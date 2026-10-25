# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Scoped Roadmap command authority; transport activation has a separate default-off gate."""

import hashlib
import json
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from types import MappingProxyType
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from plane.curve.config import curve_policy_recorder, is_curve_enabled_for_workspace
from plane.curve.models import AuditEvent, AuditOutcome, DataClassification, PolicyDecision, Product, Roadmap
from plane.curve.product_format import require_supported_product_format
from plane.curve.policy_services import (
    CurvePolicyDenied,
    CurvePolicyResourceNotFound,
    correlation_id_for_request,
    _next_policy_sequence,
)
from plane.curve.services import _append_audit_event
from plane.db.models import User, Workspace, WorkspaceMember

ACTIONS = frozenset({"CREATE_ROADMAP", "UPDATE_ROADMAP", "CREATE_MILESTONE", "UPDATE_MILESTONE", "REORDER_MILESTONES"})
POLICY = {
    "policy_key": "CURVE_ROADMAP_HIERARCHY_POLICY",
    "policy_version": 1,
    "create": ["PRODUCT_OWNER", "WORKSPACE_ADMINISTRATOR"],
    "mutate": ["ROADMAP_OWNER"],
    "active_human_required": True,
    "active_product_required": True,
    "initial_owner": "AUTHENTICATED_CREATOR",
    "actions": sorted(ACTIONS),
}
POLICY_DIGEST = (
    "sha256:" + hashlib.sha256(json.dumps(POLICY, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
)
if json.loads((Path(__file__).parent / "roadmap_domain/hierarchy-policy-v1.json").read_bytes()) != POLICY:
    raise RuntimeError("ROADMAP_POLICY_CONTRACT_CHANGED")

_TOKEN = object()
_ACTIVE = ContextVar("curve_roadmap_receipt", default=None)


@dataclass(frozen=True, slots=True)
class RoadmapReceipt:
    decision_id: uuid.UUID
    action: str
    workspace_id: uuid.UUID
    product_id: uuid.UUID
    roadmap_id: uuid.UUID | None
    actor: object
    correlation_id: str
    resource_ref: object
    _token: object


def assert_receipt(receipt):
    if (
        not isinstance(receipt, RoadmapReceipt)
        or receipt._token is not _TOKEN
        or _ACTIVE.get() is not receipt
        or not transaction.get_connection().in_atomic_block
    ):
        raise PermissionError("an active Roadmap authorization receipt is required")


def append_audit(receipt, *, target_ref, outcome, key_digest=None, after_digest=None, replay=False):
    assert_receipt(receipt)
    return _append_audit_event(
        workspace_id=receipt.workspace_id,
        action=f"CURVE.ROADMAP.{receipt.action}" + (".IDEMPOTENT_REPLAY" if replay else ""),
        target_ref=target_ref,
        outcome=outcome,
        actor=dict(receipt.actor),
        effective_principal=dict(receipt.actor),
        correlation_id=receipt.correlation_id,
        key_digest=key_digest,
        after_digest=after_digest,
        policy_decision_ref={
            "resource_type": "POLICY_DECISION",
            "resource_id": str(receipt.decision_id),
            "resource_version": 1,
        },
    )


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise CurvePolicyResourceNotFound from error


def execute_mutation(*, request, workspace_slug, product_id, roadmap_id, action, callback, no_effect_exceptions):
    """Lock authoritative scope, authorize before replay, retain one audit per decision."""
    if action not in ACTIONS:
        raise CurvePolicyDenied(reason_codes=("UNKNOWN_ACTION",), decision_id=None)
    # Unauthenticated callers have no trusted human identity for a policy receipt.
    user = request.user
    if user is None or not getattr(user, "is_authenticated", False):
        raise CurvePolicyResourceNotFound
    product_id = _uuid(product_id)
    roadmap_id = _uuid(roadmap_id) if roadmap_id is not None else None
    error = result = None
    correlation = correlation_id_for_request(request)
    with transaction.atomic():
        from plane.curve.scope_reopening_qualification import require_roadmap_hierarchy_qualification

        require_roadmap_hierarchy_qualification()
        workspace = Workspace.objects.select_for_update().filter(slug=workspace_slug).first()
        if workspace is None:
            raise CurvePolicyResourceNotFound
        actor = {"actor_type": "HUMAN", "actor_id": str(user.id)}
        # Lock membership as well as workspace: direct membership updates serialize here.
        membership = (
            WorkspaceMember.objects.select_for_update().filter(workspace_id=workspace.id, member_id=user.id).first()
        )
        human = User.objects.select_for_update().filter(id=user.id, is_active=True, is_bot=False).exists()
        product = roadmap = None
        reason = "ALLOW"
        if not is_curve_enabled_for_workspace(workspace.slug):
            reason = "FEATURE_DISABLED"
        elif not human or membership is None or not membership.is_active:
            reason = "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"
        else:
            product = Product.objects.select_for_update().filter(workspace_id=workspace.id, id=product_id).first()
            if product is None:
                reason = "RESOURCE_UNAVAILABLE"
            elif action == "CREATE_ROADMAP":
                if roadmap_id is not None:
                    reason = "RESOURCE_UNAVAILABLE"
                elif product.owner_user_id != user.id and membership.role != 20:
                    reason = "PRODUCT_OWNER_OR_ADMINISTRATOR_REQUIRED"
            else:
                roadmap = (
                    Roadmap.objects.select_for_update()
                    .filter(workspace_id=workspace.id, product_id=product.id, id=roadmap_id)
                    .first()
                )
                if roadmap is None or roadmap.tombstoned_at is not None:
                    reason = "RESOURCE_UNAVAILABLE"
                elif roadmap.owner_user_id != user.id:
                    reason = "ROADMAP_OWNER_REQUIRED"
            if reason == "ALLOW" and product.state != "ACTIVE":
                reason = "PRODUCT_UNAVAILABLE"
        ref = {"resource_type": "ROADMAP" if roadmap_id else "PRODUCT", "resource_id": str(roadmap_id or product_id)}
        if reason == "ALLOW":
            ref["resource_version"] = roadmap.version if roadmap else product.version
        decision_input = {
            "workspace_id": str(workspace.id),
            "product_id": str(product_id),
            "action": action,
            "resource_ref": ref,
            "actor": actor,
            "reason": reason,
        }
        at = timezone.now()
        decision = PolicyDecision.objects.create(
            workspace_id=workspace.id,
            sequence=_next_policy_sequence(
                workspace_id=workspace.id, resource_type=ref["resource_type"], resource_id=uuid.UUID(ref["resource_id"])
            ),
            action=f"CURVE.ROADMAP.{action}",
            resource_type=ref["resource_type"],
            resource_id=ref["resource_id"],
            resource_version=ref.get("resource_version"),
            subject=actor,
            effective_principal=actor,
            effect="ALLOW" if reason == "ALLOW" else "DENY",
            reason_codes=[reason],
            policy_key=POLICY["policy_key"],
            policy_version=1,
            policy_manifest_digest=POLICY_DIGEST,
            input_digest="sha256:"
            + hashlib.sha256(json.dumps(decision_input, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            normalized_classification=DataClassification.INTERNAL,
            permitted_projection=["ROADMAP_SAFE_METADATA"] if reason == "ALLOW" else [],
            correlation_id=correlation,
            evaluated_at=at,
            recorded_at=at,
            recorded_by=curve_policy_recorder(),
        )
        receipt = RoadmapReceipt(
            decision.id,
            action,
            workspace.id,
            product_id,
            roadmap_id,
            MappingProxyType(actor),
            correlation,
            MappingProxyType(ref),
            _TOKEN,
        )
        token = _ACTIVE.set(receipt)
        try:
            if reason != "ALLOW":
                append_audit(receipt, target_ref=ref, outcome=AuditOutcome.DENIED)
                error = CurvePolicyDenied(reason_codes=(reason,), decision_id=decision.id)
            else:
                try:
                    # Savepoint contains every mutation, including deferred checks.
                    with transaction.atomic():
                        require_supported_product_format(product)
                        if roadmap is not None and roadmap.schema_version != "1.0":
                            raise RoadmapFormatUnavailable
                        result = callback(receipt, product, roadmap)
                except no_effect_exceptions as caught:
                    append_audit(receipt, target_ref=ref, outcome=AuditOutcome.NO_EFFECT)
                    error = caught
            if (
                AuditEvent.objects.filter(
                    workspace_id=workspace.id, policy_decision_ref__resource_id=str(decision.id)
                ).count()
                != 1
            ):
                raise RuntimeError("Roadmap command requires exactly one linked audit")
        finally:
            _ACTIVE.reset(token)
    if error is not None:
        raise error
    return result


class RoadmapFormatUnavailable(Exception):
    code = "ROADMAP_FORMAT_UNAVAILABLE"
