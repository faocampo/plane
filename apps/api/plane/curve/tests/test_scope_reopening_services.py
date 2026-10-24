# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Real migrated PostgreSQL C2b lifecycle, authority and safe replacement metadata."""
# ruff: noqa: F811 - imported pytest fixtures intentionally name test parameters.

from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import json
import uuid

import pytest
from django.db import connection
from django.utils import timezone
from jsonschema import Draft202012Validator, FormatChecker
from rest_framework.test import APIClient

from plane.db.models import Issue, Project, ProjectMember, WorkspaceMember
from plane.curve.models import (
    AuditEvent,
    DocumentCheckpoint,
    DomainEvent,
    IdempotencyRecord,
    Operation,
    OutboxEvent,
    PolicyDecision,
    PrdReadinessRecord,
    PrdReviewDecision,
)
from plane.curve.policy_services import CurvePolicyDenied, CurvePolicyResourceNotFound
from plane.curve.prd_acceptance import accept_prd_command
from plane.curve.prd_commands import PrdCommandError, parse_prd_command
from plane.curve.prd_completion import PrdCompletionUnavailable
from plane.curve.scope_proposal_models import ScopeProposal, ScopeProposalItem, ScopeProposalRevision
from plane.curve.scope_reopening_contracts import ACTION, POLICY_EDITION, SCHEMA_VERSION
from plane.curve.scope_reopening_models import ScopeReopening
from plane.curve.scope_reopening_services import reopen_and_replace_scope
from plane.curve.scoped_prd_models import (
    ScopedPrdAcceptedCommand,
    ScopedPrdDecision,
    ScopedPrdObservation,
    ScopedPrdReadiness,
    ScopedPrdSubject,
)
from plane.curve.services import IdempotencyConflict, OptimisticConcurrencyError, ReplayResourceUnavailable
from plane.curve.tests.test_prd_policy_context import resolver
from plane.curve.tests.test_scoped_prd_bridge import (  # noqa: F401
    accept,
    bridge,
    cmd,
    complete,
    configuration,
    configure_read_runtime,
    context,
    observe,
    pins,
    review_command,
    submission,
    submit,
)

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]
REASON = "Synthetic private reopening reason never retained verbatim"
DENIED = (
    PrdCommandError,
    CurvePolicyDenied,
    CurvePolicyResourceNotFound,
    OptimisticConcurrencyError,
    ReplayResourceUnavailable,
    IdempotencyConflict,
)
HISTORY_MODELS = (
    DocumentCheckpoint,
    PrdReadinessRecord,
    PrdReviewDecision,
    ScopedPrdObservation,
    ScopedPrdReadiness,
    ScopedPrdSubject,
    ScopedPrdDecision,
    ScopedPrdAcceptedCommand,
    Operation,
)


@pytest.fixture
def reopening(bridge, settings):
    settings.CURVE_SCOPE_REOPENING_ENABLED = True
    return bridge


def selection(bridge, issue=None, purpose="PROPOSED_DELIVERY"):
    return dict(
        association_id=str(bridge.association.id),
        association_version=1,
        source_issue_id=str((issue or bridge.issue).id),
        purpose=purpose,
    )


def replacement(bridge, *, items=None, expected=None, reason=REASON):
    return dict(
        schema_version=SCHEMA_VERSION,
        policy_edition=POLICY_EDITION,
        expected_scope_revision=bridge.scope["version"] if expected is None else expected,
        reason=reason,
        items=[selection(bridge)] if items is None else items,
    )


def reopen(bridge, *, payload=None, version=None, key="reopen-1", request=None):
    return reopen_and_replace_scope(
        request=request or bridge.request,
        workspace_slug=bridge.workspace.slug,
        initiative_id=bridge.initiative.id,
        payload=replacement(bridge) if payload is None else payload,
        expected_version=bridge.initiative.version if version is None else version,
        raw_idempotency_key=key,
    )


def adopt(bridge, result):
    bridge.scope = result.data["revision"]
    bridge.initiative.refresh_from_db()
    return result


def post(bridge, *, payload=None, body=None, headers=None, user=None, csrf=False):
    client = APIClient(enforce_csrf_checks=csrf)
    client.force_authenticate(user=user or bridge.user)
    return client.post(
        f"/api/v1/workspaces/{bridge.workspace.slug}/curve/initiatives/{bridge.initiative.id}"
        "/scope-reopening/v1/reopen-and-replace/",
        data=json.dumps(replacement(bridge) if payload is None else payload) if body is None else body,
        content_type="application/json",
        **(
            {"HTTP_IF_MATCH": f'"{bridge.initiative.version}"', "HTTP_IDEMPOTENCY_KEY": "reopen-http"}
            if headers is None
            else headers
        ),
    )


def make_issue(bridge, *, parent=None, creator=None):
    issue = Issue.objects.create(
        workspace=bridge.workspace,
        project=bridge.project,
        state=bridge.state,
        parent=parent,
        name="Replacement selected metadata",
        created_by=creator or bridge.user,
    )
    Issue.objects.filter(id=issue.id).update(created_by_id=(creator or bridge.user).id)
    issue.refresh_from_db()
    return issue


def raw_gate(gate, **changes):
    columns = ", ".join(f"{connection.ops.quote_name(key)} = %s" for key in changes)
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE curve_gate_assignment SET {columns} WHERE id = %s", [*changes.values(), gate.id])


def history():
    return {model._meta.db_table: list(model.objects.order_by("pk").values()) for model in HISTORY_MODELS}


def stage(bridge, state):
    if state == "ALIGNING":
        return None, None, None
    subject, command, operation = submit(bridge)
    if state == "PLANNING":
        command = review_command(bridge, subject)
        operation = accept(bridge, command).operation
        assert complete(bridge, operation)["status"] == "SUCCEEDED"
        bridge.initiative.refresh_from_db()
    return subject, command, operation


def no_reopening(bridge):
    bridge.initiative.refresh_from_db()
    assert bridge.initiative.pending_scope_reopening_id is None
    assert not ScopeReopening.objects.exists()
    assert ScopeProposalRevision.objects.count() == 1


@pytest.mark.parametrize("state", ["ALIGNING", "PRD_REVIEW", "PLANNING"])
def test_each_allowed_state_invalidates_authority_without_rewriting_history(reopening, state):
    stage(reopening, state)
    original_scope = deepcopy(reopening.scope)
    checkpoint = reopening.initiative.current_prd_checkpoint_id
    decision = reopening.initiative.controlling_prd_decision_id
    version = reopening.initiative.version
    old_history = history()
    source = Issue.objects.filter(id=reopening.issue.id).values().get()
    result = reopen(reopening)
    assert result.response_status == 201 and result.replayed is False
    data = result.data
    schema = json.loads(
        (Path(__file__).parents[1] / "scope_reopening_candidate/scope-reopening-receipt-v1.schema.json").read_text()
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(data)
    reopening.initiative.refresh_from_db()
    assert reopening.initiative.state == "ALIGNING" and reopening.initiative.version == version + 1
    assert reopening.initiative.pending_scope_reopening_id == uuid.UUID(data["id"])
    assert reopening.initiative.current_prd_checkpoint_id == checkpoint
    assert reopening.initiative.controlling_prd_decision_id is None
    assert data["approval_invalidated"] is (decision is not None)
    assert data["historical_checkpoint_status"] == ("RETAINED_STALE" if checkpoint else "NONE")
    assert data["prd_authority"] == "REQUIRES_FRESH_SCOPED_SUBMISSION"
    assert data["previous_initiative_version"] == version and data["previous_state"] == state
    assert data["controlling"] is False and data["revision"]["controlling"] is False
    assert data["revision"]["predecessor_id"] == original_scope["id"]
    assert data["revision"]["schema_version"] == "2.0"
    assert data["revision"]["policy_edition"] == "REOPENED_EXISTING_WORK_SCOPE_PROPOSAL_V1"
    assert history() == old_history
    assert Issue.objects.filter(id=reopening.issue.id).values().get() == source
    record = ScopeReopening.objects.get(id=data["id"])
    assert record.previous_checkpoint_id == checkpoint and record.previous_decision_id == decision
    assert record.previous_initiative_version == version and record.previous_state == state
    assert record.as_record() == data
    assert record.reason_digest == "sha256:" + sha256(REASON.encode()).hexdigest()
    digestable = {key: value for key, value in data.items() if key != "digest"}
    assert (
        data["digest"]
        == "sha256:"
        + sha256(json.dumps(digestable, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    )
    head = ScopeProposal.objects.get(initiative_id=reopening.initiative.id)
    assert head.current_revision_id == uuid.UUID(data["revision"]["id"]) and head.version == 2
    assert ScopeProposalRevision.objects.count() == 2 and ScopeProposalItem.objects.count() == 2
    serialized = json.dumps(data)
    assert REASON not in serialized and "Private native acceptance" not in serialized
    assert not ({"previous_checkpoint_id", "previous_decision_id", "previous_members", "removed_items"} & data.keys())
    for model in (ScopeReopening, DomainEvent, OutboxEvent, PolicyDecision, AuditEvent, IdempotencyRecord):
        assert REASON not in json.dumps(list(model.objects.values()), default=str)
    assert OutboxEvent.objects.filter(event_id=record.command_receipt_id).count() == 1
    assert PolicyDecision.objects.get(id=record.policy_decision_id).policy_key == "CURVE_SCOPE_REOPENING_POLICY"
    assert AuditEvent.objects.filter(policy_decision_ref__resource_id=str(record.policy_decision_id)).count() == 1
    assert "curve_work_item_binding" not in connection.introspection.table_names()


@pytest.mark.parametrize("state", ["PRD_REVIEW", "PLANNING"])
def test_fresh_exact_submission_clears_marker_then_new_approval_is_required(reopening, state):
    old_subject, old_command, old_operation = stage(reopening, state)
    old_checkpoint = reopening.initiative.current_prd_checkpoint_id
    result = adopt(reopening, reopen(reopening))
    assert result.data["revision"]["version"] == 2
    observation = observe(reopening).data
    recaptured = observe(reopening).data
    assert recaptured["id"] != observation["id"]
    command = submission(reopening, recaptured)
    operation = accept(reopening, command).operation
    assert complete(reopening, operation)["status"] == "SUCCEEDED"
    reopening.initiative.refresh_from_db()
    assert reopening.initiative.pending_scope_reopening_id is None
    assert reopening.initiative.state == "PRD_REVIEW" and reopening.initiative.controlling_prd_decision_id is None
    checkpoint = DocumentCheckpoint.objects.get(id=reopening.initiative.current_prd_checkpoint_id)
    assert checkpoint.id != old_checkpoint and checkpoint.predecessor_id == old_checkpoint
    subject = ScopedPrdSubject.objects.get(checkpoint_id=checkpoint.id)
    assert subject.as_record()["scope_revision_id"] == result.data["revision"]["id"]
    reopening.runtime.capture = None
    reopening.runtime.records = (
        reopening.binding,
        reopening.initiative,
        checkpoint,
        reopening.gates[0],
        reopening.user,
        reopening.workspace,
    )
    approved = accept(reopening, review_command(reopening, subject)).operation
    assert complete(reopening, approved)["status"] == "SUCCEEDED"
    reopening.initiative.refresh_from_db()
    assert reopening.initiative.state == "PLANNING" and reopening.initiative.controlling_prd_decision_id is not None
    assert ScopedPrdSubject.objects.get(id=old_subject.id).digest == old_subject.digest
    with pytest.raises(DENIED):
        accept(reopening, old_command)
    with pytest.raises((PrdCommandError, PrdCompletionUnavailable)):
        complete(reopening, old_operation)


def test_replay_requires_current_successor_marker_scope_and_authority(reopening):
    original_payload = replacement(reopening)
    original_version = reopening.initiative.version
    result = adopt(reopening, reopen(reopening, payload=original_payload, version=original_version))
    replay = reopen(reopening, payload=original_payload, version=original_version)
    assert replay.response_status == 201 and replay.replayed and replay.data == result.data
    with pytest.raises(DENIED):
        reopen(reopening, payload=dict(original_payload, reason=REASON + " changed"), version=original_version)
    second = adopt(reopening, reopen(reopening, key="reopen-2"))
    assert second.data["revision"]["predecessor_id"] == result.data["revision"]["id"]
    ledger = ScopeReopening.objects.get(id=second.data["id"])
    assert ledger.previous_pending_reopening_id == uuid.UUID(result.data["id"])
    with pytest.raises(DENIED):
        reopen(reopening, payload=original_payload, version=original_version)
    assert ScopeReopening.objects.count() == 2 and ScopeProposalRevision.objects.count() == 3


def test_submission_makes_old_reopening_replay_unavailable(reopening):
    payload, version = replacement(reopening), reopening.initiative.version
    adopt(reopening, reopen(reopening, payload=payload, version=version))
    submit(reopening)
    with pytest.raises(DENIED):
        reopen(reopening, payload=payload, version=version)


@pytest.mark.parametrize("index", [0, 1, 2])
def test_replay_rechecks_each_reviewer_native_access(reopening, index):
    payload, version = replacement(reopening), reopening.initiative.version
    adopt(reopening, reopen(reopening, payload=payload, version=version))
    ProjectMember.objects.filter(project=reopening.project, member=reopening.reviewers[index]).update(is_active=False)
    with pytest.raises(DENIED):
        reopen(reopening, payload=payload, version=version)
    assert ScopeReopening.objects.count() == 1


@pytest.mark.parametrize("index", [0, 1, 2])
def test_every_current_gate_reviewer_needs_native_selected_member_access(reopening, index):
    ProjectMember.objects.filter(project=reopening.project, member=reopening.reviewers[index]).update(is_active=False)
    with pytest.raises(DENIED):
        reopen(reopening)
    no_reopening(reopening)


def test_only_current_product_approver_with_exact_new_action_acl_can_reopen(reopening):
    calls = []

    def deny_new_action(**kwargs):
        calls.append(kwargs["action"])
        value = resolver(**kwargs)
        if kwargs["action"] == ACTION:
            value["object_acl"]["deny_principals"] = [kwargs["actor"]]
        return value

    reopening.runtime.resolve_acl = deny_new_action
    with pytest.raises(DENIED):
        reopen(reopening)
    assert calls and set(calls) == {ACTION}
    no_reopening(reopening)
    reopening.runtime.resolve_acl = resolver
    raw_gate(reopening.gates[0], valid_until=timezone.now() - timedelta(seconds=1))
    with pytest.raises(DENIED):
        reopen(reopening)  # Actor is still creator and workspace administrator.
    no_reopening(reopening)


@pytest.mark.parametrize("substitute", ["workspace_admin", "creator", "project_lead"])
def test_administrator_creator_and_project_lead_are_not_product_approver_substitutes(reopening, substitute):
    actor = reopening.reviewers[1]
    if substitute == "workspace_admin":
        WorkspaceMember.objects.filter(workspace=reopening.workspace, member=actor).update(role=20)
    elif substitute == "project_lead":
        Project.objects.filter(id=reopening.project.id).update(project_lead_id=actor.id)
    else:
        # The original actor remains creator after their approver assignment expires.
        actor = reopening.user
        raw_gate(reopening.gates[0], valid_until=timezone.now() - timedelta(seconds=1))
    with pytest.raises(DENIED):
        reopen(reopening, request=SimpleNamespace(user=actor))
    no_reopening(reopening)


def test_standard_risk_requires_three_distinct_current_humans(reopening):
    raw_gate(reopening.gates[2], approver_user_id=reopening.reviewers[1].id)
    with pytest.raises(DENIED):
        reopen(reopening)
    no_reopening(reopening)


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
def test_native_restricted_reviewer_guest_roots_and_explicit_subitems(reopening, child, own, view_all, allowed):
    reviewer = reopening.reviewers[1]
    selected = make_issue(
        reopening, parent=reopening.issue if child else None, creator=reviewer if own else reopening.user
    )
    ProjectMember.objects.filter(project=reopening.project, member=reviewer).update(role=5)
    Project.objects.filter(id=reopening.project.id).update(guest_view_all_features=view_all)
    payload = replacement(reopening, items=[selection(reopening, selected)])
    if not allowed:
        with pytest.raises(DENIED):
            reopen(reopening, payload=payload)
        no_reopening(reopening)
    else:
        result = reopen(reopening, payload=payload)
        assert [row["source_issue_id"] for row in result.data["revision"]["items"]] == [str(selected.id)]
        assert result.data["revision"]["item_count"] == 1


@pytest.mark.parametrize("damage", ["deleted", "draft", "inaccessible"])
def test_removed_historical_members_need_integrity_but_not_current_source_access(reopening, damage):
    new_issue = make_issue(reopening, creator=reopening.reviewers[1])
    if damage == "deleted":
        Issue.all_objects.filter(id=reopening.issue.id).delete()
    elif damage == "draft":
        Issue.objects.filter(id=reopening.issue.id).update(is_draft=True)
    else:
        ProjectMember.objects.filter(project=reopening.project, member=reopening.reviewers[1]).update(role=5)
        Project.objects.filter(id=reopening.project.id).update(guest_view_all_features=False)
    result = reopen(reopening, payload=replacement(reopening, items=[selection(reopening, new_issue)]))
    assert [item["source_issue_id"] for item in result.data["revision"]["items"]] == [str(new_issue.id)]
    assert str(reopening.issue.id) not in json.dumps(result.data)
    assert ScopeProposalItem.objects.filter(source_issue_id=reopening.issue.id).count() == 1


@pytest.mark.parametrize(
    "target,change",
    [
        ("issue", {"is_draft": True}),
        ("issue", {"deleted_at": timezone.now()}),
        ("issue", {"archived_at": timezone.now().date()}),
        ("state", {"group": "triage"}),
        ("state", {"deleted_at": timezone.now()}),
        ("project", {"archived_at": timezone.now()}),
        ("project", {"deleted_at": timezone.now()}),
        ("user", {"is_active": False}),
        ("user", {"is_bot": True}),
    ],
)
def test_current_native_lifecycle_fails_closed(reopening, target, change):
    value = getattr(reopening, target)
    type(value).objects.filter(id=value.id).update(**change)
    with pytest.raises(DENIED):
        reopen(reopening)
    no_reopening(reopening)


def test_context_only_successor_never_regains_legacy_submit_compatibility(reopening, settings):
    adopt(
        reopening,
        reopen(reopening, payload=replacement(reopening, items=[selection(reopening, purpose="CONTEXT_EVIDENCE")])),
    )
    assert reopening.scope["delivery_count"] == 0
    for pending in (True, False):
        if not pending:
            submit(reopening)
        command = parse_prd_command(
            route="submit",
            body=json.dumps(
                dict(
                    external_document_binding_id=str(reopening.binding.id),
                    evidence_snapshot_id=str(uuid.uuid4()),
                    completeness_check_id=str(uuid.uuid4()),
                )
            ).encode(),
            if_match=f'"{reopening.initiative.version}"',
            idempotency_key=f"legacy-context-{pending}",
        )
        with pytest.raises(PrdCommandError):
            accept_prd_command(
                request=reopening.request,
                workspace_slug=reopening.workspace.slug,
                initiative_id=reopening.initiative.id,
                command=command,
            )


def test_pending_marker_hides_generic_and_scoped_gets_but_allows_fresh_capture(reopening, settings):
    subject, _, _ = submit(reopening)
    observation_id = ScopedPrdObservation.objects.get().id
    configure_read_runtime(reopening, settings)
    adopt(reopening, reopen(reopening))
    client = APIClient()
    client.force_authenticate(user=reopening.user)
    base = f"/api/v1/workspaces/{reopening.workspace.slug}/curve/initiatives/{reopening.initiative.id}"
    paths = [
        "/prd/review-context/",
        "/scoped-prd/v1/subjects/current",
        f"/scoped-prd/v1/subjects/{subject.id}",
        f"/scoped-prd/v1/observations/{observation_id}",
    ]
    for path in paths:
        response = client.get(base + path)
        assert response.status_code == 404, (path, response.data)
        assert response["Cache-Control"] == "no-store" and "members" not in response.data
    fresh = observe(reopening).data
    response = client.get(base + f"/scoped-prd/v1/observations/{fresh['id']}")
    assert response.status_code == 404
    scope = client.get(base + "/scope-proposal/")
    assert scope.status_code == 200 and scope.data == reopening.scope
    assert scope.data["schema_version"] == "2.0" and "prd_authority" not in scope.data


@pytest.mark.parametrize(
    "headers,status",
    [
        ({}, 428),
        ({"HTTP_IF_MATCH": 'W/"3"', "HTTP_IDEMPOTENCY_KEY": "k"}, 412),
        ({"HTTP_IF_MATCH": '"3"'}, 422),
    ],
)
def test_http_requires_numeric_strong_version_and_idempotency(reopening, headers, status):
    response = post(reopening, headers=headers)
    assert response.status_code == status and response["Cache-Control"] == "no-store"
    no_reopening(reopening)


def test_http_closed_201_and_exact_replay(reopening):
    first = post(reopening)
    assert first.status_code == 201, first.data
    assert first["ETag"] == f'"{first.data["initiative_version"]}"'
    assert first["Cache-Control"] == "no-store"
    replay = post(reopening)
    assert replay.status_code == 201 and replay.data == first.data


@pytest.mark.parametrize(
    "setting,value",
    [
        ("CURVE_SCOPE_REOPENING_ENABLED", False),
        ("CURVE_SCOPE_REOPENING_ENABLED", "true"),
        ("CURVE_SCOPE_PROPOSALS_ENABLED", False),
        ("CURVE_SCOPED_PRD_COMMANDS_ENABLED", False),
        ("CURVE_PRD_COMMANDS_ENABLED", False),
        ("CURVE_ENABLED", False),
        ("CURVE_ENVIRONMENT", "STAGING"),
        ("CURVE_ENVIRONMENT", "PRODUCTION"),
    ],
)
def test_all_feature_and_local_environment_gates_fail_closed(reopening, settings, setting, value):
    setattr(settings, setting, value)
    response = post(reopening)
    assert response.status_code == 404
    no_reopening(reopening)


@pytest.mark.parametrize("change", ["acl", "reviewer", "assignment", "source"])
def test_final_acl_callback_cannot_commit_revoked_authority_or_source(reopening, change):
    calls = []

    def resolve(**kwargs):
        calls.append(kwargs["action"])
        value = resolver(**kwargs)
        if len(calls) >= 2:
            if change == "acl":
                value["object_acl"]["deny_principals"] = [kwargs["actor"]]
            elif change == "reviewer":
                ProjectMember.objects.filter(project=reopening.project, member=reopening.reviewers[2]).update(
                    is_active=False
                )
            elif change == "assignment":
                raw_gate(reopening.gates[2], valid_until=timezone.now() - timedelta(seconds=1))
            else:
                Issue.objects.filter(id=reopening.issue.id).update(is_draft=True)
        return value

    reopening.runtime.resolve_acl = resolve
    with pytest.raises(DENIED):
        reopen(reopening)
    assert len(calls) >= 2 and set(calls) == {ACTION}
    no_reopening(reopening)
    # Callback mutations are in the failed effect transaction too.
    assert ProjectMember.objects.get(project=reopening.project, member=reopening.reviewers[2]).is_active
    assert not Issue.objects.get(id=reopening.issue.id).is_draft


def test_moved_source_and_stale_association_version_are_rejected(reopening):
    selected = replacement(reopening)
    selected["items"][0]["association_version"] = 2
    with pytest.raises(DENIED):
        reopen(reopening, payload=selected)
    other = Project.objects.create(workspace=reopening.workspace, name="Moved", identifier="MOVE")
    Issue.objects.filter(id=reopening.issue.id).update(project=other)
    with pytest.raises(DENIED):
        reopen(reopening)
    no_reopening(reopening)


@pytest.mark.parametrize("risk,allowed", [("LOW", True), ("STANDARD", False), ("HIGH", False)])
def test_overlap_uses_existing_explicit_low_risk_rule(reopening, risk, allowed):
    from plane.curve.tests.test_prd_lifecycle_repository import raw_update

    raw_update(reopening.initiative.id, risk_tier=risk)
    raw_gate(reopening.gates[2], approver_user_id=reopening.reviewers[1].id)
    if allowed:
        assert reopen(reopening).response_status == 201
    else:
        with pytest.raises(DENIED):
            reopen(reopening)
        no_reopening(reopening)


def test_preparse_limit_is_bounded_without_trusting_content_length(reopening):
    from io import BytesIO
    from plane.middleware.request_body_size import RequestBodySizeLimitMiddleware

    for length in (None, "0", "2", "999999999"):
        calls = []
        stream = BytesIO(b"x" * 100000)

        def read(size):
            calls.append(size)
            return stream.read(size)

        request = SimpleNamespace(
            path_info=f"/api/v1/workspaces/{reopening.workspace.slug}/curve/initiatives/{reopening.initiative.id}"
            "/scope-reopening/v1/reopen-and-replace/",
            read=read,
            META={} if length is None else {"CONTENT_LENGTH": length},
        )
        response = RequestBodySizeLimitMiddleware(lambda _: pytest.fail("Oversized command reached downstream"))(
            request
        )
        assert response.status_code == 413 and calls == [65537]
        assert response["Cache-Control"] == "no-store"


def test_context_only_successor_also_blocks_legacy_approval(reopening):
    adopt(
        reopening,
        reopen(reopening, payload=replacement(reopening, items=[selection(reopening, purpose="CONTEXT_EVIDENCE")])),
    )
    subject, _, _ = submit(reopening)
    record = subject.as_record()
    payload = {
        key: record[key]
        for key in (
            "checkpoint_id",
            "artifact_version_id",
            "content_digest",
            "provider_version",
            "evidence_snapshot_id",
        )
    }
    payload.update(
        gate_assignment_id=str(reopening.gates[0].id),
        confirmed_risk_tier=reopening.initiative.risk_tier,
        rationale="Synthetic sensitive rationale sentinel",
    )
    command = parse_prd_command(
        route="approve",
        body=json.dumps(payload).encode(),
        if_match=f'"{reopening.initiative.version}"',
        idempotency_key="legacy-context-approval",
    )
    with pytest.raises(PrdCommandError):
        accept_prd_command(
            request=reopening.request,
            workspace_slug=reopening.workspace.slug,
            initiative_id=reopening.initiative.id,
            command=command,
        )
    reopening.initiative.refresh_from_db()
    assert reopening.initiative.state == "PRD_REVIEW" and reopening.initiative.controlling_prd_decision_id is None


def test_session_csrf_is_required_at_new_endpoint(reopening):
    from rest_framework.test import APIRequestFactory
    from plane.curve.scope_reopening_views import CurveScopeReopeningEndpoint

    request = APIRequestFactory(enforce_csrf_checks=True).post(
        "/synthetic-reopening",
        data=json.dumps(replacement(reopening)),
        content_type="application/json",
        HTTP_IF_MATCH=f'"{reopening.initiative.version}"',
        HTTP_IDEMPOTENCY_KEY="csrf-reopening",
    )
    request.user = reopening.user
    response = CurveScopeReopeningEndpoint.as_view()(
        request, slug=reopening.workspace.slug, initiative_id=reopening.initiative.id
    )
    response.render()
    assert response.status_code == 403 and response.data["code"] == "FORBIDDEN"
    assert response["Cache-Control"] == "no-store"
    no_reopening(reopening)


@pytest.mark.parametrize("state", ["PRD_REVIEW", "PLANNING"])
def test_historical_success_is_not_available_as_current_success_while_pending(reopening, state):
    _, command, operation = stage(reopening, state)
    previous = Operation.objects.filter(id=operation.id).values().get()
    adopt(reopening, reopen(reopening))
    with pytest.raises(DENIED):
        accept(reopening, command)
    with pytest.raises((PrdCommandError, PrdCompletionUnavailable)):
        complete(reopening, operation)
    assert Operation.objects.filter(id=operation.id).values().get() == previous


def assert_one_reopening_denial(bridge):
    decisions = PolicyDecision.objects.filter(policy_key="CURVE_SCOPE_REOPENING_POLICY")
    assert decisions.count() == 1
    decision = decisions.get()
    assert decision.effect == "DENY" and decision.permitted_projection == []
    assert decision.action == ACTION
    principal = dict(actor_type="HUMAN", actor_id=str(bridge.user.id))
    assert decision.subject == decision.effective_principal == principal
    audit = AuditEvent.objects.get(policy_decision_ref__resource_id=str(decision.id))
    assert audit.outcome == "DENIED" and audit.effective_principal == principal
    return decision


def test_inaccessible_selected_item_records_deny_instead_of_allowed_no_effect(reopening):
    ProjectMember.objects.filter(project=reopening.project, member=reopening.reviewers[1]).update(is_active=False)
    with pytest.raises(DENIED):
        reopen(reopening)
    assert_one_reopening_denial(reopening)
    no_reopening(reopening)


def test_audit_callback_permission_loss_rolls_back_allow_and_records_one_final_deny(reopening, monkeypatch):
    import plane.curve.scope_reopening_services as services

    append = services._append_audit_event
    calls = []

    def revoke(**kwargs):
        value = append(**kwargs)
        if kwargs["action"] == ACTION and kwargs["outcome"] == "SUCCEEDED":
            calls.append(kwargs["outcome"])
            Issue.objects.filter(id=reopening.issue.id).update(is_draft=True)
        return value

    monkeypatch.setattr(services, "_append_audit_event", revoke)
    with pytest.raises(DENIED):
        reopen(reopening)
    assert calls == ["SUCCEEDED"]
    assert_one_reopening_denial(reopening)
    no_reopening(reopening)
    assert not Issue.objects.get(id=reopening.issue.id).is_draft


def test_stale_business_version_preserves_allowed_no_effect_classification(reopening):
    with pytest.raises(DENIED):
        reopen(reopening, version=reopening.initiative.version + 1)
    decision = PolicyDecision.objects.get(policy_key="CURVE_SCOPE_REOPENING_POLICY")
    assert decision.effect == "ALLOW"
    audit = AuditEvent.objects.get(policy_decision_ref__resource_id=str(decision.id))
    assert audit.outcome == "NO_EFFECT"
    no_reopening(reopening)


def test_policy_input_digest_binds_native_source_fence(reopening, monkeypatch):
    from plane.db.models import State

    fixed = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: fixed)
    digests = []
    for changed in (False, False, True):
        if changed:
            State.objects.filter(id=reopening.state.id).update(group="started")
        with pytest.raises(DENIED):
            reopen(reopening, version=reopening.initiative.version + 1)
        decision = PolicyDecision.objects.filter(policy_key="CURVE_SCOPE_REOPENING_POLICY").order_by("sequence").last()
        assert decision.effect == "ALLOW"
        digests.append(decision.input_digest)
    assert digests[0] == digests[1]
    assert digests[1] != digests[2]
    assert AuditEvent.objects.filter(action=ACTION).count() == 3
    no_reopening(reopening)


def existing_lifecycle_command(bridge, command):
    from plane.curve import initiative_services

    result = getattr(initiative_services, f"{command}_initiative")(
        request=bridge.request,
        workspace_slug=bridge.workspace.slug,
        initiative_id=bridge.initiative.id,
        expected_version=bridge.initiative.version,
        raw_idempotency_key=f"pending-reopening-{command}",
        payload={"reason": "Synthetic existing lifecycle transition"},
    )
    bridge.initiative.refresh_from_db()
    return result


def test_pending_reopening_preserves_existing_pause_resume_with_marker(reopening):
    result = adopt(reopening, reopen(reopening))
    marker = uuid.UUID(result.data["id"])
    version = reopening.initiative.version
    existing_lifecycle_command(reopening, "pause")
    assert reopening.initiative.state == "PAUSED" and reopening.initiative.paused_from_state == "ALIGNING"
    assert reopening.initiative.version == version + 1
    assert reopening.initiative.pending_scope_reopening_id == marker
    assert reopening.initiative.controlling_prd_decision_id is None
    with pytest.raises(DENIED):
        reopen(reopening, key="cannot-reopen-paused")
    existing_lifecycle_command(reopening, "resume")
    assert reopening.initiative.state == "ALIGNING" and reopening.initiative.paused_from_state is None
    assert reopening.initiative.version == version + 2
    assert reopening.initiative.pending_scope_reopening_id == marker
    assert reopening.initiative.controlling_prd_decision_id is None
    submit(reopening)
    assert reopening.initiative.pending_scope_reopening_id is None and reopening.initiative.state == "PRD_REVIEW"


@pytest.mark.parametrize("paused", [False, True])
def test_pending_reopening_preserves_existing_cancellation_without_restoring_authority(reopening, paused):
    result = adopt(reopening, reopen(reopening))
    marker = uuid.UUID(result.data["id"])
    if paused:
        existing_lifecycle_command(reopening, "pause")
    version = reopening.initiative.version
    existing_lifecycle_command(reopening, "cancel")
    assert reopening.initiative.state == "CANCELLED" and reopening.initiative.paused_from_state is None
    assert reopening.initiative.version == version + 1
    assert reopening.initiative.pending_scope_reopening_id == marker
    assert reopening.initiative.controlling_prd_decision_id is None
    with pytest.raises(DENIED):
        reopen(reopening, key="cannot-reopen-cancelled")
