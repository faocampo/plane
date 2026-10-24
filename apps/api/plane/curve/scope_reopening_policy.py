# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Current ProductApprover action policy and complete replacement native access."""

from dataclasses import dataclass
from types import SimpleNamespace
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from plane.db.models import User, Workspace, WorkspaceMember
from .models import GateAssignment, Initiative, Product
from .prd_commands import PrdCommandError
from .prd_policy_context import _build_gate_policy_context
from .scope_proposal_policy import resolve_scope_items
from .scope_reopening_contracts import ACTION, POLICY_DIGEST, require_reopening_contract_integrity
from .scope_reopening_qualification import require_reopening_qualification
from .scoped_prd_policy import scoped_enabled
from .scoped_prd_scope import load_locked_scope


@dataclass(frozen=True)
class ReopeningCurrent:
    workspace: object
    initiative: object
    product: object
    head: object
    revision: object
    actor_id: uuid.UUID
    observed_members: tuple
    reviewers: tuple
    fence: tuple


def reopening_enabled(slug):
    return (
        scoped_enabled(slug)
        and getattr(settings, "CURVE_SCOPE_PROPOSALS_ENABLED", False) is True
        and getattr(settings, "CURVE_SCOPE_REOPENING_ENABLED", False) is True
    )


def build_reopening_policy_context(*, request, workspace_slug, initiative_id, acl_resolver):
    require_reopening_contract_integrity()
    context = _build_gate_policy_context(
        request=request,
        workspace_slug=workspace_slug,
        initiative_id=initiative_id,
        action=ACTION,
        acl_resolver=acl_resolver,
        for_update=True,
        supported_actions=frozenset({ACTION}),
        manifest_digest=POLICY_DIGEST,
    )
    context["feature_enabled"] = context["feature_enabled"] and reopening_enabled(workspace_slug)
    return context


def _require(value):
    if not value:
        raise PrdCommandError("SCOPE_REOPENING_UNAVAILABLE", 404)


def require_reopening_current(*, workspace_id, initiative_id, actor_id, selections):
    _require(transaction.get_connection().in_atomic_block)
    require_reopening_qualification()
    workspace = Workspace.objects.select_for_update().filter(id=workspace_id).first()
    _require(workspace is not None and reopening_enabled(workspace.slug))
    initiative = Initiative.objects.find_by_id(workspace_id=workspace_id, record_id=initiative_id, for_update=True)
    _require(
        initiative is not None
        and initiative.mode == "STANDALONE"
        and initiative.schema_version == "1.1"
        and initiative.roadmap_item_id is None
        and initiative.workflow_version_id is not None
        and initiative.first_external_resource_at is None
    )
    assignments = list(
        GateAssignment.objects.select_for_update()
        .filter(workspace_id=workspace_id, initiative_id=initiative_id)
        .order_by("gate_type")
    )
    product = Product.objects.find_by_id(workspace_id=workspace_id, record_id=initiative.product_id, for_update=True)
    _require(product is not None and product.state == "ACTIVE")
    _require(
        len(assignments) == 3
        and {a.gate_type for a in assignments} == {"PRD_APPROVAL", "PLAN_APPROVAL", "CODE_READINESS"}
    )
    now = timezone.now()
    _require(all(a.valid_from <= now and (a.valid_until is None or now < a.valid_until) for a in assignments))
    _require(initiative.risk_tier in {"LOW", "STANDARD", "HIGH"})
    if initiative.risk_tier != "LOW":
        _require(len({a.approver_user_id for a in assignments}) == 3)
    actor_id = uuid.UUID(str(actor_id))
    _require(next(a for a in assignments if a.gate_type == "PRD_APPROVAL").approver_user_id == actor_id)
    user_ids = sorted({actor_id, *(a.approver_user_id for a in assignments)})
    users = list(User.objects.select_for_update().filter(id__in=user_ids, is_active=True, is_bot=False).order_by("id"))
    memberships = list(
        WorkspaceMember.objects.select_for_update()
        .filter(workspace_id=workspace_id, member_id__in=user_ids, is_active=True, role__in=[5, 15, 20])
        .order_by("member_id")
    )
    _require(len(users) == len(user_ids) == len(memberships))
    initiative, head, revision, _ = load_locked_scope(workspace_id=workspace_id, initiative_id=initiative_id)
    _require(head is not None)
    try:
        installation = uuid.UUID(str(getattr(settings, "CURVE_LOCAL_PLANE_INSTALLATION_ID", None)))
    except (TypeError, ValueError):
        raise PrdCommandError("SCOPE_REOPENING_UNAVAILABLE", 404) from None
    observed, fences = None, []
    for user in users:
        native = SimpleNamespace(
            workspace=workspace, product=product, initiative=initiative, installation_id=installation, user=user
        )
        try:
            fresh, fence = resolve_scope_items(native, selections)
        except Exception:
            raise PrdCommandError("SCOPE_REOPENING_UNAVAILABLE", 404) from None
        comparable = tuple({k: v for k, v in item.items() if k != "source_observed_at"} for item in fresh)
        _require(
            observed is None
            or comparable == tuple({k: v for k, v in item.items() if k != "source_observed_at"} for item in observed)
        )
        if observed is None:
            observed = tuple(fresh)
        fences.append((user.id, fence))
    reviewers = tuple(
        dict(gate_assignment_id=str(a.id), gate_type=a.gate_type, approver_user_id=str(a.approver_user_id))
        for a in assignments
    )
    return ReopeningCurrent(
        workspace,
        initiative,
        product,
        head,
        revision,
        actor_id,
        observed,
        reviewers,
        (
            product.id,
            product.version,
            product.state,
            initiative.risk_tier,
            tuple((a.id, a.approver_user_id, a.valid_from, a.valid_until) for a in assignments),
            tuple((m.id, m.member_id, m.role, m.is_active) for m in memberships),
            tuple(fences),
        ),
    )


class ReopeningAuthorityDenied(PrdCommandError):
    """Final authority loss rolls back the provisional ALLOW and every effect."""

    def __init__(self):
        super().__init__("SCOPE_REOPENING_UNAVAILABLE", 404)


def revalidate_reopening_authority(*, context_builder, current_resolver, expected):
    from .policy_evaluator import evaluate_core_policy
    from .policy_types import PolicyEffect

    try:
        if evaluate_core_policy(context_builder()).effect is not PolicyEffect.ALLOW:
            raise ValueError
        fresh = current_resolver()
        if fresh.fence != expected.fence:
            raise ValueError
        return fresh
    except Exception:
        raise ReopeningAuthorityDenied from None


def execute_reopening_action(
    *, context_builder, current_resolver, mutation_callback, request_digest, no_effect_exceptions
):
    """Native subject authorization participates in the durable policy decision.

    A final source/authority denial erases the provisional ALLOW and its effects,
    then records a distinct immutable DENY; historical decisions are never edited.
    """
    from dataclasses import replace
    from .policy_evaluator import evaluate_core_policy
    from .policy_types import PolicyEffect
    from .policy_services import (
        _record_policy_decision,
        _new_authorized_receipt,
        _ACTIVE_MUTATION_RECEIPT,
        _append_policy_audit,
        _assert_one_mutation_audit,
        CurvePolicyDenied,
    )
    from .scope_proposal_policy import _fence_digest
    from .scope_reopening_contracts import digest

    pending, value = None, None
    with transaction.atomic():
        context = context_builder()
        evaluated = evaluate_core_policy(context)
        current = None
        if evaluated.effect is PolicyEffect.ALLOW:
            try:
                current = current_resolver()
            except PrdCommandError as error:
                pending = error
                evaluated = replace(
                    evaluated, effect=PolicyEffect.DENY, reason_codes=("RESOURCE_NOT_FOUND",), permitted_projection=()
                )
        normalized = dict(
            policy_context=context,
            request_digest=request_digest,
            trusted_installation_id=str(getattr(settings, "CURVE_LOCAL_PLANE_INSTALLATION_ID", None)),
            replacement_authority_fence_digest=_fence_digest(current.fence) if current else None,
            prior_revision_id=str(current.revision.id) if current else None,
            failure_stage="SUBJECT_AUTHORIZATION" if pending else None,
        )
        evaluated = replace(evaluated, input_digest=digest(normalized))
        if evaluated.effect is not PolicyEffect.ALLOW:
            decision = _record_policy_decision(context=context, result=evaluated)
            _append_policy_audit(context=context, result=evaluated, decision=decision)
            pending = pending or CurvePolicyDenied(reason_codes=evaluated.reason_codes, decision_id=decision.id)
        else:
            try:
                with transaction.atomic():
                    decision = _record_policy_decision(context=context, result=evaluated)
                    receipt = _new_authorized_receipt(decision=decision, result=evaluated, context=context)
                    token = _ACTIVE_MUTATION_RECEIPT.set(receipt)
                    try:
                        try:
                            value = mutation_callback(receipt, current)
                        except ReopeningAuthorityDenied:
                            raise
                        except no_effect_exceptions as error:
                            pending = error
                    finally:
                        _ACTIVE_MUTATION_RECEIPT.reset(token)
                    _assert_one_mutation_audit(decision.id)
            except ReopeningAuthorityDenied as error:
                normalized["failure_stage"] = "COMMIT_FENCE"
                denied = replace(
                    evaluated,
                    effect=PolicyEffect.DENY,
                    reason_codes=("RESOURCE_NOT_FOUND",),
                    permitted_projection=(),
                    input_digest=digest(normalized),
                )
                decision = _record_policy_decision(context=context, result=denied)
                _append_policy_audit(context=context, result=denied, decision=decision)
                pending = error
        _assert_one_mutation_audit(decision.id)
    if pending is not None:
        raise pending
    return value
