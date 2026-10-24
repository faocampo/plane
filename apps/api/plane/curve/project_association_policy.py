# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Independent local candidate policy, never a provider-registration grant."""

import hashlib
import json
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .config import curve_policy_recorder, is_curve_enabled_for_workspace
from .models import AuditEvent, AuditOutcome, PolicyDecision, Product, ProjectAssociation
from .policy_services import CurvePolicyResourceNotFound, correlation_id_for_request
from .services import _append_audit_event, canonical_json_bytes, sha256_digest
from plane.db.models import Project, ProjectMember, User, Workspace, WorkspaceMember


POLICY_KEY = "CURVE_PROJECT_ASSOCIATION_POLICY"
POLICY_DIGEST = "sha256:0ea402f3db6a7fb0743a79a45644d79235a685781ad844d3c42230da2c548691"
ASSOCIATE = "CURVE.PROJECT_ASSOCIATION.ASSOCIATE"
END = "CURVE.PROJECT_ASSOCIATION.END"
READ = "CURVE.PROJECT_ASSOCIATION.READ"
_ACTIVE_RECEIPT = ContextVar("curve_project_association_receipt", default=None)


@dataclass(frozen=True)
class AssociationContext:
    workspace: Workspace
    user: User
    membership: WorkspaceMember
    project_membership: ProjectMember
    project: Project
    product: Product
    installation_id: uuid.UUID
    association: ProjectAssociation | None

    def fence(self):
        return (
            self.workspace.id,
            self.user.id,
            self.user.is_active,
            self.user.is_bot,
            self.membership.id,
            self.membership.role,
            self.membership.is_active,
            self.project_membership.id,
            self.project_membership.role,
            self.project_membership.is_active,
            self.project.id,
            self.project.workspace_id,
            self.project.archived_at,
            self.project.updated_at,
            self.product.id,
            self.product.workspace_id,
            self.product.owner_user_id,
            self.product.state,
            self.product.version,
            self.installation_id,
        )


@dataclass(frozen=True)
class AssociationReceipt:
    decision_id: uuid.UUID
    action: str
    workspace_id: uuid.UUID
    actor: dict
    correlation_id: str
    resource_ref: dict
    context: AssociationContext | None


def enabled(workspace_slug):
    return (
        is_curve_enabled_for_workspace(workspace_slug)
        and getattr(settings, "CURVE_PROJECT_ASSOCIATIONS_ENABLED", False) is True
        and getattr(settings, "CURVE_ENVIRONMENT", "") == "LOCAL"
    )


def _installation():
    try:
        return uuid.UUID(str(getattr(settings, "CURVE_LOCAL_PLANE_INSTALLATION_ID", None)))
    except (TypeError, ValueError) as error:
        raise CurvePolicyResourceNotFound from error


def _policy_integrity():
    raw = (Path(__file__).parent / "project_association_candidate" / "policy-v1.json").read_bytes()
    if f"sha256:{hashlib.sha256(raw).hexdigest()}" != POLICY_DIGEST:
        raise CurvePolicyResourceNotFound
    return json.loads(raw)


def _load_context(
    *,
    request,
    workspace_slug,
    product_id=None,
    source_project_id=None,
    provider_installation_id=None,
    association_id=None,
    action,
):
    # The caller's role flags, provider capabilities, successful earlier reads,
    # request auth metadata, and cached user.is_active are never authority.
    if not enabled(workspace_slug) or not getattr(request.user, "is_authenticated", False):
        raise CurvePolicyResourceNotFound
    installation_id = _installation()
    workspace = Workspace.objects.select_for_update().filter(slug=workspace_slug).first()
    if workspace is None:
        raise CurvePolicyResourceNotFound
    user = User.objects.select_for_update().filter(id=request.user.id, is_active=True, is_bot=False).first()
    membership = (
        WorkspaceMember.objects.select_for_update()
        .filter(
            workspace_id=workspace.id,
            member_id=request.user.id,
            is_active=True,
        )
        .first()
    )
    if user is None or membership is None:
        return workspace, None, ("RESOURCE_NOT_FOUND",)
    if action not in {ASSOCIATE, END, READ}:
        return workspace, None, ("UNKNOWN_ACTION",)
    if action != READ and membership.role != 20:
        return workspace, None, ("WORKSPACE_ADMINISTRATOR_REQUIRED",)
    association = None
    if association_id is not None:
        association = ProjectAssociation.objects.find_by_id(
            workspace_id=workspace.id,
            record_id=association_id,
            for_update=True,
        )
        if association is None or association.provider_installation_id != installation_id:
            return workspace, None, ("RESOURCE_NOT_FOUND",)
        product_id, source_project_id = association.product_id, association.source_project_id
    elif provider_installation_id != installation_id:
        return workspace, None, ("RESOURCE_NOT_FOUND",)
    product = Product.objects.find_by_id(workspace_id=workspace.id, record_id=product_id, for_update=True)
    project = Project.objects.select_for_update().filter(id=source_project_id, workspace_id=workspace.id).first()
    project_membership = (
        ProjectMember.objects.select_for_update()
        .filter(
            workspace_id=workspace.id,
            project_id=source_project_id,
            member_id=user.id,
            is_active=True,
        )
        .first()
    )
    if product is None or project is None or project_membership is None:
        return workspace, None, ("RESOURCE_NOT_FOUND",)
    # Product metadata authority is explicit even though the stricter command
    # administrator condition above currently implies it.
    if action != READ and not (membership.role == 20 or product.owner_user_id == user.id):
        return workspace, None, ("PRODUCT_AUTHORITY_REQUIRED",)
    return (
        workspace,
        AssociationContext(
            workspace,
            user,
            membership,
            project_membership,
            project,
            product,
            installation_id,
            association,
        ),
        ("ALLOW",),
    )


def _record_decision(*, workspace, action, resource_ref, actor, correlation_id, reasons, subject):
    from .policy_services import _next_policy_sequence

    now = timezone.now()
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
        effect="ALLOW" if reasons == ("ALLOW",) else "DENY",
        reason_codes=list(reasons),
        policy_key=POLICY_KEY,
        policy_version=1,
        policy_manifest_digest=POLICY_DIGEST,
        input_digest=sha256_digest(
            canonical_json_bytes(
                {
                    "action": action,
                    "actor": actor,
                    "workspace_id": str(workspace.id),
                    "subject": subject,
                    "resource_ref": resource_ref,
                    "reason_codes": reasons,
                }
            )
        ),
        normalized_classification="INTERNAL",
        permitted_projection=["PROJECT_ASSOCIATION_SAFE_IDENTITY"] if reasons == ("ALLOW",) else [],
        correlation_id=correlation_id,
        evaluated_at=now,
        recorded_at=now,
        recorded_by=curve_policy_recorder(),
    )


def append_association_audit(receipt, *, target_ref, outcome, key_digest=None, after_digest=None):
    if _ACTIVE_RECEIPT.get() is not receipt or not transaction.get_connection().in_atomic_block:
        raise PermissionError("Active association authorization receipt required")
    return _append_audit_event(
        workspace_id=receipt.workspace_id,
        action=receipt.action,
        target_ref=target_ref,
        outcome=outcome,
        actor=receipt.actor,
        effective_principal=receipt.actor,
        correlation_id=receipt.correlation_id,
        key_digest=key_digest,
        after_digest=after_digest,
        policy_decision_ref={
            "resource_type": "POLICY_DECISION",
            "resource_id": str(receipt.decision_id),
            "resource_version": 1,
        },
    )


def execute_association_action(
    *,
    request,
    workspace_slug,
    action,
    callback,
    command_subject,
    product_id=None,
    source_project_id=None,
    provider_installation_id=None,
    association_id=None,
    no_effect_exceptions=(),
):
    """Lock trusted authority, run atomically, recheck, enforce one linked audit.

    Source/member updates by another transaction block on these same row locks.
    The final reread also rejects same-transaction permission changes. A callback
    failure rolls back its aggregate/event/outbox/idempotency/audit effects while
    retaining one safe NO_EFFECT audit of the policy decision.
    """
    _policy_integrity()
    args = dict(
        request=request,
        workspace_slug=workspace_slug,
        action=action,
        product_id=product_id,
        source_project_id=source_project_id,
        provider_installation_id=provider_installation_id,
        association_id=association_id,
    )
    pending_error = None
    result = None
    with transaction.atomic():
        workspace, context, reasons = _load_context(**args)
        ref = {"resource_type": "WORKSPACE", "resource_id": str(workspace.id), "resource_version": 1}
        if context is not None:
            ref = (
                {
                    "resource_type": "PROJECT_ASSOCIATION",
                    "resource_id": str(context.association.id),
                    "resource_version": context.association.version,
                }
                if context.association
                else {
                    "resource_type": "PRODUCT",
                    "resource_id": str(context.product.id),
                    "resource_version": context.product.version,
                }
            )
        actor = {"actor_type": "HUMAN", "actor_id": str(request.user.id)}
        subject = dict(command_subject)
        subject["trusted_provider_installation_id"] = str(_installation())
        if context:
            subject.update(
                product_id=str(context.product.id),
                source_project_id=str(context.project.id),
                product_version=context.product.version,
            )
        decision = _record_decision(
            workspace=workspace,
            action=action,
            resource_ref=ref,
            actor=actor,
            correlation_id=correlation_id_for_request(request),
            reasons=reasons,
            subject=subject,
        )
        receipt = AssociationReceipt(decision.id, action, workspace.id, actor, decision.correlation_id, ref, context)
        token = _ACTIVE_RECEIPT.set(receipt)
        try:
            if reasons != ("ALLOW",):
                append_association_audit(receipt, target_ref=ref, outcome=AuditOutcome.DENIED)
                pending_error = CurvePolicyResourceNotFound()
            else:
                fence = context.fence()
                try:
                    with transaction.atomic():
                        result = callback(receipt, context)
                        _, fresh, fresh_reasons = _load_context(**args)
                        if fresh_reasons != ("ALLOW",) or fresh is None or fresh.fence() != fence:
                            raise CurvePolicyResourceNotFound
                except (*no_effect_exceptions, CurvePolicyResourceNotFound) as error:
                    append_association_audit(receipt, target_ref=ref, outcome=AuditOutcome.NO_EFFECT)
                    pending_error = error
            linked = AuditEvent.objects.filter(
                workspace_id=workspace.id,
                policy_decision_ref__resource_type="POLICY_DECISION",
                policy_decision_ref__resource_id=str(decision.id),
                policy_decision_ref__resource_version=1,
            ).count()
            if linked != 1:
                raise RuntimeError("Association action must append exactly one linked audit")
        finally:
            _ACTIVE_RECEIPT.reset(token)
    if pending_error is not None:
        raise pending_error
    return result


def assert_association_write(association, *, creating):
    receipt = _ACTIVE_RECEIPT.get()
    if (
        receipt is None
        or receipt.context is None
        or not transaction.get_connection().in_atomic_block
        or receipt.action != (ASSOCIATE if creating else END)
    ):
        raise PermissionError("An active exact-subject association command receipt is required")
    context = receipt.context
    if (
        association.workspace_id != context.workspace.id
        or association.provider_installation_id != context.installation_id
        or association.source_project_id != context.project.id
        or association.product_id != context.product.id
        or (creating and association.initiated_by != context.user.id)
        or (not creating and association.ended_by != context.user.id)
        or (not creating and (context.association is None or association.id != context.association.id))
    ):
        raise PermissionError("Association command receipt does not authorize this exact subject")
