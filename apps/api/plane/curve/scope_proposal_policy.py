# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Independent C1 authority. Native issue visibility is evaluated per explicit ID."""

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from plane.db.models import Issue, Project, ProjectMember, State, User, Workspace, WorkspaceMember
from .config import curve_policy_recorder, is_curve_enabled_for_workspace
from .models import AuditEvent, AuditOutcome, Initiative, PolicyDecision, Product, ProjectAssociation
from .policy_services import CurvePolicyResourceNotFound, correlation_id_for_request, _next_policy_sequence
from .scope_proposal_models import ScopeProposal, ScopeProposalRevision, ScopeProposalItem
from .services import _append_audit_event, canonical_json_bytes, sha256_digest, OptimisticConcurrencyError

POLICY_KEY = "CURVE_SCOPE_PROPOSAL_POLICY"
POLICY_DIGEST = "sha256:778bdbd6fb82f51482d791d22ae6cf884a8906e91613b07cdafc6b429d24e266"
REPLACE = "CURVE.SCOPE_PROPOSAL.REPLACE"
READ = "CURVE.SCOPE_PROPOSAL.READ"
_ACTIVE = ContextVar("curve_scope_proposal_receipt", default=None)


@dataclass
class ScopeReceipt:
    decision_id: uuid.UUID
    action: str
    workspace_id: uuid.UUID
    actor: dict
    correlation_id: str
    resource_ref: dict
    context: object
    revision_id: uuid.UUID | None = None
    proposal_id: uuid.UUID | None = None
    source_fences: list = field(default_factory=list)
    authorized_items: dict = field(default_factory=dict)
    final_initiative_version: int | None = None


@dataclass(frozen=True)
class ScopeContext:
    workspace: Workspace
    user: User
    membership: WorkspaceMember
    initiative: Initiative
    product: Product
    installation_id: uuid.UUID
    head: ScopeProposal | None
    authority_fence: tuple


def enabled(slug):
    return (
        is_curve_enabled_for_workspace(slug)
        and getattr(settings, "CURVE_SCOPE_PROPOSALS_ENABLED", False) is True
        and getattr(settings, "CURVE_ENVIRONMENT", "") == "LOCAL"
    )


def _installation():
    try:
        return uuid.UUID(str(getattr(settings, "CURVE_LOCAL_PLANE_INSTALLATION_ID", None)))
    except (TypeError, ValueError):
        raise CurvePolicyResourceNotFound from None


def _policy_integrity():
    raw = (Path(__file__).parent / "scope_proposal_candidate" / "policy-v1.json").read_bytes()
    if sha256_digest(raw) != POLICY_DIGEST:
        raise CurvePolicyResourceNotFound


def load_scope_context(*, request, workspace_slug, initiative_id, action):
    if not enabled(workspace_slug) or not getattr(request.user, "is_authenticated", False):
        raise CurvePolicyResourceNotFound
    installation = _installation()
    workspace = Workspace.objects.select_for_update().filter(slug=workspace_slug).first()
    if workspace is None:
        raise CurvePolicyResourceNotFound
    user = User.objects.select_for_update().filter(id=request.user.id, is_active=True, is_bot=False).first()
    membership = (
        WorkspaceMember.objects.select_for_update()
        .filter(workspace_id=workspace.id, member_id=request.user.id, is_active=True, role__in=[5, 15, 20])
        .first()
    )
    if user is None or membership is None:
        return workspace, None
    initiative = Initiative.objects.find_by_id(workspace_id=workspace.id, record_id=initiative_id, for_update=True)
    if initiative is None or initiative.mode != "STANDALONE":
        return workspace, None
    if action not in {READ, REPLACE} or (
        action == REPLACE and membership.role != 20 and initiative.creator_user_id != user.id
    ):
        return workspace, None
    product = Product.objects.find_by_id(workspace_id=workspace.id, record_id=initiative.product_id, for_update=True)
    if product is None:
        return workspace, None
    head = (
        ScopeProposal.objects.select_for_update().filter(workspace_id=workspace.id, initiative_id=initiative.id).first()
    )
    fence = (
        workspace.id,
        workspace.owner_id,
        user.id,
        user.is_active,
        user.is_bot,
        membership.id,
        membership.role,
        membership.is_active,
        membership.updated_at,
        initiative.id,
        initiative.product_id,
        initiative.mode,
        initiative.state,
        initiative.creator_user_id,
        product.id,
        product.state,
        product.version,
        product.owner_user_id,
        installation,
    )
    return workspace, ScopeContext(workspace, user, membership, initiative, product, installation, head, fence)


def _fingerprint(issue, state):
    # Identity/lifecycle coordinates only. C1 does not inspect or attest task
    # bodies; any content-sensitive review proof belongs to a later C2 edition.
    coordinates = {
        key: str(getattr(issue, key)) if getattr(issue, key) is not None else None
        for key in (
            "id",
            "workspace_id",
            "project_id",
            "parent_id",
            "state_id",
            "created_by_id",
            "archived_at",
            "deleted_at",
            "is_draft",
            "updated_at",
        )
    }
    coordinates.update(state_group=state.group, state_updated_at=state.updated_at.isoformat())
    return sha256_digest(canonical_json_bytes(coordinates))


def resolve_scope_items(context, selections, *, check_versions=True):
    """Fresh locked native ordinary-Issue visibility, never project access alone.

    The same predicate applies to explicitly selected children; no parent walk or
    descendant query occurs. Native public/external surfaces confer no grant.
    """
    association_ids = sorted({item["association_id"] for item in selections})
    associations = list(
        ProjectAssociation.objects.select_for_update()
        .filter(
            workspace_id=context.workspace.id,
            id__in=association_ids,
            provider_installation_id=context.installation_id,
            product_id=context.product.id,
            state="ACTIVE",
        )
        .order_by("id")
    )
    if len(associations) != len(association_ids):
        raise CurvePolicyResourceNotFound
    by_assoc = {str(item.id): item for item in associations}
    project_ids = sorted({item.source_project_id for item in associations})
    projects = list(
        Project.objects.select_for_update()
        .filter(id__in=project_ids, workspace_id=context.workspace.id, archived_at__isnull=True)
        .only("id", "workspace_id", "archived_at", "updated_at", "network", "guest_view_all_features")
        .order_by("id")
    )
    memberships = list(
        ProjectMember.objects.select_for_update()
        .filter(
            workspace_id=context.workspace.id,
            project_id__in=project_ids,
            member_id=context.user.id,
            is_active=True,
            role__in=[5, 15, 20],
        )
        .order_by("project_id", "id")
    )
    if len(projects) != len(project_ids) or len(memberships) != len(project_ids):
        raise CurvePolicyResourceNotFound
    by_project = {item.id: item for item in projects}
    by_member = {item.project_id: item for item in memberships}
    # Lock Issues first, then States deterministically; the subsequent selector
    # repeats native manager/state predicates after both sets are fenced.
    ids = [item["source_issue_id"] for item in selections]
    issues = list(
        Issue.issue_objects.select_for_update(of=("self",))
        .filter(
            id__in=ids,
            workspace_id=context.workspace.id,
            project_id__in=project_ids,
            project__deleted_at__isnull=True,
            state__deleted_at__isnull=True,
        )
        .only(
            "id",
            "workspace_id",
            "project_id",
            "parent_id",
            "state_id",
            "created_by_id",
            "archived_at",
            "deleted_at",
            "is_draft",
            "updated_at",
        )
        .order_by("id")
    )
    if len(issues) != len(ids):
        raise CurvePolicyResourceNotFound
    states = list(
        State.objects.select_for_update()
        .filter(id__in={item.state_id for item in issues}, workspace_id=context.workspace.id)
        .only("id", "workspace_id", "project_id", "group", "updated_at", "deleted_at")
        .order_by("id")
    )
    by_state = {item.id: item for item in states}
    by_issue = {str(item.id): item for item in issues}
    observed_at = timezone.now()
    observations, fence = [], []
    for selection in selections:
        association = by_assoc.get(selection["association_id"])
        issue = by_issue.get(selection["source_issue_id"])
        if association is None or issue is None:
            raise CurvePolicyResourceNotFound
        project, membership = by_project[association.source_project_id], by_member[association.source_project_id]
        state = by_state.get(issue.state_id)
        if (
            issue.project_id != project.id
            or state is None
            or state.project_id != project.id
            or state.group == "triage"
            or (membership.role == 5 and not project.guest_view_all_features and issue.created_by_id != context.user.id)
        ):
            raise CurvePolicyResourceNotFound
        if check_versions and association.version != selection["association_version"]:
            raise OptimisticConcurrencyError
        fingerprint = _fingerprint(issue, state)
        observations.append(
            dict(
                selection,
                provider_installation_id=str(context.installation_id),
                source_project_id=str(project.id),
                source_observed_at=observed_at,
                source_version=issue.updated_at.isoformat(),
                source_fingerprint=fingerprint,
            )
        )
        fence.append(
            (
                association.id,
                association.version,
                association.state,
                association.product_id,
                association.provider_installation_id,
                association.source_project_id,
                project.id,
                project.network,
                project.guest_view_all_features,
                project.updated_at,
                membership.id,
                membership.role,
                membership.is_active,
                membership.updated_at,
                state.id,
                state.group,
                state.updated_at,
                fingerprint,
            )
        )
    return observations, tuple(fence)


def authorize_scope_items(receipt, context, selections):
    if _ACTIVE.get() is not receipt:
        raise PermissionError("Active scope receipt required")
    observations, fence = resolve_scope_items(context, selections)
    receipt.source_fences.append((selections, fence))
    return observations


def append_scope_audit(receipt, *, target_ref, outcome, key_digest=None, after_digest=None):
    if _ACTIVE.get() is not receipt or not transaction.get_connection().in_atomic_block:
        raise PermissionError("An active scope authorization receipt is required")
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


def _fence_digest(fence):
    def wire(value):
        if isinstance(value, (tuple, list)):
            return [wire(item) for item in value]
        if isinstance(value, uuid.UUID):
            return str(value)
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value

    return sha256_digest(canonical_json_bytes(wire(fence)))


def _record_scope_decision(
    *,
    workspace,
    context,
    request,
    action,
    ref,
    actor,
    subject,
    allowed,
    source_fence,
    resolved_revision_id,
    failure_stage=None,
):
    now = timezone.now()
    reasons = ["ALLOW"] if allowed else ["RESOURCE_NOT_FOUND"]
    normalized = {
        "action": action,
        "actor": actor,
        "subject": subject,
        "resource_ref": ref,
        "trusted_provider_installation_id": str(_installation()),
        "authority_fence_digest": _fence_digest(context.authority_fence) if context else None,
        "source_fence_digest": _fence_digest(source_fence),
        "resolved_revision_id": str(resolved_revision_id) if resolved_revision_id else None,
        "reason_codes": reasons,
        "failure_stage": failure_stage,
    }
    return PolicyDecision.objects.create(
        workspace_id=workspace.id,
        sequence=_next_policy_sequence(
            workspace_id=workspace.id, resource_type="INITIATIVE", resource_id=ref["resource_id"]
        ),
        action=action,
        resource_type="INITIATIVE",
        resource_id=ref["resource_id"],
        resource_version=ref.get("resource_version"),
        subject=actor,
        effective_principal=actor,
        effect="ALLOW" if allowed else "DENY",
        reason_codes=reasons,
        policy_key=POLICY_KEY,
        policy_version=1,
        policy_manifest_digest=POLICY_DIGEST,
        input_digest=sha256_digest(canonical_json_bytes(normalized)),
        normalized_classification="INTERNAL",
        permitted_projection=["SCOPE_PROPOSAL_SAFE_IDENTITY"] if allowed else [],
        correlation_id=correlation_id_for_request(request),
        evaluated_at=now,
        recorded_at=now,
        recorded_by=curve_policy_recorder(),
    )


def execute_scope_action(
    *, request, workspace_slug, initiative_id, action, subject, callback, resolve_subject, no_effect_exceptions=()
):
    """Record a final decision only after exact native subject authorization.

    The ALLOW decision and callback share a savepoint. If the final source or
    authority fence is lost, neither that decision nor its effects survive;
    a new immutable DENY is recorded with exactly one linked DENIED audit.
    """
    _policy_integrity()
    pending, result = None, None
    args = dict(request=request, workspace_slug=workspace_slug, initiative_id=initiative_id, action=action)
    with transaction.atomic():
        workspace, context = load_scope_context(**args)
        ref = {"resource_type": "INITIATIVE", "resource_id": str(initiative_id)}
        if context is not None:
            ref["resource_version"] = context.initiative.version
        actor = {"actor_type": "HUMAN", "actor_id": str(request.user.id)}
        selections, source_fence, resolved_revision_id = [], (), None
        allowed = context is not None
        if allowed:
            try:
                selections, resolved_revision_id = resolve_subject(context)
                # Version mismatch is a business precondition, not source denial.
                # Resolve all items first so a stale pin cannot mask inaccessible ones.
                _, source_fence = resolve_scope_items(context, selections, check_versions=False)
            except CurvePolicyResourceNotFound:
                allowed = False
        decision_args = dict(
            workspace=workspace,
            context=context,
            request=request,
            action=action,
            ref=ref,
            actor=actor,
            subject=subject,
            source_fence=source_fence,
            resolved_revision_id=resolved_revision_id,
        )

        def record(allow, failure_stage=None):
            decision = _record_scope_decision(**decision_args, allowed=allow, failure_stage=failure_stage)
            receipt = ScopeReceipt(decision.id, action, workspace.id, actor, decision.correlation_id, ref, context)
            receipt.source_fences.append((selections, source_fence))
            return decision, receipt

        try:
            with transaction.atomic():
                decision, receipt = record(allowed, None if allowed else "SUBJECT_AUTHORIZATION")
                token = _ACTIVE.set(receipt)
                try:
                    if not allowed:
                        append_scope_audit(receipt, target_ref=ref, outcome=AuditOutcome.DENIED)
                        pending = CurvePolicyResourceNotFound()
                    else:
                        try:
                            with transaction.atomic():
                                result = callback(receipt, context)
                                _, fresh = load_scope_context(**args)
                                if fresh is None or fresh.authority_fence != context.authority_fence:
                                    raise CurvePolicyResourceNotFound
                                if receipt.revision_id is not None and (
                                    fresh.head is None
                                    or fresh.head.id != receipt.proposal_id
                                    or fresh.head.current_revision_id != receipt.revision_id
                                    or fresh.initiative.version != receipt.final_initiative_version
                                ):
                                    raise CurvePolicyResourceNotFound
                                for selected, fence in receipt.source_fences:
                                    _, current_fence = resolve_scope_items(fresh, selected, check_versions=False)
                                    if current_fence != fence:
                                        raise CurvePolicyResourceNotFound
                        except no_effect_exceptions as error:
                            append_scope_audit(receipt, target_ref=ref, outcome=AuditOutcome.NO_EFFECT)
                            pending = error
                finally:
                    _ACTIVE.reset(token)
        except CurvePolicyResourceNotFound as error:
            # The savepoint erased the provisional ALLOW and all domain effects.
            decision, receipt = record(False, "COMMIT_FENCE")
            token = _ACTIVE.set(receipt)
            try:
                append_scope_audit(receipt, target_ref=ref, outcome=AuditOutcome.DENIED)
            finally:
                _ACTIVE.reset(token)
            pending = error
        if (
            AuditEvent.objects.filter(
                workspace_id=workspace.id, policy_decision_ref__resource_id=str(decision.id)
            ).count()
            != 1
        ):
            raise RuntimeError("Scope action must append exactly one linked audit")
    if pending is not None:
        raise pending
    return result


def assert_scope_write(record):
    receipt = _ACTIVE.get()
    if (
        receipt is None
        or receipt.context is None
        or receipt.action != REPLACE
        or receipt.revision_id is None
        or receipt.proposal_id is None
        or not transaction.get_connection().in_atomic_block
    ):
        raise PermissionError("An active exact-subject scope command receipt is required")
    context = receipt.context
    if record.workspace_id != context.workspace.id:
        raise PermissionError("Scope receipt does not authorize this workspace")
    if isinstance(record, ScopeProposalItem):
        from .scope_proposal_serialization import serialize_scope_item

        if record.revision_id != receipt.revision_id or receipt.authorized_items.get(
            str(record.source_issue_id)
        ) != serialize_scope_item(record):
            raise PermissionError("Scope receipt does not authorize this revision")
    elif isinstance(record, (ScopeProposal, ScopeProposalRevision)):
        if record.initiative_id != context.initiative.id or record.product_id != context.product.id:
            raise PermissionError("Scope receipt does not authorize this Initiative")
        if isinstance(record, ScopeProposal):
            valid = record.id == receipt.proposal_id and record.current_revision_id == receipt.revision_id
        else:
            valid = (
                record.id == receipt.revision_id
                and record.proposal_id == receipt.proposal_id
                and record.created_by == context.user.id
            )
        if not valid:
            raise PermissionError("Scope receipt does not authorize this exact subject")
    else:
        raise PermissionError("Unsupported scope record")
