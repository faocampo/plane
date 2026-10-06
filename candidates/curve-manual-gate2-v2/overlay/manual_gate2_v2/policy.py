"""Fresh human/material/native authority for exact review and reconciled release."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import SimpleNamespace
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from plane.curve.manual_plan_v2 import policy as draft_policy
from plane.curve.manual_plan_v2.synthetic import SyntheticManualPlanResolverV2
from plane.curve.manual_plan_v2.validation import (
    canonical_json,
    digest,
    parse_strict_json,
)
from .contracts import Gate2Error, POLICY_KEY, policy_digest, require, validate

_ACTIVE = ContextVar("manual_gate2_receipt", default=None)
_TOKEN = object()


@dataclass(frozen=True)
class Authority:
    context: object
    captured: object
    subject: object
    principals: tuple
    task_observations: tuple
    task_groups: dict
    fence: str
    file_fence: tuple


@dataclass(frozen=True)
class Receipt:
    workspace_id: uuid.UUID
    initiative_id: uuid.UUID
    actor_id: uuid.UUID
    action: str
    decision_id: uuid.UUID
    request_digest: str
    correlation_id: str
    token: object


def require_enabled(request, slug):
    draft_policy.require_enabled(request, slug)
    require(getattr(settings, "CURVE_MANUAL_GATE2_V2_ENABLED", False) is True)


def require_edition():
    try:
        from plane.curve.scope_reopening_qualification import (
            require_manual_gate2_v2_qualification,
        )

        require_manual_gate2_v2_qualification()
    except Exception:
        raise Gate2Error("EDITION_UNAVAILABLE", 503) from None


def principals_for(identity, actor_id, reviewers=()):
    return tuple(
        sorted(
            {
                str(actor_id),
                *identity["human_owner_ids"],
                *(g["approver_user_id"] for g in identity["gate_assignments"]),
                *(g["approver_user_id"] for g in reviewers),
            }
        )
    )


def _require_people(workspace_id, principals, *, lock):
    from plane.db.models import User, WorkspaceMember

    users = User.objects.filter(id__in=principals, is_active=True, is_bot=False).order_by("id")
    members = WorkspaceMember.objects.filter(
        workspace_id=workspace_id,
        member_id__in=principals,
        is_active=True,
        role__in=[5, 15, 20],
    ).order_by("member_id")
    if lock:
        users, members = users.select_for_update(), members.select_for_update()
    users, members = list(users), list(members)
    require(len(users) == len(members) == len(principals))
    return users, tuple((u.id, u.is_active, u.is_bot, u.updated_at) for u in users) + tuple(
        (m.id, m.member_id, m.role, m.is_active, m.updated_at) for m in members
    )


def preflight(*, request, slug, revision, resolver):
    require(not transaction.get_connection().in_atomic_block, "EDITION_UNAVAILABLE", 503)
    require_enabled(request, slug)
    from plane.db.models import Workspace

    workspace = Workspace.objects.filter(slug=slug, id=revision.workspace_id).first()
    require(workspace is not None)
    _require_people(workspace.id, [str(request.user.id)], lock=False)
    initial = resolver.capture(
        workspace_id=workspace.id,
        initiative_id=revision.initiative_id,
        definition_ref=revision.payload["definition_ref"],
        principals=[request.user.id],
        action="READ_REVISION",
    )
    principals = principals_for(initial.identity, request.user.id)
    _require_people(workspace.id, principals, lock=False)
    captured = resolver.capture(
        workspace_id=workspace.id,
        initiative_id=revision.initiative_id,
        definition_ref=revision.payload["definition_ref"],
        principals=principals,
        action="READ_REVISION",
    )
    require(captured.identity == initial.identity == revision.original_input_identity)
    require(captured.file_fence == initial.file_fence)
    return captured


def _fence_json(value):
    if type(value) is int and abs(value) > 9007199254740991:
        return {"integer_decimal": str(value)}
    if type(value) is bytes:
        return {"bytes_digest": digest(value)}
    if type(value) in (list, tuple):
        return [_fence_json(item) for item in value]
    if type(value) is dict:
        return {key: _fence_json(item) for key, item in value.items()}
    return draft_policy._observation_json(value)


def _review_authority(*, request, slug, revision, resolver, action):
    context, subject = draft_policy.load_native(
        request=request, workspace_slug=slug, initiative_id=revision.initiative_id
    )
    captured = draft_policy.capture_authorized(
        context=context,
        subject=subject,
        resolver=resolver,
        definition_ref=revision.payload["definition_ref"],
        action="READ_REVISION",
    )
    require(captured.identity == revision.original_input_identity)
    if action == "PREPARE":
        require(
            context.initiative.creator_user_id == context.actor_id
            or str(context.actor_id) in captured.technical_contributor_ids
        )
    elif action != "READ":
        technical = next(v for v in context.reviewers if v["gate_type"] == "PLAN_APPROVAL")
        require(str(context.actor_id) == technical["approver_user_id"])
    principals = principals_for(captured.identity, context.actor_id, context.reviewers)
    raw = _fence_json(draft_policy.authority_fence(context, subject, captured))
    return Authority(
        context,
        captured,
        subject,
        principals,
        tuple(context.observed_members),
        {},
        digest(canonical_json(raw)),
        captured.file_fence,
    )


def _release_authority(*, request, slug, revision, resolver, action):
    """Original immutable inputs plus current native access, independently of old task progress.

    A moved task keeps its stable reservation identity. Its current project must
    have an active explicit Product association and be visible to every principal.
    No old observation or native membership is substituted for object read grants.
    """
    from plane.db.models import Issue, State, Workspace
    from plane.curve.models import (
        GateAssignment,
        Initiative,
        Product,
        ProjectAssociation,
    )
    from plane.curve.scoped_prd_models import ScopedPrdSubject
    from plane.curve.scope_proposal_policy import resolve_scope_items

    workspace = Workspace.objects.select_for_update().filter(slug=slug, id=revision.workspace_id).first()
    require(workspace is not None)
    initiative = Initiative.objects.find_by_id(
        workspace_id=workspace.id, record_id=revision.initiative_id, for_update=True
    )
    require(
        initiative is not None
        and initiative.mode == "STANDALONE"
        and initiative.state in {"PLANNING", "PAUSED", "CANCELLED"}
        and initiative.pending_scope_reopening_id is None
    )
    product = Product.objects.find_by_id(workspace_id=workspace.id, record_id=initiative.product_id, for_update=True)
    require(product is not None and product.state == "ACTIVE")
    now = timezone.now()
    assignments = list(
        GateAssignment.objects.select_for_update()
        .filter(workspace_id=workspace.id, initiative_id=initiative.id, valid_from__lte=now)
        .order_by("gate_type", "id")
    )
    assignments = [g for g in assignments if g.valid_until is None or g.valid_until > now]
    require(
        len(assignments) == 3
        and {g.gate_type for g in assignments} == {"PLAN_APPROVAL", "PRD_APPROVAL", "CODE_READINESS"}
    )
    if initiative.risk_tier in {"STANDARD", "HIGH"}:
        require(len({g.approver_user_id for g in assignments}) == 3)
    reviewers = tuple(
        dict(
            gate_type=g.gate_type,
            gate_assignment_id=str(g.id),
            approver_user_id=str(g.approver_user_id),
        )
        for g in assignments
    )
    if action not in {"READ_RELEASE", "REPLAY_PREPARE"}:
        require(
            str(request.user.id) == next(g["approver_user_id"] for g in reviewers if g["gate_type"] == "PLAN_APPROVAL")
        )
    identity = revision.original_input_identity
    principals = principals_for(identity, request.user.id, reviewers)
    users, people_fence = _require_people(workspace.id, principals, lock=True)
    captured = resolver.capture(
        workspace_id=workspace.id,
        initiative_id=initiative.id,
        definition_ref=identity["definition_ref"],
        principals=principals,
        action="READ_REVISION",
    )
    require(captured.identity == identity)
    if action == "REPLAY_PREPARE":
        require(
            initiative.creator_user_id == request.user.id or str(request.user.id) in captured.technical_contributor_ids
        )
    subject = (
        ScopedPrdSubject.objects.select_for_update()
        .filter(
            id=identity["approved_subject_ref"]["entity_id"],
            workspace_id=workspace.id,
            initiative_id=initiative.id,
            checkpoint_id=initiative.current_prd_checkpoint_id,
        )
        .first()
    )
    require(
        subject is not None
        and subject.digest == identity["approved_subject_ref"]["digest"]
        and str(initiative.workflow_version_id) == identity["workflow_ref"]["entity_id"]
    )
    context = SimpleNamespace(
        workspace=workspace,
        initiative=initiative,
        product=product,
        actor_id=uuid.UUID(str(request.user.id)),
        reviewers=reviewers,
    )
    draft_policy.require_prd_materials(context, captured)
    installation = uuid.UUID(str(settings.CURVE_LOCAL_PLANE_INSTALLATION_ID))
    tasks = captured.facts["proposed_delivery_refs"]
    require(tasks and all(t["provider_installation_id"] == str(installation) for t in tasks))
    ids = sorted(t["source_issue_id"] for t in tasks)
    # Guaranteed-existing native rows serialize first acquisition and project moves.
    issues = list(
        Issue.issue_objects.select_for_update(of=("self",)).filter(workspace_id=workspace.id, id__in=ids).order_by("id")
    )
    require(len(issues) == len(ids))
    projects = {v.project_id for v in issues}
    associations = list(
        ProjectAssociation.objects.select_for_update()
        .filter(
            workspace_id=workspace.id,
            product_id=product.id,
            provider_installation_id=installation,
            source_project_id__in=projects,
            state="ACTIVE",
        )
        .order_by("id")
    )
    require(len(associations) == len(projects) and {a.source_project_id for a in associations} == projects)
    by_project = {a.source_project_id: a for a in associations}
    selections = [
        dict(
            association_id=str(by_project[i.project_id].id),
            association_version=by_project[i.project_id].version,
            source_issue_id=str(i.id),
            purpose="PROPOSED_DELIVERY",
        )
        for i in issues
    ]
    native_fences, observed = [], None
    for user in users:
        rows, fence = resolve_scope_items(
            SimpleNamespace(
                workspace=workspace,
                product=product,
                initiative=initiative,
                installation_id=installation,
                user=user,
            ),
            selections,
        )
        rows = tuple({k: v for k, v in row.items() if k != "source_observed_at"} for row in rows)
        require(observed is None or observed == rows)
        observed = rows
        native_fences.append((user.id, fence))
    groups = {str(i.id): State.objects.get(id=i.state_id).group for i in issues}
    raw = dict(
        people=draft_policy._observation_json(people_fence),
        native=draft_policy._observation_json(native_fences),
        assignments=draft_policy._observation_json(
            [(g.id, g.approver_user_id, g.valid_from, g.valid_until) for g in assignments]
        ),
        product=[str(product.id), product.version, product.state],
        initiative=[
            str(initiative.id),
            initiative.state,
            str(initiative.controlling_prd_decision_id),
            str(initiative.current_prd_checkpoint_id),
            str(initiative.workflow_version_id),
            initiative.risk_tier,
        ],
        grants=list(captured.grants),
        catalog_generation=captured.catalog_generation,
        input_identity_digest=identity["digest"],
    )
    return Authority(
        context,
        captured,
        subject,
        principals,
        observed,
        groups,
        digest(canonical_json(raw)),
        captured.file_fence,
    )


def load_authority(*, request, slug, revision, resolver, action):
    require_enabled(request, slug)
    require(type(resolver) is SyntheticManualPlanResolverV2)
    require(transaction.get_connection().in_atomic_block)
    if action in {
        "RECONCILE",
        "RELEASE",
        "READ_RELEASE",
        "REPLAY_PREPARE",
        "REPLAY_DECISION",
    }:
        return _release_authority(
            request=request,
            slug=slug,
            revision=revision,
            resolver=resolver,
            action=action,
        )
    return _review_authority(request=request, slug=slug, revision=revision, resolver=resolver, action=action)


def read_rationale(authority, resolver, command):
    ref = command.payload["rationale_ref"]
    if ref is None:
        return (), None
    catalog, _, _, catalog_fence = resolver.authorize(
        workspace_id=authority.context.workspace.id,
        initiative_id=authority.context.initiative.id,
        principals=authority.principals,
        action="READ_REVISION",
    )
    raw, fence, grants = resolver.read_material(
        catalog=catalog,
        workspace_id=authority.context.workspace.id,
        reference=ref,
        principals=authority.principals,
        action="READ_REVISION",
    )
    value = parse_strict_json(raw, max_bytes=16384)
    validate("rationale", value)
    expected = "RECONCILE" if command.action == "RELEASE" else command.action
    require(
        value["workspace_id"] == str(authority.context.workspace.id)
        and value["initiative_id"] == str(authority.context.initiative.id)
        and value["draft_revision_id"] == command.payload["draft_revision_id"]
        and value["intent"] == expected
        and bool(value["text"].strip())
        and value["no_unresolved_controlled_work"] is (expected == "RECONCILE")
    )
    return (catalog_fence, fence), digest(canonical_json(list(grants)))


def assert_active(receipt):
    if (
        type(receipt) is not Receipt
        or receipt.token is not _TOKEN
        or _ACTIVE.get() is not receipt
        or not transaction.get_connection().in_atomic_block
    ):
        raise PermissionError("Active exact Gate 2 receipt required")


@contextmanager
def record_authorization(*, request, authority, command, fence):
    from plane.curve.config import curve_policy_recorder
    from plane.curve.models import PolicyDecision
    from plane.curve.policy_services import (
        _next_policy_sequence,
        correlation_id_for_request,
    )

    context = authority.context
    actor = dict(actor_type="HUMAN", actor_id=str(context.actor_id))
    action = "CURVE.MANUAL_GATE2." + command.action + "_V2"
    now = timezone.now()
    decision = PolicyDecision.objects.create(
        workspace_id=context.workspace.id,
        sequence=_next_policy_sequence(
            workspace_id=context.workspace.id,
            resource_type="INITIATIVE",
            resource_id=context.initiative.id,
        ),
        action=action,
        resource_type="INITIATIVE",
        resource_id=context.initiative.id,
        resource_version=context.initiative.version,
        subject=actor,
        effective_principal=actor,
        effect="ALLOW",
        reason_codes=["ALLOW"],
        policy_key=POLICY_KEY,
        policy_version=2,
        policy_manifest_digest=policy_digest(),
        input_digest=digest(canonical_json(dict(request_digest=command.request_digest, native_fence_digest=fence))),
        normalized_classification="INTERNAL",
        permitted_projection=["MANUAL_GATE2_METADATA_V2"],
        correlation_id=correlation_id_for_request(request),
        evaluated_at=now,
        recorded_at=now,
        recorded_by=curve_policy_recorder(),
    )
    receipt = Receipt(
        context.workspace.id,
        context.initiative.id,
        context.actor_id,
        action,
        decision.id,
        command.request_digest,
        decision.correlation_id,
        _TOKEN,
    )
    token = _ACTIVE.set(receipt)
    try:
        yield receipt
    finally:
        _ACTIVE.reset(token)
