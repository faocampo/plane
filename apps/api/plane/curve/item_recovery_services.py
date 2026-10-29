# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Current-authorized receipt reconciliation; never executes an Item command."""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from plane.curve.config import curve_policy_recorder
from plane.curve.item_creation_services import _retained_pair
from plane.curve.item_recovery_rules import recovery_read_reason
from plane.curve.item_scope_authority import resolve_item_scope_facts
from plane.curve.models import AuditOutcome, DataClassification, Feature, IdempotencyRecord, Milestone, PolicyDecision
from plane.curve.policy_services import (
    CurvePolicyDenied,
    CurvePolicyResourceNotFound,
    correlation_id_for_request,
    _next_policy_sequence,
)
from plane.curve.services import _append_audit_event, idempotency_key_digest, ReplayResourceUnavailable
from plane.db.models import Workspace

_POLICY_BYTES = (Path(__file__).parent / "items/recovery-policy-v1.json").read_bytes()
if hashlib.sha256(_POLICY_BYTES).hexdigest() != "d64e4262a2b958e4ccaa828b50095021b9ff3ae372f7dd327127505b2d418616":
    raise RuntimeError("ITEM_RECOVERY_POLICY_CONTRACT_CHANGED")
POLICY = json.loads(_POLICY_BYTES)
POLICY_DIGEST = (
    "sha256:" + hashlib.sha256(json.dumps(POLICY, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
)


def _record_recovery(*, workspace_id, action, ref, actor, correlation, reason, facts):
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


def read_item_creation_receipt(*, request, workspace_slug, product_id, roadmap_id, command_key):
    try:
        product_id, roadmap_id = UUID(str(product_id)), UUID(str(roadmap_id))
        command_id = UUID(command_key)
        if str(command_id) != command_key:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise CurvePolicyResourceNotFound from None
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        raise CurvePolicyResourceNotFound
    result = error = None
    with transaction.atomic(durable=True):
        from plane.curve.scope_reopening_qualification import require_item_recovery_qualification

        require_item_recovery_qualification()
        workspace = Workspace.objects.select_for_update(no_key=True).filter(slug=workspace_slug).first()
        if workspace is None:
            raise CurvePolicyResourceNotFound
        facts = None
        reason = "RESOURCE_UNAVAILABLE"
        ref = {"resource_type": "ROADMAP", "resource_id": str(roadmap_id)}
        try:
            facts = resolve_item_scope_facts(
                workspace_slug=workspace_slug, product_id=product_id, roadmap_id=roadmap_id, actor_id=user.id
            )
            reason = recovery_read_reason(
                facts,
                enabled=getattr(settings, "CURVE_ITEM_RECOVERY_ENABLED", False) is True,
                local=getattr(settings, "CURVE_ENVIRONMENT", None) == "LOCAL",
            )
            if reason == "ALLOW":
                ref["resource_version"] = facts.roadmap_version
                retained = (
                    IdempotencyRecord.objects.select_for_update()
                    .filter(
                        workspace_id=workspace.id,
                        principal_scope=f"HUMAN:{user.id}",
                        command_scope=f"CURVE.ITEM.CREATE_ROADMAP_ITEM_INITIATIVE:{product_id}:{roadmap_id}",
                        key_digest=idempotency_key_digest(command_key),
                    )
                    .first()
                )
                result = {"state": "UNRESOLVED"}
                if retained is not None and retained.state == "COMPLETED":
                    # The original receipt digest and both current reciprocal rows
                    # must agree. This exposes IDs only, without protected material.
                    item = _retained_pair(
                        SimpleNamespace(workspace_id=workspace.id, product_id=product_id, roadmap_id=roadmap_id),
                        retained,
                    )
                    live = {
                        "workspace_id": workspace.id,
                        "product_id": product_id,
                        "tombstoned_at__isnull": True,
                        "schema_version": "1.0",
                    }
                    if not Feature.objects.select_for_update(no_key=True).filter(**live, id=item.feature_id).exists():
                        raise CurvePolicyResourceNotFound
                    if (
                        not Milestone.objects.select_for_update(no_key=True)
                        .filter(**live, id=item.milestone_id, roadmap_id=roadmap_id)
                        .exists()
                    ):
                        raise CurvePolicyResourceNotFound
                    result = {"state": "COMPLETED", "resource_ref": deepcopy(retained.response_resource_ref)}
        except (CurvePolicyResourceNotFound, ReplayResourceUnavailable):
            reason = "RESOURCE_UNAVAILABLE"
        decision = _record_recovery(
            workspace_id=workspace.id,
            action="READ_ITEM_CREATION_RECEIPT",
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
