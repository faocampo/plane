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
from plane.curve.models import AuditEvent, AuditOutcome, DataClassification, PolicyDecision, Product
from plane.curve.policy_services import CurvePolicyDenied, CurvePolicyResourceNotFound, correlation_id_for_request
from plane.db.models import Workspace, WorkspaceMember


PRODUCT_POLICY_KEY = "CURVE_PRODUCT_POLICY"
PRODUCT_POLICY_VERSION = 1
PRODUCT_POLICY_DIGEST = "sha256:37e93b93cf9a3b6e560f5123fc147353127ba8be8aadba7b6c3dbb7a73fbbd06"
PRODUCT_ACTIONS = frozenset(
    {
        "CURVE.PRODUCT.CREATE",
        "CURVE.PRODUCT.READ",
        "CURVE.PRODUCT.UPDATE_METADATA",
        "CURVE.PRODUCT.ARCHIVE",
        "CURVE.PRODUCT.RESTORE",
        "CURVE.PRODUCT.REASSIGN_OWNER",
    }
)
_ADMIN_ACTIONS = frozenset(
    {
        "CURVE.PRODUCT.CREATE",
        "CURVE.PRODUCT.ARCHIVE",
        "CURVE.PRODUCT.RESTORE",
        "CURVE.PRODUCT.REASSIGN_OWNER",
    }
)
_RECEIPT_TOKEN = object()
_ACTIVE_RECEIPT: ContextVar[object | None] = ContextVar("curve_product_policy_receipt", default=None)


@dataclass(frozen=True, slots=True)
class ProductPolicyReceipt:
    decision_id: uuid.UUID
    action: str
    workspace_id: uuid.UUID
    resource_ref: Mapping[str, object]
    actor: Mapping[str, str]
    correlation_id: str
    _token: object


@dataclass(frozen=True, slots=True)
class ProductQueryAuthorization:
    workspace: Workspace
    product: Product | None
    decision_id: uuid.UUID
    actor: Mapping[str, str]
    correlation_id: str


def _canonical_digest(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _load_policy() -> dict:
    path = Path(__file__).resolve().parent / "contracts" / "policy" / "product-policy-v1.json"
    payload = path.read_bytes()
    if f"sha256:{hashlib.sha256(payload).hexdigest()}" != PRODUCT_POLICY_DIGEST:
        raise RuntimeError("Curve Product policy integrity check failed")
    policy = json.loads(payload)
    if policy.get("policy_key") != PRODUCT_POLICY_KEY or policy.get("policy_version") != PRODUCT_POLICY_VERSION:
        raise RuntimeError("Curve Product policy identity is invalid")
    return policy


PRODUCT_POLICY = _load_policy()


def _actor(user) -> dict[str, str]:
    return {"actor_type": "HUMAN", "actor_id": str(user.id)}


def _workspace_membership(*, workspace_id, user):
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return (
        WorkspaceMember.objects.filter(
            workspace_id=workspace_id,
            member_id=user.id,
            is_active=True,
        )
        .only("workspace_id", "member_id", "role", "is_active")
        .first()
    )


def _resource_ref(*, workspace, product_id=None, product=None) -> dict[str, object]:
    if product_id is None:
        return {"resource_type": "WORKSPACE", "resource_id": str(workspace.id), "resource_version": 1}
    reference = {"resource_type": "PRODUCT", "resource_id": str(product_id)}
    if product is not None:
        reference["resource_version"] = product.version
    return reference


def _resolve_product_id(product_id) -> uuid.UUID:
    try:
        return uuid.UUID(str(product_id))
    except (TypeError, ValueError) as error:
        raise CurvePolicyResourceNotFound from error


def _reason_codes(*, request, workspace, membership, action, product, product_id) -> tuple[str, ...]:
    if action not in PRODUCT_ACTIONS:
        return ("UNKNOWN_ACTION",)
    if not is_curve_enabled_for_workspace(workspace.slug):
        return ("FEATURE_DISABLED",)
    if request.user is None or not getattr(request.user, "is_authenticated", False):
        return ("UNAUTHENTICATED",)
    if membership is None:
        return ("INACTIVE_MEMBERSHIP",)
    if product_id is not None and product is None:
        return ("RESOURCE_NOT_FOUND",)
    if action == "CURVE.PRODUCT.READ":
        return ("ALLOW",)
    if action in _ADMIN_ACTIONS:
        return ("ALLOW",) if membership.role == 20 else ("WORKSPACE_ADMINISTRATOR_REQUIRED",)
    if action == "CURVE.PRODUCT.UPDATE_METADATA":
        if membership.role == 20 or product.owner_user_id == request.user.id:
            return ("ALLOW",)
        return ("PRODUCT_OWNER_OR_ADMINISTRATOR_REQUIRED",)
    return ("UNKNOWN_ACTION",)


def _record_decision(*, workspace, action, resource_ref, actor, correlation_id, reason_codes) -> PolicyDecision:
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
        policy_key=PRODUCT_POLICY_KEY,
        policy_version=PRODUCT_POLICY_VERSION,
        policy_manifest_digest=PRODUCT_POLICY_DIGEST,
        input_digest=_canonical_digest(input_document),
        normalized_classification=DataClassification.INTERNAL,
        permitted_projection=["PRODUCT_SAFE_METADATA"] if allowed else [],
        correlation_id=correlation_id,
        evaluated_at=evaluated_at,
        recorded_at=evaluated_at,
        recorded_by=curve_policy_recorder(),
    )


def _decision_ref(decision_id) -> dict[str, object]:
    return {
        "resource_type": "POLICY_DECISION",
        "resource_id": str(decision_id),
        "resource_version": 1,
    }


def _append_policy_audit(*, workspace, action, resource_ref, actor, correlation_id, decision, outcome):
    from plane.curve.services import _append_audit_event

    return _append_audit_event(
        workspace_id=workspace.id,
        action=action,
        target_ref=resource_ref,
        outcome=outcome,
        actor=actor,
        effective_principal=actor,
        correlation_id=correlation_id,
        policy_decision_ref=_decision_ref(decision.id),
    )


def _load_context(*, request, workspace_slug, action, product_id=None, for_update=False):
    workspace_query = Workspace.objects.select_for_update() if for_update else Workspace.objects
    try:
        workspace = workspace_query.only("id", "slug", "owner_id").get(slug=workspace_slug)
    except Workspace.DoesNotExist as error:
        raise CurvePolicyResourceNotFound from error
    membership = _workspace_membership(workspace_id=workspace.id, user=request.user)
    resolved_id = _resolve_product_id(product_id) if product_id is not None else None
    product = None
    if resolved_id is not None and membership is not None and is_curve_enabled_for_workspace(workspace.slug):
        product = Product.objects.find_by_id(
            workspace_id=workspace.id,
            record_id=resolved_id,
            for_update=for_update,
        )
    resource_ref = _resource_ref(
        workspace=workspace,
        product_id=resolved_id,
        product=product,
    )
    actor = _actor(request.user)
    reasons = _reason_codes(
        request=request,
        workspace=workspace,
        membership=membership,
        action=action,
        product=product,
        product_id=resolved_id,
    )
    return workspace, membership, product, resource_ref, actor, reasons


def authorize_product_query(*, request, workspace_slug, product_id=None) -> ProductQueryAuthorization:
    pending_error = None
    authorization = None
    correlation_id = correlation_id_for_request(request)
    with transaction.atomic():
        workspace, _, product, resource_ref, actor, reasons = _load_context(
            request=request,
            workspace_slug=workspace_slug,
            action="CURVE.PRODUCT.READ",
            product_id=product_id,
        )
        decision = _record_decision(
            workspace=workspace,
            action="CURVE.PRODUCT.READ",
            resource_ref=resource_ref,
            actor=actor,
            correlation_id=correlation_id,
            reason_codes=reasons,
        )
        if reasons != ("ALLOW",):
            _append_policy_audit(
                workspace=workspace,
                action="CURVE.PRODUCT.READ",
                resource_ref=resource_ref,
                actor=actor,
                correlation_id=correlation_id,
                decision=decision,
                outcome=AuditOutcome.DENIED,
            )
            pending_error = CurvePolicyDenied(reason_codes=reasons, decision_id=decision.id)
        else:
            _append_policy_audit(
                workspace=workspace,
                action="CURVE.PRODUCT.READ",
                resource_ref=resource_ref,
                actor=actor,
                correlation_id=correlation_id,
                decision=decision,
                outcome=AuditOutcome.ALLOWED,
            )
            authorization = ProductQueryAuthorization(
                workspace=workspace,
                product=product,
                decision_id=decision.id,
                actor=MappingProxyType(actor),
                correlation_id=correlation_id,
            )
    if pending_error is not None:
        raise pending_error
    return authorization


def assert_product_receipt(receipt, *, action, workspace_id):
    if (
        not isinstance(receipt, ProductPolicyReceipt)
        or receipt._token is not _RECEIPT_TOKEN
        or _ACTIVE_RECEIPT.get() is not receipt
        or receipt.action != action
        or receipt.workspace_id != workspace_id
        or not transaction.get_connection().in_atomic_block
    ):
        raise PermissionError("an active Product authorization receipt is required")


def append_product_mutation_audit(
    receipt,
    *,
    action,
    target_ref,
    outcome,
    before_digest=None,
    after_digest=None,
    key_digest=None,
):
    assert_product_receipt(receipt, action=receipt.action, workspace_id=receipt.workspace_id)
    from plane.curve.services import _append_audit_event

    return _append_audit_event(
        workspace_id=receipt.workspace_id,
        action=action,
        target_ref=target_ref,
        outcome=outcome,
        actor=dict(receipt.actor),
        effective_principal=dict(receipt.actor),
        correlation_id=receipt.correlation_id,
        before_digest=before_digest,
        after_digest=after_digest,
        key_digest=key_digest,
        policy_decision_ref=_decision_ref(receipt.decision_id),
    )


def execute_product_mutation(
    *,
    request,
    workspace_slug: str,
    action: str,
    callback: Callable,
    product_id=None,
    no_effect_exceptions=(),
):
    pending_error = None
    result = None
    correlation_id = correlation_id_for_request(request)
    with transaction.atomic():
        workspace, _, product, resource_ref, actor, reasons = _load_context(
            request=request,
            workspace_slug=workspace_slug,
            action=action,
            product_id=product_id,
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
            _append_policy_audit(
                workspace=workspace,
                action=action,
                resource_ref=resource_ref,
                actor=actor,
                correlation_id=correlation_id,
                decision=decision,
                outcome=AuditOutcome.DENIED,
            )
            pending_error = CurvePolicyDenied(reason_codes=reasons, decision_id=decision.id)
        else:
            receipt = ProductPolicyReceipt(
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
                    result = callback(receipt, workspace, product)
                except no_effect_exceptions as error:
                    append_product_mutation_audit(
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
                raise RuntimeError("Product mutation must append exactly one linked audit event")
    if pending_error is not None:
        raise pending_error
    return result
