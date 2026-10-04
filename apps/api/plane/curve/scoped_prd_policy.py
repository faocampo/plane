# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Current exact C1 membership and per-human native access; no retained grant."""

from dataclasses import dataclass
from types import SimpleNamespace
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from plane.db.models import User, Workspace, WorkspaceMember
from .config import is_curve_enabled_for_workspace
from .models import GateAssignment, Initiative, Product
from .prd_commands import PrdCommandError
from .scope_proposal_policy import resolve_scope_items
from .scope_proposal_services import selection_for_item
from .scoped_prd_contracts import metadata_digest, validate_scoped_contract, require_contract_integrity
from .scoped_prd_scope import load_locked_scope


@dataclass(frozen=True)
class ScopedCurrent:
    workspace: object
    initiative: object
    product: object
    actor_id: uuid.UUID
    head: object
    revision: object
    members: tuple
    observed_members: tuple
    reviewers: tuple
    fence: tuple


def scoped_enabled(slug):
    return (
        is_curve_enabled_for_workspace(slug)
        and getattr(settings, "CURVE_ENVIRONMENT", None) == "LOCAL"
        and getattr(settings, "CURVE_PRD_COMMANDS_ENABLED", False) is True
        and getattr(settings, "CURVE_SCOPED_PRD_COMMANDS_ENABLED", False) is True
    )


def _require(value, code="SCOPED_PRD_UNAVAILABLE", status=404):
    if not value:
        raise PrdCommandError(code, status)


def scope_pins(context):
    return dict(
        proposal_id=str(context.head.id),
        scope_revision_id=str(context.revision.id),
        scope_revision=context.revision.version,
        membership_digest=context.revision.membership_digest,
    )


def _record_payload(record, name):
    payload = record.as_record()
    validate_scoped_contract(name, payload)
    _require(metadata_digest(payload) == payload["digest"] == record.digest)
    return payload


def require_scoped_current(*, workspace_id, initiative_id, actor_id, observation=None, subject=None):
    """Called under each action's current PRD policy receipt or protected read grant.

    Workspace locking serializes Curve's policy/C1 commands. Native source locks
    are still essential: native edits do not rely on that Curve workspace fence.
    No provider/network call occurs here. All reviewers are checked separately.
    """
    _require(transaction.get_connection().in_atomic_block)
    require_contract_integrity()
    workspace = Workspace.objects.select_for_update().filter(id=workspace_id).first()
    _require(workspace is not None and scoped_enabled(workspace.slug))
    initiative = Initiative.objects.find_by_id(workspace_id=workspace_id, record_id=initiative_id, for_update=True)
    _require(initiative is not None and initiative.mode == "STANDALONE")
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
    if initiative.risk_tier in {"STANDARD", "HIGH"}:
        _require(len({a.approver_user_id for a in assignments}) == 3)
    elif initiative.risk_tier != "LOW":
        _require(False)
    actor_id = uuid.UUID(str(actor_id))
    user_ids = sorted({actor_id, *(a.approver_user_id for a in assignments)})
    users = list(User.objects.select_for_update().filter(id__in=user_ids, is_active=True, is_bot=False).order_by("id"))
    memberships = list(
        WorkspaceMember.objects.select_for_update()
        .filter(workspace_id=workspace_id, member_id__in=user_ids, is_active=True, role__in=[5, 15, 20])
        .order_by("member_id")
    )
    _require(len(users) == len(user_ids) == len(memberships))
    initiative, head, revision, members = load_locked_scope(workspace_id=workspace_id, initiative_id=initiative_id)
    _require(head is not None and revision.item_count > 0)
    try:
        installation = uuid.UUID(str(getattr(settings, "CURVE_LOCAL_PLANE_INSTALLATION_ID", None)))
    except (TypeError, ValueError):
        raise PrdCommandError("SCOPED_PRD_UNAVAILABLE", 404) from None
    members = sorted(members, key=lambda m: str(m.source_issue_id))
    selections = [selection_for_item(member) for member in members]
    fences = []
    observed = None
    for user in users:
        context = SimpleNamespace(
            workspace=workspace, product=product, initiative=initiative, installation_id=installation, user=user
        )
        try:
            fresh, fence = resolve_scope_items(context, selections)
        except Exception:
            raise PrdCommandError("SCOPED_PRD_UNAVAILABLE", 404) from None
        for original, item in zip(members, fresh):
            _require(
                str(original.provider_installation_id) == item["provider_installation_id"]
                and str(original.source_project_id) == item["source_project_id"]
            )
        comparable = tuple({k: v for k, v in item.items() if k != "source_observed_at"} for item in fresh)
        if observed is not None:
            _require(comparable == observed)
        observed = comparable
        fences.append((user.id, fence))
    reviewers = tuple(
        dict(gate_assignment_id=str(a.id), gate_type=a.gate_type, approver_user_id=str(a.approver_user_id))
        for a in assignments
    )
    current = ScopedCurrent(
        workspace,
        initiative,
        product,
        actor_id,
        head,
        revision,
        tuple(members),
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
    if subject is not None:
        from .scoped_prd_models import ScopedPrdObservation, ScopedPrdReadiness

        payload = _record_payload(subject, "Subject")
        _require(
            subject.workspace_id == workspace.id
            and subject.initiative_id == initiative.id
            and subject.product_id == product.id
        )
        observation = ScopedPrdObservation.objects.find_by_id(
            workspace_id=workspace_id, record_id=payload["observation_set_id"], for_update=True
        )
        ready = ScopedPrdReadiness.objects.find_by_id(
            workspace_id=workspace_id, record_id=payload["scoped_readiness_id"], for_update=True
        )
        _require(observation is not None and ready is not None)
        ready_payload = _record_payload(ready, "Readiness")
        _require(
            ready_payload["observation_set_id"] == str(observation.id)
            and ready_payload["observation_digest"] == payload["observation_digest"] == observation.digest
            and ready.digest == payload["scoped_readiness_digest"]
            and ready.workspace_id == workspace.id
            and ready.initiative_id == initiative.id
        )
        for key, value in scope_pins(current).items():
            _require(payload[key] == ready_payload[key] == value, "SCOPED_PRD_SUBJECT_CHANGED", 409)
        expected_members = [
            {k: v for k, v in item.items() if k not in {"source_version", "source_fingerprint"}} for item in observed
        ]
        _require(payload["members"] == expected_members, "SCOPED_PRD_SUBJECT_CHANGED", 409)
    if observation is not None:
        payload = _record_payload(observation, "Observation")
        _require(
            observation.workspace_id == workspace.id
            and observation.initiative_id == initiative.id
            and observation.product_id == product.id
        )
        _require(
            all(payload[key] == value for key, value in scope_pins(current).items())
            and payload["members"] == list(observed)
            and payload["reviewers"] == list(reviewers),
            "SCOPED_PRD_SUBJECT_CHANGED",
            409,
        )
    return current


def revalidate_prd_action(*, receipt, request, workspace_slug, initiative_id, action, runtime):
    """Current local/DB-only ACL resolution after runtime callbacks, no cached ALLOW."""
    from .policy_services import assert_active_mutation_receipt
    from .policy_evaluator import evaluate_core_policy
    from .policy_types import PolicyEffect
    from .prd_policy_context import build_prd_policy_context

    assert_active_mutation_receipt(
        receipt, action=action, workspace_id=receipt.workspace_id, resource_ref=dict(receipt.resource_ref)
    )
    current = build_prd_policy_context(
        request=request,
        workspace_slug=workspace_slug,
        initiative_id=initiative_id,
        action=action,
        acl_resolver=runtime.resolve_acl,
        for_update=True,
    )
    if evaluate_core_policy(current).effect is not PolicyEffect.ALLOW:
        raise PrdCommandError("SCOPED_PRD_UNAVAILABLE", 404)
