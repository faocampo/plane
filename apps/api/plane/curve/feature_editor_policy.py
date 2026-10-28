# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Current owner/admin editor-management authority over locked server records.

Integration requires the separate command qualification successor and exact
PolicyDecision manifest constraint. This module never activates HTTP routes.
"""

from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
import uuid

from django.db import connection, transaction
from django.utils import timezone

from plane.curve.config import curve_policy_recorder, is_curve_enabled_for_workspace
from plane.curve.feature_editor_rules import FeatureEditorFacts, feature_editor_reason
from plane.curve.models import (
    AuditEvent,
    AuditOutcome,
    DataClassification,
    PolicyDecision,
    Product,
)
from plane.curve.policy_services import (
    CurvePolicyDenied,
    CurvePolicyResourceNotFound,
    correlation_id_for_request,
    _next_policy_sequence,
)
from plane.curve.product_format import (
    ProductFormatUnavailable,
    require_supported_product_format,
)
from plane.curve.services import _append_audit_event
from plane.db.models import User, Workspace, WorkspaceMember


_POLICY_BYTES = (Path(__file__).parent / "feature_editors/command-policy-v1.json").read_bytes()
if hashlib.sha256(_POLICY_BYTES).hexdigest() != "ba25ea05f1236657dd753aa8e9c3ba6b205fe48b1c8b7344186fc139f0d3509d":
    raise RuntimeError("FEATURE_EDITOR_POLICY_CONTRACT_CHANGED")
POLICY = json.loads(_POLICY_BYTES)
POLICY_DIGEST = (
    "sha256:" + hashlib.sha256(json.dumps(POLICY, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
)
ACTIONS = frozenset({"GRANT_FEATURE_EDITOR", "REVOKE_FEATURE_EDITOR"})
_TOKEN = object()
_ACTIVE = ContextVar("curve_feature_editor_receipt", default=None)
_GRANT_FIELDS = (
    "id",
    "version",
    "workspace_id",
    "product_id",
    "member_id",
    "membership_id",
    "membership_generation",
    "granted_by",
    "granted_at",
    "revoked_by",
    "revoked_at",
)


@dataclass(frozen=True, slots=True)
class FeatureEditorReceipt:
    decision_id: uuid.UUID
    action: str
    workspace_id: uuid.UUID
    product_id: uuid.UUID
    grant_id: uuid.UUID | None
    target_member_id: uuid.UUID | None
    target_membership_id: uuid.UUID | None
    target_membership_generation: int | None
    actor: object
    correlation_id: str
    resource_ref: object
    _token: object


def assert_receipt(receipt):
    if (
        not isinstance(receipt, FeatureEditorReceipt)
        or receipt._token is not _TOKEN
        or _ACTIVE.get() is not receipt
        or not transaction.get_connection().in_atomic_block
    ):
        raise PermissionError("an active Feature editor authorization receipt is required")


def append_audit(receipt, *, target_ref, outcome, key_digest=None, after_digest=None, replay=False):
    assert_receipt(receipt)
    return _append_audit_event(
        workspace_id=receipt.workspace_id,
        action=f"CURVE.FEATURE_EDITOR.{receipt.action}" + (".IDEMPOTENT_REPLAY" if replay else ""),
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


def scoped_grant(*, workspace_id, product_id, grant_id, lock=False):
    """Internal scoped lookup; permission decisions precede any caller projection."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT " + ",".join(_GRANT_FIELDS) + " FROM curve_feature_editor_grant "
            "WHERE workspace_id=%s AND product_id=%s AND id=%s" + (" FOR UPDATE" if lock else ""),
            [workspace_id, product_id, grant_id],
        )
        row = cursor.fetchone()
    return dict(zip(_GRANT_FIELDS, row, strict=True)) if row is not None else None


def _active_human(user):
    return user is not None and user.is_active and not user.is_bot


def _active_member(member):
    return member is not None and member.is_active and member.deleted_at is None


def execute_editor_mutation(
    *,
    request,
    workspace_slug,
    product_id,
    action,
    callback,
    no_effect_exceptions,
    target_member_id=None,
    grant_id=None,
):
    if action not in ACTIONS:
        raise CurvePolicyDenied(reason_codes=("UNKNOWN_ACTION",), decision_id=None)
    user = request.user
    if user is None or not getattr(user, "is_authenticated", False):
        raise CurvePolicyResourceNotFound
    product_id = _uuid(product_id)
    if action == "GRANT_FEATURE_EDITOR":
        if grant_id is not None:
            raise CurvePolicyResourceNotFound
        target_member_id = _uuid(target_member_id)
    else:
        if target_member_id is not None:
            raise CurvePolicyResourceNotFound
        grant_id = _uuid(grant_id)
    error = result = None
    correlation = correlation_id_for_request(request)
    with transaction.atomic():
        from plane.curve.scope_reopening_qualification import (
            require_feature_editor_command_qualification,
        )

        require_feature_editor_command_qualification()
        # Keep authority rows stable while allowing deferred foreign-key checks
        # from a concurrent membership update to finish before we take its lock.
        workspace = Workspace.objects.select_for_update(no_key=True).filter(slug=workspace_slug).first()
        if workspace is None:
            raise CurvePolicyResourceNotFound
        # Grant scope and recipient are immutable; this initial read identifies
        # membership locks. Re-read the whole record under lock below.
        original = (
            scoped_grant(workspace_id=workspace.id, product_id=product_id, grant_id=grant_id) if grant_id else None
        )
        if original is not None:
            target_member_id = original["member_id"]
        identities = {user.id}
        if target_member_id is not None:
            identities.add(target_member_id)
        memberships = list(
            WorkspaceMember.objects.select_for_update(no_key=True)
            .filter(workspace_id=workspace.id, member_id__in=identities)
            .order_by("id")
        )
        members = {row.member_id: row for row in memberships}
        humans = {
            row.id: row for row in User.objects.select_for_update(no_key=True).filter(id__in=identities).order_by("id")
        }
        actor_member = members.get(user.id)
        target_member = members.get(target_member_id)
        product = grant = None
        target_generation = None
        reason = "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"
        if _active_human(humans.get(user.id)) and _active_member(actor_member):
            product = (
                Product.objects.select_for_update(no_key=True).filter(workspace_id=workspace.id, id=product_id).first()
            )
            if product is None:
                reason = "RESOURCE_UNAVAILABLE"
            else:
                supported = True
                try:
                    require_supported_product_format(product)
                except ProductFormatUnavailable:
                    supported = False
                facts = FeatureEditorFacts(
                    workspace_id=workspace.id,
                    product_id=product.id,
                    actor_id=user.id,
                    owner_id=product.owner_user_id,
                    actor_active_human=True,
                    actor_active_member=True,
                    actor_administrator=actor_member.role == 20,
                    product_active=product.state == "ACTIVE",
                    product_format_supported=supported,
                    feature_enabled=is_curve_enabled_for_workspace(workspace.slug),
                )
                reason = feature_editor_reason(action, facts)
        if reason == "ALLOW":
            if action == "GRANT_FEATURE_EDITOR":
                if not _active_member(target_member) or not _active_human(humans.get(target_member_id)):
                    reason = "TARGET_ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"
                else:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT generation FROM curve_feature_membership_lifetime "
                            "WHERE membership_id=%s FOR UPDATE",
                            [target_member.id],
                        )
                        lifetime = cursor.fetchone()
                    if lifetime is None:
                        reason = "TARGET_MEMBERSHIP_UNAVAILABLE"
                    else:
                        target_generation = lifetime[0]
            else:
                grant = scoped_grant(
                    workspace_id=workspace.id,
                    product_id=product_id,
                    grant_id=grant_id,
                    lock=True,
                )
                if grant is None:
                    reason = "RESOURCE_UNAVAILABLE"
        actor = {"actor_type": "HUMAN", "actor_id": str(user.id)}
        ref = {
            "resource_type": "FEATURE_EDITOR_GRANT" if grant_id else "PRODUCT",
            "resource_id": str(grant_id or product_id),
        }
        if reason == "ALLOW":
            ref["resource_version"] = grant["version"] if grant is not None else product.version
        decision_input = {
            "workspace_id": str(workspace.id),
            "product_id": str(product_id),
            "action": action,
            "resource_ref": ref,
            "actor": actor,
            "reason": reason,
            "target_member_id": str(target_member_id) if target_member_id else None,
            "target_membership_id": str(target_member.id) if target_member is not None else None,
            "target_membership_generation": target_generation,
        }
        at = timezone.now()
        decision = PolicyDecision.objects.create(
            workspace_id=workspace.id,
            sequence=_next_policy_sequence(
                workspace_id=workspace.id,
                resource_type=ref["resource_type"],
                resource_id=uuid.UUID(ref["resource_id"]),
            ),
            action=f"CURVE.FEATURE_EDITOR.{action}",
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
            permitted_projection=["FEATURE_EDITOR_METADATA"] if reason == "ALLOW" else [],
            correlation_id=correlation,
            evaluated_at=at,
            recorded_at=at,
            recorded_by=curve_policy_recorder(),
        )
        receipt = FeatureEditorReceipt(
            decision.id,
            action,
            workspace.id,
            product_id,
            grant_id,
            target_member_id,
            target_member.id if target_member is not None else None,
            target_generation,
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
                    with transaction.atomic():
                        result = callback(receipt, product, grant)
                except no_effect_exceptions as caught:
                    append_audit(receipt, target_ref=ref, outcome=AuditOutcome.NO_EFFECT)
                    error = caught
            if (
                AuditEvent.objects.filter(
                    workspace_id=workspace.id,
                    policy_decision_ref__resource_id=str(decision.id),
                ).count()
                != 1
            ):
                raise RuntimeError("Feature editor command requires exactly one linked audit")
        finally:
            _ACTIVE.reset(token)
    if error is not None:
        raise error
    return result
