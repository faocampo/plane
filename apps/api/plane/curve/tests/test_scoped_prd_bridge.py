# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Real migrated PostgreSQL C1 -> exact Gate 1, synthetic protected runtime only."""

from datetime import timedelta
from types import SimpleNamespace
import json
import uuid

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from plane.db.models import User, WorkspaceMember, ProjectMember, Issue, State
from plane.curve.models import (
    Initiative,
    GateAssignment,
    ProjectAssociation,
    ProviderConnection,
    ExternalDocumentBinding,
    PrdArtifact,
    DocumentCheckpoint,
    PrdReviewDecision,
    Operation,
)
from plane.curve.initiative_services import accept_initiative_refinement
from plane.curve.scope_proposal_services import replace_scope_proposal
from plane.curve.scope_proposal_models import ScopeProposalRevision
from plane.curve.prd_commands import PrdCommandError, parse_prd_command
from plane.curve.prd_acceptance import accept_prd_command
from plane.curve.prd_completion import PrdCompletionUnavailable
from plane.curve.scoped_prd_commands import parse_scoped_prd_command
from plane.curve.scoped_prd_contracts import SCHEMA_VERSION, POLICY_EDITION
from plane.curve.scoped_prd_observations import capture_scoped_prd_observation
from plane.curve.scoped_prd_acceptance import accept_scoped_prd_command
from plane.curve.scoped_prd_completion import complete_scoped_prd_operation
from plane.curve.scoped_prd_models import (
    ScopedPrdObservation,
    ScopedPrdAcceptedCommand,
    ScopedPrdReadiness,
    ScopedPrdSubject,
    ScopedPrdDecision,
)
from plane.curve.tests.test_project_association_api import context, configuration, create  # noqa: F401
from plane.curve.tests.test_prd_checkpoint_models import capture_records
from plane.curve.tests.test_prd_completion import SyntheticCompletionRuntime
from plane.curve.tests.test_provider_models import connection_values
from plane.curve.tests.test_prd_policy_context import resolver

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def bridge(context, settings):  # noqa: F811
    settings.CURVE_SCOPE_PROPOSALS_ENABLED = True
    settings.CURVE_SCOPED_PRD_COMMANDS_ENABLED = True
    settings.CURVE_PRD_COMMANDS_ENABLED = True
    response = create(context)
    assert response.status_code == 201, response.content
    context.association = ProjectAssociation.objects.get(id=response.json()["id"])
    actor = dict(actor_type="HUMAN", actor_id=str(context.user.id))
    context.initiative = Initiative.objects.create(
        workspace_id=context.workspace.id,
        product_id=context.product.id,
        mode="STANDALONE",
        keyword="scoped",
        title="Exact remaining outcome",
        description={},
        risk_tier="STANDARD",
        business_intent="BUSINESS_IMPROVEMENT",
        creator_user_id=context.user.id,
        created_by=actor,
        updated_by=actor,
    )
    context.reviewers = [context.user]
    for index in range(2):
        user = User.objects.create(
            email=f"scoped-reviewer-{index}@example.invalid", username=f"scoped-reviewer-{index}"
        )
        WorkspaceMember.objects.create(workspace=context.workspace, member=user, is_active=True, role=15)
        ProjectMember.objects.create(
            workspace=context.workspace, project=context.project, member=user, is_active=True, role=15
        )
        context.reviewers.append(user)
    context.gates = [
        GateAssignment.objects.create(
            workspace_id=context.workspace.id,
            initiative=context.initiative,
            gate_type=kind,
            approver_user_id=user.id,
            valid_from=timezone.now() - timedelta(days=1),
        )
        for kind, user in zip(("PRD_APPROVAL", "PLAN_APPROVAL", "CODE_READINESS"), context.reviewers)
    ]
    context.state = State.objects.create(
        workspace=context.workspace, project=context.project, name="Ready", color="#000000", group="unstarted"
    )
    context.issue = Issue.objects.create(
        workspace=context.workspace,
        project=context.project,
        state=context.state,
        name="DO NOT COPY BODY",
        description_html="<p>Private native acceptance</p>",
        created_by=context.user,
    )
    ProjectMember.objects.filter(id=context.project_membership.id).update(role=15)
    Issue.objects.filter(id=context.issue.id).update(created_by_id=context.user.id)
    context.issue.refresh_from_db()
    context.request = SimpleNamespace(user=context.user)
    selected = replace_scope_proposal(
        request=context.request,
        workspace_slug=context.workspace.slug,
        initiative_id=context.initiative.id,
        expected_version=1,
        raw_idempotency_key="initial-scope",
        payload=dict(
            expected_scope_revision=0,
            items=[
                dict(
                    association_id=str(context.association.id),
                    association_version=1,
                    source_issue_id=str(context.issue.id),
                    purpose="PROPOSED_DELIVERY",
                )
            ],
        ),
    )
    context.scope = selected.data
    accept_initiative_refinement(
        request=context.request,
        workspace_slug=context.workspace.slug,
        initiative_id=context.initiative.id,
        expected_version=2,
        raw_idempotency_key="refinement",
    )
    context.initiative.refresh_from_db()
    provider = ProviderConnection.objects.create(**connection_values(context.workspace.id))
    context.binding = ExternalDocumentBinding.objects.create(
        workspace_id=context.workspace.id,
        initiative=context.initiative,
        provider_connection=provider,
        provider_file_id="synthetic-document",
        provider_container_id="synthetic-container",
        canonical_url="https://docs.example.invalid/documents/synthetic-document",
        current_provider_version="source-v1",
        current_modified_at=timezone.now(),
        created_by=actor,
    )
    context.artifact = PrdArtifact.objects.create(workspace_id=context.workspace.id, initiative=context.initiative)
    context.runtime = SyntheticCompletionRuntime(
        (context.binding, context.initiative, None, context.gates[0], context.user, context.workspace)
    )
    settings.CURVE_PRD_ACCEPTANCE_RUNTIME = settings.CURVE_PRD_COMPLETION_RUNTIME = context.runtime
    return context


def cmd(bridge, route, payload, *, key=None, version=None):
    return parse_scoped_prd_command(
        route=route,
        body=json.dumps(dict(schema_version=SCHEMA_VERSION, policy_edition=POLICY_EDITION, **payload)).encode(),
        if_match=f'"{version or bridge.initiative.version}"',
        idempotency_key=key or str(uuid.uuid4()),
    )


def pins(bridge):
    return dict(
        proposal_id=bridge.scope["proposal_id"],
        scope_revision_id=bridge.scope["id"],
        scope_revision=bridge.scope["version"],
        membership_digest=bridge.scope["membership_digest"],
    )


def observe(bridge, key=None):
    command = cmd(bridge, "observe", pins(bridge), key=key)
    return capture_scoped_prd_observation(
        request=bridge.request,
        workspace_slug=bridge.workspace.slug,
        initiative_id=bridge.initiative.id,
        command=command,
    )


def accept(bridge, command):
    return accept_scoped_prd_command(
        request=bridge.request,
        workspace_slug=bridge.workspace.slug,
        initiative_id=bridge.initiative.id,
        command=command,
    )


def complete(bridge, operation):
    return complete_scoped_prd_operation(workspace_id=bridge.workspace.id, operation_id=operation.id)


def submission(bridge, observation=None):
    observation = observation or observe(bridge).data
    bridge.artifact.refresh_from_db()
    capture = capture_records(bridge.binding, bridge.artifact, bridge.initiative.current_prd_checkpoint_id)
    capture[1].created_by = capture[2].submitted_or_approved_by = dict(actor_type="HUMAN", actor_id=str(bridge.user.id))
    bridge.runtime.capture = capture
    return cmd(
        bridge,
        "submit",
        dict(
            external_document_binding_id=str(bridge.binding.id),
            evidence_snapshot_id=str(capture[0].id),
            completeness_check_id=str(capture[2].completeness_check_id),
            **pins(bridge),
            observation_set_id=observation["id"],
            observation_digest=observation["digest"],
        ),
    )


def submit(bridge):
    command = submission(bridge)
    operation = accept(bridge, command).operation
    result = complete(bridge, operation)
    assert result["status"] == "SUCCEEDED" and result["effect_applied"], result
    bridge.initiative.refresh_from_db()
    checkpoint = DocumentCheckpoint.objects.get(id=bridge.initiative.current_prd_checkpoint_id)
    bridge.runtime.capture = None
    bridge.runtime.records = (
        bridge.binding,
        bridge.initiative,
        checkpoint,
        bridge.gates[0],
        bridge.user,
        bridge.workspace,
    )
    return ScopedPrdSubject.objects.get(checkpoint_id=checkpoint.id), command, operation


def review_command(bridge, subject, route="approve"):
    p = subject.as_record()
    payload = {
        key: p[key]
        for key in (
            "checkpoint_id",
            "artifact_version_id",
            "content_digest",
            "provider_version",
            "evidence_snapshot_id",
        )
    }
    payload.update(
        gate_assignment_id=str(bridge.gates[0].id),
        confirmed_risk_tier=bridge.initiative.risk_tier,
        scoped_subject_id=str(subject.id),
        scoped_subject_digest=subject.digest,
        rationale="Synthetic sensitive rationale sentinel",
    )
    if route != "approve":
        payload["decision"] = "CHANGES_REQUESTED"
    return cmd(bridge, route, payload)


def test_exact_observation_submission_and_gate_one_have_zero_control(bridge):
    subject, command, operation = submit(bridge)
    assert ScopedPrdReadiness.objects.count() == ScopedPrdSubject.objects.count() == 1
    assert "curve_work_item_binding" not in connection.introspection.table_names()
    assert complete(bridge, operation)["effect_applied"] is False
    approved = accept(bridge, review_command(bridge, subject)).operation
    assert complete(bridge, approved)["status"] == "SUCCEEDED"
    bridge.initiative.refresh_from_db()
    assert bridge.initiative.state == "PLANNING"
    assert PrdReviewDecision.objects.count() == ScopedPrdDecision.objects.count() == 1
    assert "curve_work_item_binding" not in connection.introspection.table_names()
    assert ScopeProposalRevision.objects.count() == 1
    assert "DO NOT COPY" not in json.dumps(subject.as_record())


def test_observation_replay_and_changed_metadata_requires_refresh(bridge):
    original = observe(bridge, "same-observe")
    assert observe(bridge, "same-observe").data == original.data
    Issue.objects.filter(id=bridge.issue.id).update(updated_at=timezone.now())
    with pytest.raises(PrdCommandError, match="SCOPED_PRD_SUBJECT_CHANGED"):
        observe(bridge, "same-observe")
    refreshed = observe(bridge).data
    assert refreshed["id"] != original.data["id"] and refreshed["digest"] != original.data["digest"]
    assert refreshed["membership_digest"] == original.data["membership_digest"]
    assert ScopeProposalRevision.objects.count() == 1
    operation = accept(bridge, submission(bridge, refreshed)).operation
    assert complete(bridge, operation)["status"] == "SUCCEEDED"


@pytest.mark.parametrize("index", [0, 1, 2])
def test_each_current_reviewer_needs_native_membership_before_prepare(bridge, index):
    command = submission(bridge)
    ProjectMember.objects.filter(project=bridge.project, member=bridge.reviewers[index]).update(is_active=False)
    with pytest.raises(PrdCommandError):
        accept(bridge, command)
    assert bridge.runtime.calls == 0 and not ScopedPrdAcceptedCommand.objects.exists()


@pytest.mark.parametrize("stage", ["prepare", "revalidate"])
def test_source_revocation_during_acceptance_rolls_back(bridge, stage):
    command = submission(bridge)

    def revoke(*args):
        ProjectMember.objects.filter(project=bridge.project, member=bridge.reviewers[1]).update(is_active=False)
        return True

    if stage == "prepare":
        bridge.runtime.on_prepare = revoke
    else:
        bridge.runtime.on_revalidate = revoke
    with pytest.raises(PrdCommandError):
        accept(bridge, command)
    assert not ScopedPrdAcceptedCommand.objects.exists() and not Operation.objects.exists()


@pytest.mark.parametrize("stage", ["acceptance", "completion"])
def test_runtime_acl_revocation_cannot_commit(bridge, stage):
    command = submission(bridge)

    def deny(**kwargs):
        value = resolver(**kwargs)
        value["object_acl"]["deny_principals"] = [kwargs["actor"]]
        return value

    def revoke(*args):
        bridge.runtime.resolve_acl = deny
        return True

    if stage == "acceptance":
        bridge.runtime.on_revalidate = revoke
        with pytest.raises(PrdCommandError):
            accept(bridge, command)
        assert not Operation.objects.exists()
    else:
        operation = accept(bridge, command).operation
        bridge.runtime.local_hook = revoke
        assert complete(bridge, operation)["status"] == "FAILED"
        assert not ScopedPrdSubject.objects.exists() and not DocumentCheckpoint.objects.exists()


def test_previous_success_replay_after_revocation_does_not_escape_worker_fallback(bridge):
    subject, command, operation = submit(bridge)
    ProjectMember.objects.filter(project=bridge.project, member=bridge.reviewers[2]).update(is_active=False)
    with pytest.raises(PrdCommandError):
        accept(bridge, command)
    with pytest.raises((PrdCommandError, PrdCompletionUnavailable)):
        complete(bridge, operation)
    operation.refresh_from_db()
    assert operation.status == "SUCCEEDED" and ScopedPrdSubject.objects.get(id=subject.id).digest == subject.digest


def test_previous_success_acl_replay_cannot_be_laundered(bridge):
    _, _, operation = submit(bridge)

    def deny(**kwargs):
        value = resolver(**kwargs)
        value["object_acl"]["deny_principals"] = [kwargs["actor"]]
        return value

    bridge.runtime.resolve_acl = deny
    with pytest.raises(PrdCompletionUnavailable):
        complete(bridge, operation)
    operation.refresh_from_db()
    assert operation.status == "SUCCEEDED"


@pytest.mark.parametrize("field", ["observation_digest", "membership_digest", "scope_revision_id"])
def test_submission_exact_refs_cannot_be_substituted(bridge, field):
    command = submission(bridge)
    payload = command.subject_metadata()
    payload[field] = str(uuid.uuid4()) if field.endswith("_id") else "sha256:" + "0" * 64
    altered = parse_scoped_prd_command(
        route="submit",
        body=json.dumps(payload).encode(),
        if_match=f'"{bridge.initiative.version}"',
        idempotency_key=str(uuid.uuid4()),
    )
    with pytest.raises(PrdCommandError):
        accept(bridge, altered)
    assert not Operation.objects.exists()


def test_completion_rechecks_metadata_and_settles_without_checkpoint(bridge):
    operation = accept(bridge, submission(bridge)).operation
    bridge.runtime.hook = lambda *_: Issue.objects.filter(id=bridge.issue.id).update(updated_at=timezone.now())
    assert complete(bridge, operation)["status"] == "FAILED"
    assert not DocumentCheckpoint.objects.exists() and not ScopedPrdReadiness.objects.exists()
    assert not ScopedPrdSubject.objects.exists()


def test_return_for_revision_preserves_frozen_membership(bridge):
    subject, _, _ = submit(bridge)
    operation = accept(bridge, review_command(bridge, subject, "return-for-revision")).operation
    assert complete(bridge, operation)["status"] == "SUCCEEDED"
    bridge.initiative.refresh_from_db()
    assert bridge.initiative.state == "ALIGNING"
    assert ScopeProposalRevision.objects.count() == 1
    assert ScopedPrdSubject.objects.get(id=subject.id).digest == subject.digest


def test_legacy_submit_is_still_blocked_when_scoped_subject_exists(bridge, settings):
    submit(bridge)
    settings.CURVE_SCOPE_PROPOSALS_ENABLED = settings.CURVE_SCOPED_PRD_COMMANDS_ENABLED = False
    command = parse_prd_command(
        route="submit",
        body=json.dumps(
            dict(
                external_document_binding_id=str(bridge.binding.id),
                evidence_snapshot_id=str(uuid.uuid4()),
                completeness_check_id=str(uuid.uuid4()),
            )
        ).encode(),
        if_match=f'"{bridge.initiative.version}"',
        idempotency_key="legacy",
    )
    with pytest.raises(PrdCommandError, match="PRD_SCOPE_BRIDGE_UNAVAILABLE"):
        accept_prd_command(
            request=bridge.request,
            workspace_slug=bridge.workspace.slug,
            initiative_id=bridge.initiative.id,
            command=command,
        )


def test_observation_database_is_immutable_and_cross_tenant_references_fail(bridge):
    original = observe(bridge).data
    for change in ("digest = 'sha256:" + "0" * 64 + "'", "workspace_id = '" + str(uuid.uuid4()) + "'"):
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f"UPDATE curve_scoped_prd_observation SET {change} WHERE id=%s", [original["id"]])
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM curve_scoped_prd_observation WHERE id=%s", [original["id"]])
    assert ScopedPrdObservation.objects.get(id=original["id"]).as_record() == original


@pytest.mark.parametrize("mutation", ["digest", "extra", "duplicate", "edition"])
def test_direct_service_cannot_skip_closed_command_parser(bridge, mutation):
    from dataclasses import replace

    command = submission(bridge)
    if mutation == "digest":
        command = replace(command, request_digest="sha256:" + "0" * 64)
    elif mutation == "extra":
        command = replace(command, subject=tuple(sorted((*command.subject, ("unknown", "untrusted")))))
    elif mutation == "duplicate":
        command = replace(command, subject=(*command.subject, command.subject[0]))
    else:
        command = replace(
            command,
            subject=tuple((key, "unsupported" if key == "schema_version" else value) for key, value in command.subject),
        )
    with pytest.raises(PrdCommandError):
        accept(bridge, command)
    assert not Operation.objects.exists()


def test_post_draft_selection_replacement_cannot_race_submission(bridge):
    from plane.curve.scope_proposal_services import ScopeCommandError

    operation = accept(bridge, submission(bridge)).operation
    before = ScopeProposalRevision.objects.count()

    def replace_after_prepare(*_):
        with pytest.raises(ScopeCommandError, match="SCOPE_PROPOSAL_STATE_CONFLICT"):
            replace_scope_proposal(
                request=bridge.request,
                workspace_slug=bridge.workspace.slug,
                initiative_id=bridge.initiative.id,
                expected_version=bridge.initiative.version,
                raw_idempotency_key="forbidden-reopen",
                payload=dict(expected_scope_revision=1, items=[]),
            )

    bridge.runtime.hook = replace_after_prepare
    assert complete(bridge, operation)["status"] == "SUCCEEDED"
    assert ScopeProposalRevision.objects.count() == before


def configure_read_runtime(bridge, settings):
    from pathlib import Path
    from plane.curve.models import PrdReadinessRecord
    from plane.curve.prd_metadata_validation import instant
    from plane.curve.prd_readiness import SUBJECT_FIELDS
    from plane.curve.tests.test_prd_read_context import Runtime

    checkpoint = DocumentCheckpoint.objects.get(id=bridge.initiative.current_prd_checkpoint_id)
    snapshot = json.loads((Path(__file__).parent / "fixtures/prd_review_context.json").read_text())
    snapshot.update(
        workspace_id=str(bridge.workspace.id),
        initiative_id=str(bridge.initiative.id),
        initiative_version=bridge.initiative.version,
        current_checkpoint_id=str(checkpoint.id),
        current_readiness_report_id=str(checkpoint.completeness_check_id),
        state=bridge.initiative.state,
    )
    for metadata in (snapshot["binding"]["metadata"], snapshot["checkpoint"]["metadata"]):
        metadata.update(workspace_id=str(bridge.workspace.id), initiative_id=str(bridge.initiative.id))
    snapshot["binding"]["metadata"].update(
        id=str(bridge.binding.id),
        provider_file_id=bridge.binding.provider_file_id,
        current_provider_version=checkpoint.provider_version,
        last_reconciled_at=instant(checkpoint.recorded_at),
    )
    snapshot["checkpoint"]["metadata"].update(
        id=str(checkpoint.id),
        metadata_schema_version=checkpoint.as_record()["schema_version"],
        checkpoint_number=checkpoint.checkpoint_number,
        external_document_binding_id=str(bridge.binding.id),
        provider_file_id=checkpoint.provider_file_id,
        artifact_version_id=str(checkpoint.artifact_version_id),
        evidence_snapshot_id=str(checkpoint.evidence_snapshot_id),
        provider_version=checkpoint.provider_version,
        content_digest=checkpoint.content_digest,
        recorded_at=instant(checkpoint.recorded_at),
        completeness_check_id=str(checkpoint.completeness_check_id),
    )
    report = PrdReadinessRecord.objects.get(id=checkpoint.completeness_check_id).payload
    snapshot["readiness"]["metadata"] = report
    snapshot["current_readiness_subject"] = {key: report[key] for key in SUBJECT_FIELDS}
    snapshot["current_readiness_subject"]["initiative_version"] = bridge.initiative.version
    for metadata, gate in zip(snapshot["assignments"], bridge.gates):
        metadata.update(
            id=str(gate.id),
            workspace_id=str(bridge.workspace.id),
            initiative_id=str(bridge.initiative.id),
            approver=dict(actor_type="HUMAN", actor_id=str(gate.approver_user_id)),
            valid_from=instant(gate.valid_from),
        )
    settings.CURVE_PRD_READ_ENABLED = True
    runtime = Runtime(snapshot)
    settings.CURVE_PRD_READ_RUNTIME = runtime
    return runtime


def test_http_capture_submit_and_exact_current_subject_use_real_native_guard(bridge, settings):
    from django.urls import reverse
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=bridge.user)

    def post(route, command):
        return client.post(
            reverse(
                f"curve-scoped-prd-{route}", kwargs=dict(slug=bridge.workspace.slug, initiative_id=bridge.initiative.id)
            ),
            data=json.dumps(command.subject_metadata()),
            content_type="application/json",
            HTTP_IF_MATCH=f'"{command.expected_version}"',
            HTTP_IDEMPOTENCY_KEY=command.idempotency_key,
        )

    observed = post("observe", cmd(bridge, "observe", pins(bridge)))
    assert observed.status_code == 201, observed.data
    accepted = post("submit", submission(bridge, observed.data))
    assert accepted.status_code == 202, accepted.data
    operation = Operation.objects.get(id=accepted.data["id"])
    assert complete(bridge, operation)["status"] == "SUCCEEDED"
    bridge.initiative.refresh_from_db()
    configure_read_runtime(bridge, settings)
    path = reverse(
        "curve-scoped-prd-subject-current", kwargs=dict(slug=bridge.workspace.slug, initiative_id=bridge.initiative.id)
    )
    response = client.get(path)
    assert response.status_code == 200, response.data
    subject = ScopedPrdSubject.objects.get(checkpoint_id=bridge.initiative.current_prd_checkpoint_id)
    assert response.data == subject.as_record() and response["Cache-Control"] == "no-store"
    assert (
        "Private native acceptance" not in response.content.decode() and "DO NOT COPY" not in response.content.decode()
    )
    ProjectMember.objects.filter(project=bridge.project, member=bridge.reviewers[2]).update(is_active=False)
    hidden = client.get(path)
    assert hidden.status_code == 404 and "members" not in hidden.data


def test_unavailable_http_subject_id_has_same_hidden_response(bridge, settings):
    from django.urls import reverse
    from rest_framework.test import APIClient

    subject, _, _ = submit(bridge)
    configure_read_runtime(bridge, settings)
    client = APIClient()
    client.force_authenticate(user=bridge.user)

    def get(record_id):
        return client.get(
            reverse(
                "curve-scoped-prd-subject",
                kwargs=dict(
                    slug=bridge.workspace.slug, initiative_id=bridge.initiative.id, scoped_subject_id=record_id
                ),
            )
        )

    assert get(subject.id).status_code == 200
    absent = get(uuid.uuid4())
    ProjectMember.objects.filter(project=bridge.project, member=bridge.user).update(is_active=False)
    forbidden = get(subject.id)
    assert absent.status_code == forbidden.status_code == 404 and absent.data == forbidden.data


def test_direct_observation_cannot_smuggle_rationale(bridge):
    from dataclasses import replace

    command = replace(cmd(bridge, "observe", pins(bridge)), rationale_bytes=b"unexpected protected bytes")
    with pytest.raises(PrdCommandError, match="SCOPED_PRD_INVALID"):
        capture_scoped_prd_observation(
            request=bridge.request,
            workspace_slug=bridge.workspace.slug,
            initiative_id=bridge.initiative.id,
            command=command,
        )
    assert not ScopedPrdObservation.objects.exists()


def test_direct_existing_submission_replay_cannot_smuggle_rationale(bridge):
    from dataclasses import replace

    command = submission(bridge)
    operation = accept(bridge, command).operation
    with pytest.raises(PrdCommandError, match="SCOPED_PRD_INVALID"):
        accept(bridge, replace(command, rationale_bytes=b"unexpected protected bytes"))
    assert Operation.objects.count() == ScopedPrdAcceptedCommand.objects.count() == 1
    assert accept(bridge, command).operation.id == operation.id
