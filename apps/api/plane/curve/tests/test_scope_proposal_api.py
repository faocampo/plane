# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from io import BytesIO
from types import SimpleNamespace

import pytest
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from plane.curve.models import (
    AuditEvent,
    DomainEvent,
    IdempotencyRecord,
    GateAssignment,
    Initiative,
    PolicyDecision,
    ProjectAssociation,
    ImmutableRecordError,
)
from plane.curve.scope_proposal_models import ScopeProposal, ScopeProposalRevision, ScopeProposalItem
from plane.curve.scope_proposal_policy import POLICY_KEY
from plane.curve.scope_proposal_serialization import scope_membership_digest
from plane.curve.scope_proposal_services import parse_scope_body, ScopeCommandError
from plane.curve.tests.test_project_association_api import context, configuration, create, end, client  # noqa: F401
from plane.db.models import Issue, Project, ProjectMember, State, User, WorkspaceMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def scope_configuration(configuration, settings):  # noqa: F811
    settings.CURVE_SCOPE_PROPOSALS_ENABLED = True


@pytest.fixture
def scope(context):  # noqa: F811
    created = create(context)
    assert created.status_code == 201
    actor = {"actor_type": "HUMAN", "actor_id": str(context.user.id)}
    initiative = Initiative.objects.create(
        workspace_id=context.workspace.id,
        product_id=context.product.id,
        mode="STANDALONE",
        keyword="scope",
        title="Scope",
        description={},
        risk_tier="STANDARD",
        creator_user_id=context.user.id,
        created_by=actor,
        updated_by=actor,
    )
    for gate in ["PRD_APPROVAL", "PLAN_APPROVAL", "CODE_READINESS"]:
        GateAssignment.objects.create(
            workspace_id=context.workspace.id,
            initiative=initiative,
            gate_type=gate,
            approver_user_id=context.user.id,
        )
    state = State.objects.create(
        workspace=context.workspace, project=context.project, name="Todo", color="#000000", group="unstarted"
    )
    issue = Issue.objects.create(
        workspace=context.workspace,
        project=context.project,
        state=state,
        name="Private source body should never be projected",
        description_html="<p>Secret</p>",
        created_by=context.user,
    )
    ProjectMember.objects.filter(id=context.project_membership.id).update(role=15)
    Issue.objects.filter(id=issue.id).update(created_by_id=context.user.id)
    issue.refresh_from_db()
    context.initiative, context.issue, context.state = initiative, issue, state
    context.association = ProjectAssociation.objects.get(id=created.json()["id"])
    return context


def item(scope, issue=None, purpose="PROPOSED_DELIVERY", association=None):
    return dict(
        association_id=str((association or scope.association).id),
        association_version=1,
        source_issue_id=str((issue or scope.issue).id),
        purpose=purpose,
    )


def replace(scope, *, items=None, expected=0, version=1, key="scope-1", user=None, body=None, headers=None):
    values = {"HTTP_IDEMPOTENCY_KEY": key}
    if version is not None:
        values["HTTP_IF_MATCH"] = f'"curve-initiative:{scope.initiative.id}:v{version}"'
    values.update(headers or {})
    payload = {"expected_scope_revision": expected, "items": [item(scope)] if items is None else items}
    return client(user or scope.user).post(
        f"/api/v1/workspaces/alpha/curve/initiatives/{scope.initiative.id}/scope-proposal/",
        json.dumps(payload).encode() if body is None else body,
        content_type="application/json",
        **values,
    )


def read(scope, revision_id=None, user=None):
    suffix = f"revisions/{revision_id}/" if revision_id else ""
    return client(user or scope.user).get(
        f"/api/v1/workspaces/alpha/curve/initiatives/{scope.initiative.id}/scope-proposal/{suffix}"
    )


def test_whole_replacements_withdrawal_history_and_no_native_changes(scope):
    source = Issue.objects.filter(id=scope.issue.id).values().get()
    project = Project.objects.filter(id=scope.project.id).values().get()
    gates = list(GateAssignment.objects.filter(initiative=scope.initiative).values())
    first = replace(scope)
    assert first.status_code == 201, first.content
    initial = first.json()
    assert initial["controlling"] is False and initial["delivery_count"] == 1
    assert initial["version"] == 1 and initial["initiative_version"] == 2
    assert "Secret" not in first.content.decode() and "Private source" not in first.content.decode()
    assert read(scope).json() == initial
    second = replace(scope, items=[], expected=1, version=2, key="withdraw")
    assert second.status_code == 201, second.content
    assert second.json()["predecessor_id"] == initial["id"] and second.json()["item_count"] == 0
    assert read(scope, initial["id"]).json() == initial
    replay = replace(scope)
    assert replay.status_code == 201 and replay.json() == initial
    assert ScopeProposal.objects.count() == 1 and ScopeProposalRevision.objects.count() == 2
    assert ScopeProposalItem.objects.count() == 1
    assert Issue.objects.filter(id=scope.issue.id).values().get() == source
    assert Project.objects.filter(id=scope.project.id).values().get() == project
    assert list(GateAssignment.objects.filter(initiative=scope.initiative).values()) == gates
    scope.initiative.refresh_from_db()
    assert scope.initiative.state == "DRAFT" and scope.initiative.version == 3
    assert scope.initiative.current_prd_checkpoint_id is None and scope.initiative.controlling_prd_decision_id is None
    for decision in PolicyDecision.objects.filter(policy_key=POLICY_KEY):
        assert AuditEvent.objects.filter(policy_decision_ref__resource_id=str(decision.id)).count() == 1
    assert end(scope, scope.association.id).status_code == 503


def test_finite_children_canonical_order_and_idempotency(scope):
    child = Issue.objects.create(
        workspace=scope.workspace,
        project=scope.project,
        state=scope.state,
        parent=scope.issue,
        name="Child",
        created_by=scope.user,
    )
    selections = [item(scope), item(scope, child, "CONTEXT_EVIDENCE")]
    first = replace(scope, items=selections)
    assert first.status_code == 201, first.content
    Issue.objects.create(
        workspace=scope.workspace,
        project=scope.project,
        state=scope.state,
        parent=scope.issue,
        name="Future child",
        created_by=scope.user,
    )
    replay = replace(scope, items=list(reversed(selections)))
    assert replay.status_code == 201 and replay.json() == first.json()
    assert len(read(scope).json()["items"]) == 2
    changed = replace(scope, items=[item(scope)], key="scope-1")
    assert changed.status_code == 409
    assert first.json()["membership_digest"] == scope_membership_digest(first.json()["items"])


@pytest.mark.parametrize(
    "body,status",
    [
        (b'{"expected_scope_revision":0,"expected_scope_revision":0,"items":[]}', 422),
        (b'{"expected_scope_revision":NaN,"items":[]}', 422),
        (b'{"expected_scope_revision":Infinity,"items":[]}', 422),
        (b'{"expected_scope_revision":true,"items":[]}', 422),
        (b'{"expected_scope_revision":null,"items":[]}', 428),
        (b'{"expected_scope_revision":0,"items":[],"include_descendants":true}', 422),
        (b" " * 65537, 413),
        (b'{"expected_scope_revision":0,"items":[]}' + b" " * 65498, 413),
    ],
    ids=["duplicate", "nan", "infinity", "bool", "null", "unknown", "over-limit", "trailing-over-limit"],
)
def test_closed_bounded_raw_json(scope, body, status):
    response = replace(scope, body=body)
    assert response.status_code == status, response.content
    assert ScopeProposal.objects.count() == 0


def test_member_limit_duplicates_versions_and_uuid_validation(scope):
    selections = [dict(item(scope), source_issue_id=str(uuid.uuid4())) for _ in range(101)]
    assert replace(scope, items=selections).status_code == 422
    assert replace(scope, items=[item(scope), item(scope, purpose="CONTEXT_EVIDENCE")]).status_code == 422
    assert replace(scope, items=[dict(item(scope), association_version=True)]).status_code == 422
    assert replace(scope, items=[dict(item(scope), source_issue_id=str(scope.issue.id).upper())]).status_code == 422
    assert replace(scope, version=None).status_code == 428
    assert replace(scope, expected=1).status_code == 412
    assert replace(scope, version=99).status_code == 412
    assert ScopeProposal.objects.count() == 0


def test_preparse_limit_does_not_trust_content_length():
    from plane.middleware.request_body_size import RequestBodySizeLimitMiddleware

    for length in (None, "0", "2", "999999999"):
        reads = []
        stream = BytesIO(b"x" * 100000)

        def bounded_read(size):
            reads.append(size)
            return stream.read(size)

        request = SimpleNamespace(
            path_info="/api/v1/workspaces/alpha/curve/initiatives/x/scope-proposal/",
            read=bounded_read,
            META={} if length is None else {"CONTENT_LENGTH": length},
        )
        response = RequestBodySizeLimitMiddleware(lambda _: None)(request)
        assert response.status_code == 413 and reads == [65537]
        assert json.loads(response.content)["correlation_id"].startswith("curve-")
        assert response["Cache-Control"] == "no-store"
    with pytest.raises(ScopeCommandError):
        parse_scope_body(b"x" * 65537)


@pytest.mark.parametrize(
    "setting,value",
    [
        ("CURVE_SCOPE_PROPOSALS_ENABLED", False),
        ("CURVE_SCOPE_PROPOSALS_ENABLED", "true"),
        ("CURVE_ENVIRONMENT", "PRODUCTION"),
        ("CURVE_ENABLED", False),
        ("CURVE_LOCAL_PLANE_INSTALLATION_ID", None),
    ],
)
def test_default_local_gate(scope, settings, setting, value):
    setattr(settings, setting, value)
    assert replace(scope).status_code == 404
    assert ScopeProposal.objects.count() == 0


@pytest.mark.parametrize("state,paused", [("ALIGNING", None), ("PAUSED", "DRAFT"), ("CANCELLED", None)])
def test_draft_only_edits(scope, state, paused):
    scope.initiative.state = state
    scope.initiative.paused_from_state = paused
    scope.initiative.workflow_version_id = uuid.uuid4() if state == "ALIGNING" else None
    scope.initiative.save()
    assert replace(scope).status_code == 409


@pytest.mark.parametrize(
    "target,changes",
    [
        ("user", {"is_active": False}),
        ("user", {"is_bot": True}),
        ("membership", {"is_active": False}),
        ("membership", {"role": 99}),
        ("project_membership", {"is_active": False}),
        ("project_membership", {"role": 99}),
        ("project_membership", {"deleted_at": timezone.now()}),
        ("project", {"deleted_at": timezone.now()}),
        ("project", {"archived_at": timezone.now()}),
        ("issue", {"is_draft": True}),
        ("issue", {"archived_at": timezone.now().date()}),
        ("issue", {"deleted_at": timezone.now()}),
        ("state", {"deleted_at": timezone.now()}),
        ("state", {"group": "triage"}),
    ],
)
def test_fresh_native_actor_item_authority(scope, target, changes):
    value = getattr(scope, target)
    type(value).objects.filter(id=value.id).update(**changes)
    response = replace(scope, headers={"HTTP_X_ROLE": "ADMIN", "HTTP_X_ITEM_ACCESS": "ALLOW"})
    assert response.status_code == 404, response.content
    assert ScopeProposal.objects.count() == 0


@pytest.mark.parametrize(
    "child,own,view_all,allowed",
    [
        (False, True, False, True),
        (False, False, False, False),
        (True, True, False, True),
        (True, False, False, False),
        (False, False, True, True),
        (True, False, True, True),
    ],
)
def test_native_restricted_guest_roots_and_children(scope, child, own, view_all, allowed):
    other = User.objects.create(username="other", email="other@example.invalid")
    selected = Issue.objects.create(
        workspace=scope.workspace,
        project=scope.project,
        state=scope.state,
        name="Selected",
        parent=scope.issue if child else None,
        created_by=scope.user if own else other,
    )
    Issue.objects.filter(id=selected.id).update(created_by_id=scope.user.id if own else other.id)
    ProjectMember.objects.filter(id=scope.project_membership.id).update(role=5)
    Project.objects.filter(id=scope.project.id).update(guest_view_all_features=view_all)
    response = replace(scope, items=[item(scope, selected)])
    assert response.status_code == (201 if allowed else 404), response.content
    # Compare to the canonical native explicit-list permission implementation.
    from plane.app.views.issue.base import IssueListEndpoint

    request = APIRequestFactory().get("/", {"issues": str(selected.id)})
    force_authenticate(request, user=scope.user)
    # Native endpoint schedules recent-visit telemetry; suppress only that task.
    from unittest.mock import patch

    with patch("plane.app.views.issue.base.recent_visited_task.delay"):
        native = IssueListEndpoint.as_view()(request, slug="alpha", project_id=scope.project.id)
    assert native.status_code == 200
    assert bool(native.data) == allowed


def test_creator_or_workspace_admin_and_public_not_membership_bypass(scope):
    outsider = User.objects.create(username="member", email="member@example.invalid")
    WorkspaceMember.objects.create(workspace=scope.workspace, member=outsider, role=15)
    ProjectMember.objects.create(workspace=scope.workspace, project=scope.project, member=outsider, role=15)
    assert replace(scope, user=outsider).status_code == 404
    WorkspaceMember.objects.filter(workspace=scope.workspace, member=outsider).update(role=20)
    assert replace(scope, user=outsider).status_code == 201
    Project.objects.filter(id=scope.project.id).update(network=2)
    ProjectMember.objects.filter(project=scope.project, member=outsider).update(is_active=False)
    assert read(scope, user=outsider).status_code == 404


def test_original_replay_revocation_after_withdrawal(scope):
    first = replace(scope)
    assert first.status_code == 201
    assert replace(scope, items=[], expected=1, version=2, key="withdraw").status_code == 201
    ProjectMember.objects.filter(id=scope.project_membership.id).update(is_active=False)
    assert read(scope).status_code == 200
    assert read(scope, first.json()["id"]).status_code == 404
    assert replace(scope).status_code == 404


def test_source_move_and_cross_product_identity_rejected(scope):
    other = Project.objects.create(workspace=scope.workspace, name="Other", identifier="OTHER")
    ProjectMember.objects.create(workspace=scope.workspace, project=other, member=scope.user)
    Issue.objects.filter(id=scope.issue.id).update(project_id=other.id)
    assert replace(scope).status_code == 404
    Issue.objects.filter(id=scope.issue.id).update(project_id=scope.project.id)
    assert replace(scope, items=[dict(item(scope), association_id=str(uuid.uuid4()))]).status_code == 404
    assert replace(scope, items=[dict(item(scope), association_version=2)]).status_code == 412


def test_source_is_not_cascaded_or_fk_blocked(scope):
    assert replace(scope).status_code == 201
    Issue.all_objects.filter(id=scope.issue.id).delete()
    assert ScopeProposalItem.objects.count() == 1
    assert read(scope).status_code == 404


def test_atomic_outbox_failure_and_last_moment_revocation(scope, monkeypatch):
    import plane.curve.scope_proposal_services as services

    original = services.OutboxEvent.objects.create

    def fail(**kwargs):
        if kwargs.get("destination") == "CURVE_SCOPE_PROPOSAL_LOCAL_V1":
            raise IntegrityError("synthetic")
        return original(**kwargs)

    monkeypatch.setattr(services.OutboxEvent.objects, "create", fail)
    assert replace(scope).status_code == 409
    assert (
        ScopeProposal.objects.count() == ScopeProposalRevision.objects.count() == ScopeProposalItem.objects.count() == 0
    )
    scope.initiative.refresh_from_db()
    assert scope.initiative.version == 1
    monkeypatch.setattr(services.OutboxEvent.objects, "create", original)
    audit = services.append_scope_audit

    def revoke(receipt, **kwargs):
        result = audit(receipt, **kwargs)
        Project.objects.filter(id=scope.project.id).update(guest_view_all_features=False)
        ProjectMember.objects.filter(id=scope.project_membership.id).update(role=99)
        return result

    monkeypatch.setattr(services, "append_scope_audit", revoke)
    assert replace(scope).status_code == 404
    assert ScopeProposal.objects.count() == 0
    scope.project_membership.refresh_from_db()
    assert scope.project_membership.role != 99  # callback effects rolled back


def test_concurrent_replacements_serialize_on_initiative(scope):
    def command(key):
        close_old_connections()
        try:
            response = replace(scope, key=key)
            return response.status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(command, ["one", "two"]))
    assert sorted(statuses) == [201, 412]
    assert ScopeProposalRevision.objects.count() == 1


def test_sql_and_model_history_cannot_be_rewritten_or_extended(scope):
    first = replace(scope)
    assert first.status_code == 201
    assert replace(scope, items=[], expected=1, version=2, key="withdraw").status_code == 201
    head, revision, member = (
        ScopeProposal.objects.get(),
        ScopeProposalRevision.objects.get(id=first.json()["id"]),
        ScopeProposalItem.objects.get(),
    )
    for record in [revision, member, head]:
        with pytest.raises((ImmutableRecordError, PermissionError)):
            record.save()
        with pytest.raises(ImmutableRecordError):
            type(record).objects.filter(id=record.id).delete()
    attempts = [
        ("UPDATE curve_scope_proposal SET current_revision_id = %s, version = 1 WHERE id = %s", [revision.id, head.id]),
        ("UPDATE curve_scope_proposal_revision SET delivery_count = 0 WHERE id = %s", [revision.id]),
        ("DELETE FROM curve_scope_proposal_item WHERE id = %s", [member.id]),
        (
            "INSERT INTO curve_scope_proposal_item SELECT %s, workspace_id, revision_id, association_id, "
            "association_version, provider_installation_id, source_project_id, %s, purpose, source_observed_at, "
            "source_version, source_fingerprint FROM curve_scope_proposal_item WHERE id = %s",
            [uuid.uuid4(), uuid.uuid4(), member.id],
        ),
    ]
    for sql, values in attempts:
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql, values)
    assert read(scope, revision.id).json() == first.json()


def test_migration_reversal_preserves_evidence(scope):
    assert replace(scope).status_code == 201
    migration = import_module("plane.curve.migrations.0021_scope_proposal")
    with pytest.raises(IntegrityError, match="preservation"), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(migration.REVERSE_GUARDS)
    assert ScopeProposalRevision.objects.count() == 1


def test_exact_hundred_explicit_members_is_supported(scope):
    selections = [item(scope)]
    for number in range(99):
        issue = Issue.objects.create(
            workspace=scope.workspace, project=scope.project, state=scope.state, name=f"Explicit {number}"
        )
        selections.append(item(scope, issue, "CONTEXT_EVIDENCE"))
    response = replace(scope, items=selections)
    assert response.status_code == 201, response.content
    assert response.json()["item_count"] == 100
    assert response.json()["delivery_count"] == 1
    assert ScopeProposalItem.objects.count() == 100


@pytest.mark.parametrize(
    "target,changes",
    [
        ("project", {"guest_view_all_features": True}),
        ("state", {"group": "started"}),
        ("issue", {"parent_id": None, "is_draft": True}),
        ("user", {"is_bot": True}),
        ("membership", {"role": 5}),
    ],
)
def test_final_native_observation_fence_rolls_back_after_callback(scope, monkeypatch, target, changes):
    import plane.curve.scope_proposal_services as services

    audit = services.append_scope_audit

    def change_source(receipt, **kwargs):
        result = audit(receipt, **kwargs)
        value = getattr(scope, target)
        type(value).objects.filter(id=value.id).update(**changes)
        return result

    monkeypatch.setattr(services, "append_scope_audit", change_source)
    assert replace(scope).status_code == 404
    assert ScopeProposalRevision.objects.count() == 0
    assert IdempotencyRecord.objects.filter(command_scope__startswith="CURVE.SCOPE_PROPOSAL").count() == 0
    assert DomainEvent.objects.filter(aggregate_type="SCOPE_PROPOSAL").count() == 0
    scope.initiative.refresh_from_db()
    assert scope.initiative.version == 1


def test_no_source_content_is_loaded_for_scope(scope):
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as captured:
        assert replace(scope).status_code == 201
    issue_reads = [
        query["sql"]
        for query in captured.captured_queries
        if query["sql"].startswith("SELECT") and 'FROM "issues"' in query["sql"]
    ]
    assert issue_reads
    for query in issue_reads:
        assert '"issues"."description' not in query and '"issues"."name"' not in query


def test_context_purpose_does_not_import_evidence_or_approve(scope):
    from plane.curve.models import PrdEvidenceSnapshot, PrdReviewDecision

    assert replace(scope, items=[item(scope, purpose="CONTEXT_EVIDENCE")]).status_code == 201
    assert PrdEvidenceSnapshot.objects.count() == PrdReviewDecision.objects.count() == 0
    assert read(scope).json()["delivery_count"] == 0


def test_audit_failure_rolls_back_entire_authorized_command(scope, monkeypatch):
    import plane.curve.scope_proposal_policy as policy

    original = policy._append_audit_event

    def fail(**kwargs):
        if kwargs.get("action") == "CURVE.SCOPE_PROPOSAL.REPLACE":
            raise RuntimeError("synthetic audit unavailable")
        return original(**kwargs)

    monkeypatch.setattr(policy, "_append_audit_event", fail)
    response = replace(scope)
    assert response.status_code == 500
    assert "synthetic audit" not in response.content.decode()
    assert (
        ScopeProposal.objects.count() == ScopeProposalRevision.objects.count() == ScopeProposalItem.objects.count() == 0
    )
    assert PolicyDecision.objects.filter(policy_key=POLICY_KEY).count() == 0
    scope.initiative.refresh_from_db()
    assert scope.initiative.version == 1


def test_wrong_product_and_installation_never_authorize_selection(scope, settings):
    from plane.curve.models import Product

    actor = {"actor_type": "HUMAN", "actor_id": str(scope.user.id)}
    other = Product.objects.create(
        workspace_id=scope.workspace.id,
        key="other-product",
        name="Other",
        timezone="UTC",
        owner_user_id=scope.user.id,
        created_by=actor,
        updated_by=actor,
    )
    other_initiative = Initiative.objects.create(
        workspace_id=scope.workspace.id,
        product_id=other.id,
        mode="STANDALONE",
        keyword="other-scope",
        title="Other",
        description={},
        risk_tier="STANDARD",
        creator_user_id=scope.user.id,
        created_by=actor,
        updated_by=actor,
    )
    original = scope.initiative
    scope.initiative = other_initiative
    assert replace(scope).status_code == 404
    scope.initiative = original
    settings.CURVE_LOCAL_PLANE_INSTALLATION_ID = str(uuid.uuid4())
    assert replace(scope).status_code == 404


def test_workspace_member_creator_can_edit_but_readers_cannot_edit(scope):
    WorkspaceMember.objects.filter(id=scope.membership.id).update(role=15)
    assert replace(scope).status_code == 201
    other = User.objects.create(username="reader", email="reader@example.invalid")
    WorkspaceMember.objects.create(workspace=scope.workspace, member=other, role=15)
    ProjectMember.objects.create(workspace=scope.workspace, project=scope.project, member=other, role=15)
    assert read(scope, user=other).status_code == 200
    assert replace(scope, user=other, expected=1, version=2, key="unauthorized").status_code == 404


def test_ended_association_preserves_history_but_rejects_read_and_replay(scope, monkeypatch):
    import plane.curve.project_association_services as associations

    assert replace(scope).status_code == 201
    # Only the old association test-double path may exercise terminal history;
    # production END remains 503 and no C1 setting replaces its guard.
    monkeypatch.setattr(associations, "assert_association_can_end", lambda **_: None)
    assert end(scope, scope.association.id).status_code == 200
    assert read(scope).status_code == 404
    assert replace(scope).status_code == 404
    assert ScopeProposalItem.objects.count() == 1


def test_missing_scope_version_is_required(scope):
    assert replace(scope, body=b'{"items":[]}').status_code == 428


def _last_scope_decision():
    return PolicyDecision.objects.filter(policy_key=POLICY_KEY).order_by("-recorded_at").first()


def _assert_source_denial():
    decision = _last_scope_decision()
    assert decision.effect == "DENY" and decision.reason_codes == ["RESOURCE_NOT_FOUND"]
    assert decision.permitted_projection == []
    audit = AuditEvent.objects.get(policy_decision_ref__resource_id=str(decision.id))
    assert audit.outcome == "DENIED"
    return decision


def test_forbidden_guest_records_final_deny_not_allow(scope):
    ProjectMember.objects.filter(id=scope.project_membership.id).update(role=5)
    Issue.objects.filter(id=scope.issue.id).update(created_by_id=None)
    assert replace(scope).status_code == 404
    _assert_source_denial()
    assert PolicyDecision.objects.filter(policy_key=POLICY_KEY).count() == 1


def test_revoked_original_replay_records_deny_even_when_current_is_empty(scope):
    assert replace(scope).status_code == 201
    assert replace(scope, items=[], expected=1, version=2, key="withdraw").status_code == 201
    ProjectMember.objects.filter(id=scope.project_membership.id).update(is_active=False)
    assert replace(scope).status_code == 404
    _assert_source_denial()


def test_commit_permission_loss_discards_allow_and_records_one_deny(scope, monkeypatch):
    import plane.curve.scope_proposal_services as services

    audit = services.append_scope_audit

    def revoke(receipt, **kwargs):
        value = audit(receipt, **kwargs)
        Issue.objects.filter(id=scope.issue.id).update(is_draft=True)
        return value

    monkeypatch.setattr(services, "append_scope_audit", revoke)
    assert replace(scope).status_code == 404
    _assert_source_denial()
    assert PolicyDecision.objects.filter(policy_key=POLICY_KEY).count() == 1
    assert ScopeProposalRevision.objects.count() == 0


def test_full_visibility_precedes_stale_embedded_pin(scope):
    other = Issue.objects.create(
        id=uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        workspace=scope.workspace,
        project=scope.project,
        state=scope.state,
        name="Other",
    )
    Issue.objects.filter(id=other.id).update(created_by_id=None)
    ProjectMember.objects.filter(id=scope.project_membership.id).update(role=5)
    assert replace(scope, items=[dict(item(scope), association_version=2), item(scope, other)]).status_code == 404
    _assert_source_denial()
    ProjectMember.objects.filter(id=scope.project_membership.id).update(role=15)
    assert replace(scope, items=[dict(item(scope), association_version=2), item(scope, other)]).status_code == 412
    decision = _last_scope_decision()
    assert decision.effect == "ALLOW"
    assert AuditEvent.objects.get(policy_decision_ref__resource_id=str(decision.id)).outcome == "NO_EFFECT"


def test_decision_digest_pins_resolved_original_source_and_authority(scope, monkeypatch):
    import plane.curve.scope_proposal_policy as policy

    captured = []
    recorder = policy._record_scope_decision

    def observe(**kwargs):
        decision = recorder(**kwargs)
        captured.append((kwargs, decision))
        return decision

    monkeypatch.setattr(policy, "_record_scope_decision", observe)
    first = replace(scope)
    assert first.status_code == 201
    assert replace(scope, items=[], expected=1, version=2, key="withdraw").status_code == 201
    assert replace(scope).status_code == 201
    arguments, decision = captured[-1]
    assert str(arguments["resolved_revision_id"]) == first.json()["id"]
    assert len(arguments["source_fence"]) == 1
    assert arguments["context"].installation_id == scope.association.provider_installation_id
    assert len(arguments["context"].authority_fence) > 0
    previous_digest = decision.input_digest
    State.objects.filter(id=scope.state.id).update(group="started")
    assert replace(scope).status_code == 201
    assert captured[-1][1].input_digest != previous_digest
    assert first.json()["membership_digest"] == read(scope, first.json()["id"]).json()["membership_digest"]
