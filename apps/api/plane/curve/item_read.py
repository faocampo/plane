# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Bounded Item metadata and assigned review stages, without protected material."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from plane.curve.config import curve_policy_recorder
from plane.curve.feature_authority_facts import resolve_feature_facts
from plane.curve.models import (
    AuditOutcome,
    DataClassification,
    Feature,
    GateAssignment,
    Initiative,
    Milestone,
    PolicyDecision,
    Roadmap,
    RoadmapItem,
)
from plane.curve.policy_services import (
    CurvePolicyDenied,
    CurvePolicyResourceNotFound,
    correlation_id_for_request,
    _next_policy_sequence,
)
from plane.curve.services import _append_audit_event
from plane.db.models import Workspace

_POLICY_BYTES = (Path(__file__).parent / "items/read-policy-v1.json").read_bytes()
if hashlib.sha256(_POLICY_BYTES).hexdigest() != "fa9c1455ce237c586d3d1da9882433333d7f5c6d633b4e867bf6c48c0b7a45d3":
    raise RuntimeError("ITEM_READ_POLICY_CONTRACT_CHANGED")
POLICY = json.loads(_POLICY_BYTES)
POLICY_DIGEST = (
    "sha256:" + hashlib.sha256(json.dumps(POLICY, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
)


def _read_reason(facts):
    if not facts.feature_enabled:
        return "FEATURE_DISABLED"
    if not facts.actor_active_human or not facts.actor_active_member:
        return "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"
    if not facts.product_active:
        return "PRODUCT_UNAVAILABLE"
    if not facts.product_format_supported:
        return "FORMAT_UNAVAILABLE"
    return "ALLOW"


def _record_read(*, workspace_id, action, ref, actor, correlation, reason, facts):
    at = timezone.now()
    document = {
        "action": action,
        "resource_ref": ref,
        "actor": actor,
        "reason": reason,
        "native_facts": asdict(facts) if facts else None,
    }
    allowed = reason == "ALLOW"
    decision = PolicyDecision.objects.create(
        workspace_id=workspace_id,
        sequence=_next_policy_sequence(
            workspace_id=workspace_id, resource_type=ref["resource_type"], resource_id=UUID(ref["resource_id"])
        ),
        action=f"CURVE.ITEM.{action}",
        resource_type=ref["resource_type"],
        resource_id=ref["resource_id"],
        resource_version=ref.get("resource_version"),
        subject=actor,
        effective_principal=actor,
        effect="ALLOW" if allowed else "DENY",
        reason_codes=[reason],
        policy_key=POLICY["policy_key"],
        policy_version=1,
        policy_manifest_digest=POLICY_DIGEST,
        input_digest="sha256:"
        + hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest(),
        normalized_classification=DataClassification.INTERNAL,
        permitted_projection=POLICY["projection"] if allowed else [],
        correlation_id=correlation,
        evaluated_at=at,
        recorded_at=at,
        recorded_by=curve_policy_recorder(),
    )
    _append_audit_event(
        workspace_id=workspace_id,
        action=f"CURVE.ITEM.{action}",
        target_ref=ref,
        outcome=AuditOutcome.SUCCEEDED if allowed else AuditOutcome.DENIED,
        actor=actor,
        effective_principal=actor,
        correlation_id=correlation,
        policy_decision_ref={
            "resource_type": "POLICY_DECISION",
            "resource_id": str(decision.id),
            "resource_version": 1,
        },
    )
    return decision


def item_metadata(item, initiative, assignments):
    """An explicit projection; approval results require their independent read path."""
    current = {}
    for assignment in assignments:
        if assignment.gate_type not in {"PRD_APPROVAL", "PLAN_APPROVAL"} or assignment.gate_type in current:
            raise CurvePolicyResourceNotFound
        current[assignment.gate_type] = str(assignment.approver_user_id)
    return {
        "id": str(item.id),
        "version": item.version,
        "roadmap_id": str(item.roadmap_id),
        "milestone_id": str(item.milestone_id),
        "feature_id": str(item.feature_id),
        "owner_user_id": str(item.owner_user_id),
        "status": item.status,
        "priority": item.priority,
        "confidence": item.confidence,
        "health": item.health,
        "planned_start": item.planned_start.isoformat() if item.planned_start else None,
        "planned_end": item.planned_end.isoformat() if item.planned_end else None,
        "declared_progress": item.declared_progress,
        "initiative": {
            "id": str(initiative.id),
            "version": initiative.version,
            "keyword": initiative.keyword,
            "title": initiative.title,
            "state": initiative.state,
        },
        "approval_stages": [
            {"role": role, "gate_type": gate, "approver_user_id": current.get(gate)}
            for role, gate in (("PRODUCT", "PRD_APPROVAL"), ("TECHNICAL", "PLAN_APPROVAL"))
        ],
    }


def _page(*, workspace_id, product_id, roadmap_id, page_size, after):
    scope = {"workspace_id": workspace_id, "product_id": product_id, "tombstoned_at__isnull": True}
    parent = Roadmap.objects.select_for_update(no_key=True).filter(**scope, id=roadmap_id).first()
    if parent is None or parent.schema_version != "1.0":
        raise CurvePolicyResourceNotFound
    query = RoadmapItem.objects.select_for_update(no_key=True).filter(**scope, roadmap_id=parent.id).order_by("id")
    if after is not None:
        query = query.filter(id__gt=after)
    rows = list(query[: page_size + 1])
    selected = rows[:page_size]
    features = {
        row.id: row
        for row in Feature.objects.select_for_update(no_key=True)
        .filter(**scope, id__in=[item.feature_id for item in selected])
        .order_by("id")
    }
    milestones = {
        row.id: row
        for row in Milestone.objects.select_for_update(no_key=True)
        .filter(**scope, roadmap_id=parent.id, id__in=[item.milestone_id for item in selected])
        .order_by("id")
    }
    initiatives = {
        row.id: row
        for row in Initiative.objects.select_for_update()
        .filter(
            workspace_id=workspace_id,
            product_id=product_id,
            mode="ROADMAP",
            id__in=[item.defining_initiative_id for item in selected],
        )
        .order_by("id")
    }
    at = timezone.now()
    assignments = {}
    for assignment in (
        GateAssignment.objects.select_for_update()
        .filter(
            workspace_id=workspace_id,
            initiative_id__in=initiatives,
            valid_from__lte=at,
        )
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gt=at))
        .order_by("initiative_id", "gate_type", "id")
    ):
        assignments.setdefault(assignment.initiative_id, []).append(assignment)
    output = []
    for item in selected:
        initiative = initiatives.get(item.defining_initiative_id)
        feature, milestone = features.get(item.feature_id), milestones.get(item.milestone_id)
        if (
            item.schema_version != "1.0"
            or initiative is None
            or initiative.schema_version != "1.2"
            or initiative.roadmap_item_id != item.id
            or feature is None
            or milestone is None
            or feature.schema_version != "1.0"
            or milestone.schema_version != "1.0"
        ):
            raise CurvePolicyResourceNotFound
        output.append(item_metadata(item, initiative, assignments.get(initiative.id, [])))
    return parent, {
        "results": output,
        "next_cursor": str(selected[-1].id) if len(rows) > page_size else None,
        "roadmap_version": parent.version,
    }


def read_items(*, request, workspace_slug, product_id, roadmap_id, page_size=50, after=None):
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise ValueError("invalid page size")
    try:
        product_id, roadmap_id = UUID(str(product_id)), UUID(str(roadmap_id))
        after = UUID(str(after)) if after is not None else None
    except (ValueError, TypeError, AttributeError) as error:
        raise CurvePolicyResourceNotFound from error
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        raise CurvePolicyResourceNotFound
    result = error = None
    with transaction.atomic(durable=True):
        from plane.curve.scope_reopening_qualification import require_item_read_qualification

        require_item_read_qualification()
        workspace = Workspace.objects.select_for_update(no_key=True).filter(slug=workspace_slug).first()
        if workspace is None:
            raise CurvePolicyResourceNotFound
        facts = None
        reason = "RESOURCE_UNAVAILABLE"
        ref = {"resource_type": "ROADMAP", "resource_id": str(roadmap_id)}
        try:
            facts = resolve_feature_facts(workspace_slug=workspace_slug, product_id=product_id, actor_id=user.id)
            reason = _read_reason(facts)
            if reason == "ALLOW" and getattr(settings, "CURVE_ENVIRONMENT", None) != "LOCAL":
                reason = "LOCAL_ITEM_PROFILE_REQUIRED"
            if reason == "ALLOW":
                parent, result = _page(
                    workspace_id=workspace.id,
                    product_id=product_id,
                    roadmap_id=roadmap_id,
                    page_size=page_size,
                    after=after,
                )
                ref["resource_version"] = parent.version
                result["can_create"] = parent.owner_user_id == user.id
        except CurvePolicyResourceNotFound:
            reason = "RESOURCE_UNAVAILABLE"
        decision = _record_read(
            workspace_id=workspace.id,
            action="LIST_ROADMAP_ITEMS",
            ref=ref,
            actor={"actor_type": "HUMAN", "actor_id": str(user.id)},
            correlation=correlation_id_for_request(request),
            reason=reason,
            facts=facts,
        )
        if reason != "ALLOW":
            error = CurvePolicyDenied(reason_codes=(reason,), decision_id=decision.id)
    if error is not None:
        raise error
    return result
