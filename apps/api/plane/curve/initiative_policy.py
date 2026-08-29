# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import json
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

from django.db import transaction
from django.utils import timezone

from plane.curve.config import curve_policy_recorder, is_curve_enabled_for_workspace
from plane.curve.models import (
    AuditEvent,
    AuditOutcome,
    DataClassification,
    GateAssignment,
    Initiative,
    PolicyDecision,
)
from plane.curve.policy_services import CurvePolicyDenied, CurvePolicyResourceNotFound, correlation_id_for_request
from plane.db.models import Workspace, WorkspaceMember


INITIATIVE_POLICY_KEY = "CURVE_INITIATIVE_POLICY"
INITIATIVE_POLICY_VERSION = 1
INITIATIVE_POLICY_DIGEST = "sha256:df9aa96d5de46232074abcc51fbb268beda0b73b45906c986f106b2d317adf8b"
INITIATIVE_ACTIONS = frozenset(
    {
        "CURVE.INITIATIVE.CREATE",
        "CURVE.INITIATIVE.READ",
        "CURVE.INITIATIVE.UPDATE_DRAFT",
        "CURVE.INITIATIVE.ACCEPT_REFINEMENT",
        "CURVE.INITIATIVE.PAUSE",
        "CURVE.INITIATIVE.RESUME",
        "CURVE.INITIATIVE.CANCEL",
    }
)
_CREATOR_OR_ADMIN_ACTIONS = frozenset({"CURVE.INITIATIVE.UPDATE_DRAFT"})
_CREATOR_ONLY_ACTIONS = frozenset({"CURVE.INITIATIVE.ACCEPT_REFINEMENT"})
_CREATOR_APPROVER_ADMIN_ACTIONS = frozenset(
    {"CURVE.INITIATIVE.PAUSE", "CURVE.INITIATIVE.RESUME", "CURVE.INITIATIVE.CANCEL"}
)
_RECEIPT_TOKEN = object()
_ACTIVE_RECEIPT: ContextVar[object | None] = ContextVar("curve_initiative_policy_receipt", default=None)


@dataclass(frozen=True, slots=True)
class InitiativePolicyReceipt:
    decision_id: uuid.UUID
    action: str
    workspace_id: uuid.UUID
    resource_ref: Mapping[str, object]
    actor: Mapping[str, str]
    correlation_id: str
    _token: object


@dataclass(frozen=True, slots=True)
class InitiativeQueryAuthorization:
    workspace: Workspace
    initiative: Initiative | None
    decision_id: uuid.UUID
    actor: Mapping[str, str]
    correlation_id: str


def _canonical_digest(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _load_policy() -> dict:
    path = Path(__file__).resolve().parent / "contracts" / "policy" / "initiative-policy-v1.json"
    payload = path.read_bytes()
    if f"sha256:{hashlib.sha256(payload).hexdigest()}" != INITIATIVE_POLICY_DIGEST:
        raise RuntimeError("Curve Initiative policy integrity check failed")
    policy = json.loads(payload)
    if policy.get("policy_key") != INITIATIVE_POLICY_KEY or policy.get("policy_version") != 1:
        raise RuntimeError("Curve Initiative policy identity is invalid")
    return policy


INITIATIVE_POLICY = _load_policy()


def _actor(user) -> dict[str, str]:
    return {"actor_type": "HUMAN", "actor_id": str(user.id)}


def _workspace_membership(*, workspace_id, user):
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return (
        WorkspaceMember.objects.filter(workspace_id=workspace_id, member_id=user.id, is_active=True)
        .only("workspace_id", "member_id", "role", "is_active")
        .first()
    )


def _resolve_initiative_id(value) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as error:
        raise CurvePolicyResourceNotFound from error


def _resource_ref(*, workspace, initiative_id=None, initiative=None):
    if initiative_id is None:
        return {"resource_type": "WORKSPACE", "resource_id": str(workspace.id), "resource_version": 1}
    reference = {"resource_type": "INITIATIVE", "resource_id": str(initiative_id)}
    if initiative is not None:
        reference["resource_version"] = initiative.version
    return reference


def _reason_codes(*, request, membership, action, initiative, initiative_id) -> tuple[str, ...]:
    if action not in INITIATIVE_ACTIONS:
        return ("UNKNOWN_ACTION",)
    if membership is None:
        return ("INACTIVE_MEMBERSHIP",)
    if initiative_id is not None and initiative is None:
        return ("RESOURCE_NOT_FOUND",)
    if action in {"CURVE.INITIATIVE.CREATE", "CURVE.INITIATIVE.READ"}:
        return ("ALLOW",)
    is_creator = initiative.creator_user_id == request.user.id
    is_admin = membership.role == 20
    if action in _CREATOR_OR_ADMIN_ACTIONS:
        return ("ALLOW",) if is_creator or is_admin else ("INITIATIVE_CREATOR_OR_ADMINISTRATOR_REQUIRED",)
    if action in _CREATOR_ONLY_ACTIONS:
        return ("ALLOW",) if is_creator else ("INITIATIVE_CREATOR_REQUIRED",)
    if action in _CREATOR_APPROVER_ADMIN_ACTIONS:
        is_approver = GateAssignment.objects.filter(
            workspace_id=initiative.workspace_id,
            initiative_id=initiative.id,
            approver_user_id=request.user.id,
            valid_from__lte=timezone.now(),
            valid_until__isnull=True,
        ).exists()
        return ("ALLOW",) if is_creator or is_admin or is_approver else ("INITIATIVE_AUTHORITY_REQUIRED",)
    return ("UNKNOWN_ACTION",)


def _record_decision(*, workspace, action, resource_ref, actor, correlation_id, reason_codes):
    from plane.curve.policy_services import _next_policy_sequence

    allowed = reason_codes == ("ALLOW",)
    evaluated_at = timezone.now()
    input_document = {
        "workspace_id": str(workspace.id),
        "action": action,
        "resource_ref": resource_ref,
        "actor": actor,
        "allowed": allowed,
        "reason_codes": reason_codes,
    }
    return PolicyDecision.objects.create(
        workspace_id=workspace.id,
        sequence=_next_policy_sequence(
            workspace_id=workspace.id,
            resource_type=resource_ref["resource_type"],
            resource_id=uuid.UUID(resource_ref["resource_id"]),
        ),
        action=action,
        resource_type=resource_ref["resource_type"],
        resource_id=resource_ref["resource_id"],
        resource_version=resource_ref.get("resource_version"),
        subject=actor,
        effective_principal=actor,
        effect="ALLOW" if allowed else "DENY",
        reason_codes=list(reason_codes),
        policy_key=INITIATIVE_POLICY_KEY,
        policy_version=INITIATIVE_POLICY_VERSION,
        policy_manifest_digest=INITIATIVE_POLICY_DIGEST,
        input_digest=_canonical_digest(input_document),
        normalized_classification=DataClassification.INTERNAL,
        permitted_projection=["INITIATIVE_SAFE_METADATA"] if allowed else [],
        correlation_id=correlation_id,
        evaluated_at=evaluated_at,
        recorded_at=evaluated_at,
        recorded_by=curve_policy_recorder(),
    )


def _decision_ref(decision_id):
    return {"resource_type": "POLICY_DECISION", "resource_id": str(decision_id), "resource_version": 1}


def _append_audit(*, workspace_id, action, target_ref, actor, correlation_id, decision_id, outcome, **digests):
    from plane.curve.services import _append_audit_event

    return _append_audit_event(
        workspace_id=workspace_id,
        action=action,
        target_ref=target_ref,
        outcome=outcome,
        actor=actor,
        effective_principal=actor,
        correlation_id=correlation_id,
        policy_decision_ref=_decision_ref(decision_id),
        **digests,
    )


def _load_context(*, request, workspace_slug, action, initiative_id=None, for_update=False):
    workspace_query = Workspace.objects.select_for_update() if for_update else Workspace.objects
    try:
        workspace = workspace_query.only("id", "slug", "owner_id").get(slug=workspace_slug)
    except Workspace.DoesNotExist as error:
        raise CurvePolicyResourceNotFound from error
    membership = _workspace_membership(workspace_id=workspace.id, user=request.user)
    resolved_id = _resolve_initiative_id(initiative_id) if initiative_id is not None else None
    initiative = None
    if resolved_id is not None and membership is not None and is_curve_enabled_for_workspace(workspace.slug):
        initiative = Initiative.objects.find_by_id(
            workspace_id=workspace.id,
            record_id=resolved_id,
            for_update=for_update,
        )
    resource_ref = _resource_ref(workspace=workspace, initiative_id=resolved_id, initiative=initiative)
    actor = _actor(request.user)
    if not is_curve_enabled_for_workspace(workspace.slug):
        reasons = ("FEATURE_DISABLED",)
    else:
        reasons = _reason_codes(
            request=request,
            membership=membership,
            action=action,
            initiative=initiative,
            initiative_id=resolved_id,
        )
    return workspace, initiative, resource_ref, actor, reasons


def authorize_initiative_query(*, request, workspace_slug, initiative_id=None):
    pending_error = None
    authorization = None
    correlation_id = correlation_id_for_request(request)
    with transaction.atomic():
        workspace, initiative, resource_ref, actor, reasons = _load_context(
            request=request,
            workspace_slug=workspace_slug,
            action="CURVE.INITIATIVE.READ",
            initiative_id=initiative_id,
        )
        decision = _record_decision(
            workspace=workspace,
            action="CURVE.INITIATIVE.READ",
            resource_ref=resource_ref,
            actor=actor,
            correlation_id=correlation_id,
            reason_codes=reasons,
        )
        outcome = AuditOutcome.ALLOWED if reasons == ("ALLOW",) else AuditOutcome.DENIED
        _append_audit(
            workspace_id=workspace.id,
            action="CURVE.INITIATIVE.READ",
            target_ref=resource_ref,
            actor=actor,
            correlation_id=correlation_id,
            decision_id=decision.id,
            outcome=outcome,
        )
        if reasons == ("ALLOW",):
            authorization = InitiativeQueryAuthorization(
                workspace=workspace,
                initiative=initiative,
                decision_id=decision.id,
                actor=MappingProxyType(actor),
                correlation_id=correlation_id,
            )
        else:
            pending_error = CurvePolicyDenied(reason_codes=reasons, decision_id=decision.id)
    if pending_error:
        raise pending_error
    return authorization


def append_initiative_mutation_audit(receipt, *, action, target_ref, outcome, **digests):
    if (
        not isinstance(receipt, InitiativePolicyReceipt)
        or receipt._token is not _RECEIPT_TOKEN
        or _ACTIVE_RECEIPT.get() is not receipt
        or not transaction.get_connection().in_atomic_block
    ):
        raise PermissionError("an active Initiative authorization receipt is required")
    return _append_audit(
        workspace_id=receipt.workspace_id,
        action=action,
        target_ref=target_ref,
        actor=dict(receipt.actor),
        correlation_id=receipt.correlation_id,
        decision_id=receipt.decision_id,
        outcome=outcome,
        **digests,
    )


def execute_initiative_mutation(
    *, request, workspace_slug: str, action: str, callback: Callable, initiative_id=None, no_effect_exceptions=()
):
    pending_error = None
    result = None
    correlation_id = correlation_id_for_request(request)
    with transaction.atomic():
        workspace, initiative, resource_ref, actor, reasons = _load_context(
            request=request,
            workspace_slug=workspace_slug,
            action=action,
            initiative_id=initiative_id,
            for_update=True,
        )
        decision = _record_decision(
            workspace=workspace,
            action=action,
            resource_ref=resource_ref,
            actor=actor,
            correlation_id=correlation_id,
            reason_codes=reasons,
        )
        if reasons != ("ALLOW",):
            _append_audit(
                workspace_id=workspace.id,
                action=action,
                target_ref=resource_ref,
                actor=actor,
                correlation_id=correlation_id,
                decision_id=decision.id,
                outcome=AuditOutcome.DENIED,
            )
            pending_error = CurvePolicyDenied(reason_codes=reasons, decision_id=decision.id)
        else:
            receipt = InitiativePolicyReceipt(
                decision_id=decision.id,
                action=action,
                workspace_id=workspace.id,
                resource_ref=MappingProxyType(dict(resource_ref)),
                actor=MappingProxyType(actor),
                correlation_id=correlation_id,
                _token=_RECEIPT_TOKEN,
            )
            token = _ACTIVE_RECEIPT.set(receipt)
            try:
                try:
                    result = callback(receipt, workspace, initiative)
                except no_effect_exceptions as error:
                    append_initiative_mutation_audit(
                        receipt,
                        action=action,
                        target_ref=dict(receipt.resource_ref),
                        outcome=AuditOutcome.NO_EFFECT,
                    )
                    pending_error = error
            finally:
                _ACTIVE_RECEIPT.reset(token)
            linked_audits = AuditEvent.objects.filter(
                policy_decision_ref__resource_type="POLICY_DECISION",
                policy_decision_ref__resource_id=str(decision.id),
                policy_decision_ref__resource_version=1,
            ).count()
            if linked_audits != 1:
                raise RuntimeError("Initiative mutation must append exactly one linked audit event")
    if pending_error:
        raise pending_error
    return result
