# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor

from plane.curve.models import DocumentCheckpoint, GateAssignment, Initiative, PrdReviewDecision
from plane.curve.prd_lifecycle_repository import record_prd_submission_transition, record_prd_decision_transition
from plane.curve.tests.test_prd_checkpoint_models import capture_fixture, capture_records
from plane.curve.tests.test_prd_metadata_models import AT
from plane.curve.tests.test_prd_review_models import decision_for


pytestmark = [pytest.mark.unit, pytest.mark.django_db]


def raw_update(initiative_id, **changes):
    columns = ", ".join(f"{connection.ops.quote_name(key)} = %s" for key in changes)
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE curve_initiative SET {columns} WHERE id = %s", [*changes.values(), initiative_id])


def submit(binding, artifact, initiative):
    records = capture_records(binding, artifact, initiative.current_prd_checkpoint_id)
    snapshot, version, checkpoint = records
    with transaction.atomic():
        result = record_prd_submission_transition(
            workspace_id=initiative.workspace_id,
            initiative_id=initiative.id,
            expected_version=initiative.version,
            expected_checkpoint_id=initiative.current_prd_checkpoint_id,
            actor=checkpoint.submitted_or_approved_by,
            artifact_id=artifact.id,
            expected_parent_version_id=version.parent_version_id,
            snapshot=snapshot,
            version=version,
            checkpoint=checkpoint,
        )
    artifact.refresh_from_db()
    return result, checkpoint


def review_fixture():
    binding, artifact = capture_fixture()
    initiative, checkpoint = submit(binding, artifact, binding.initiative)
    assignments = [
        GateAssignment.objects.create(
            workspace_id=initiative.workspace_id,
            initiative=initiative,
            gate_type=kind,
            approver_user_id=uuid.uuid4(),
            valid_from=AT,
        )
        for kind in ["PRD_APPROVAL", "PLAN_APPROVAL", "CODE_READINESS"]
    ]
    return binding, artifact, initiative, checkpoint, assignments[0]


def decide(initiative, checkpoint, assignment, state="APPROVED", **overrides):
    decision = decision_for(checkpoint, assignment, state=state)
    arguments = dict(
        workspace_id=initiative.workspace_id,
        initiative_id=initiative.id,
        expected_version=initiative.version,
        expected_checkpoint_id=checkpoint.id,
        actor=decision.decided_by,
        decision=decision,
    )
    arguments.update(overrides)
    with transaction.atomic():
        result = record_prd_decision_transition(**arguments)
    return result, decision


@pytest.mark.parametrize(
    "outcome,state",
    [
        ("APPROVED", "PLANNING"),
        ("CHANGES_REQUESTED", "ALIGNING"),
        ("REJECTED", "ALIGNING"),
    ],
)
def test_submission_and_human_review_advance_exact_aggregate(outcome, state):
    _, _, initiative, checkpoint, assignment = review_fixture()
    assert initiative.state == "PRD_REVIEW" and initiative.version == 2
    assert initiative.current_prd_checkpoint_id == checkpoint.id
    assert initiative.controlling_prd_decision_id is None
    result, decision = decide(initiative, checkpoint, assignment, outcome)
    result.refresh_from_db()
    assert result.state == state and result.version == 3
    assert result.current_prd_checkpoint_id == checkpoint.id
    assert result.controlling_prd_decision_id == decision.id
    assert result.updated_by == decision.decided_by


@pytest.mark.parametrize("state", ["PRD_REVIEW", "PLANNING"])
def test_raw_state_cannot_advance_without_checkpoint(state):
    binding, _ = capture_fixture()
    with pytest.raises(DatabaseError), transaction.atomic():
        raw_update(binding.initiative_id, state=state)


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_version": 1},
        {"expected_version": True},
        {"expected_checkpoint_id": uuid.UUID(int=1)},
        {"workspace_id": uuid.UUID(int=2)},
        {"actor": {"actor_type": "SERVICE", "actor_id": "synthetic"}},
    ],
)
def test_stale_scope_version_subject_or_actor_has_no_decision_effect(overrides):
    _, _, initiative, checkpoint, assignment = review_fixture()
    with pytest.raises(ValidationError):
        decide(initiative, checkpoint, assignment, **overrides)
    initiative.refresh_from_db()
    assert initiative.state == "PRD_REVIEW" and initiative.version == 2
    assert PrdReviewDecision.objects.count() == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "PLANNING"},
        {"state": "ALIGNING"},
        {"state": "DRAFT", "workflow_version_id": None},
        {"current_prd_checkpoint_id": None},
        {"paused_from_state": "PLANNING", "state": "PAUSED"},
    ],
)
def test_raw_update_cannot_bypass_prd_lifecycle(changes):
    _, _, initiative, _, _ = review_fixture()
    with pytest.raises(DatabaseError), transaction.atomic():
        raw_update(initiative.id, version=3, **changes)


@pytest.mark.parametrize("field", ["current_prd_checkpoint_id", "controlling_prd_decision_id"])
def test_foreign_checkpoint_and_decision_cannot_control_initiative(field):
    _, _, initiative, _, _ = review_fixture()
    _, _, foreign_init, foreign_checkpoint, foreign_assignment = review_fixture()
    _, foreign_decision = decide(foreign_init, foreign_checkpoint, foreign_assignment)
    foreign = foreign_checkpoint if field == "current_prd_checkpoint_id" else foreign_decision
    with pytest.raises(DatabaseError), transaction.atomic():
        raw_update(initiative.id, version=3, **{field: foreign.id})


def test_negative_review_and_unchanged_successor_preserve_history_then_allow_planning():
    binding, artifact, initiative, checkpoint, assignment = review_fixture()
    returned, first = decide(initiative, checkpoint, assignment, "CHANGES_REQUESTED")
    resubmitted, successor = submit(binding, artifact, returned)
    assert resubmitted.version == 4 and resubmitted.controlling_prd_decision_id is None
    assert successor.predecessor_id == checkpoint.id and successor.content_digest == checkpoint.content_digest
    planning, second = decide(resubmitted, successor, assignment)
    assert planning.state == "PLANNING" and planning.version == 5
    assert planning.controlling_prd_decision_id == second.id
    assert PrdReviewDecision.objects.get(id=first.id).state == "CHANGES_REQUESTED"
    assert DocumentCheckpoint.objects.count() == 2


def test_successor_can_replace_pending_review_and_delayed_review_is_rejected():
    binding, artifact, initiative, checkpoint, assignment = review_fixture()
    successor_init, successor = submit(binding, artifact, initiative)
    assert successor_init.version == 3 and successor.predecessor_id == checkpoint.id
    with pytest.raises(ValidationError):
        decide(initiative, checkpoint, assignment)
    assert PrdReviewDecision.objects.count() == 0


@pytest.mark.parametrize("origin", ["PRD_REVIEW", "PLANNING", "ALIGNING"])
def test_pause_resume_and_cancel_retain_controlling_subject(origin):
    _, _, initiative, checkpoint, assignment = review_fixture()
    if origin != "PRD_REVIEW":
        initiative, _ = decide(initiative, checkpoint, assignment, "APPROVED" if origin == "PLANNING" else "REJECTED")
    original_decision = initiative.controlling_prd_decision_id
    for state, paused_from in [("PAUSED", origin), (origin, None), ("CANCELLED", None)]:
        initiative.state, initiative.paused_from_state = state, paused_from
        initiative.version += 1
        initiative.save()
        initiative.refresh_from_db()
        assert initiative.current_prd_checkpoint_id == checkpoint.id
        assert initiative.controlling_prd_decision_id == original_decision


def test_outbox_failure_rolls_back_approval_and_aggregate_together():
    _, _, initiative, checkpoint, assignment = review_fixture()
    with pytest.raises(RuntimeError), transaction.atomic():
        decide(initiative, checkpoint, assignment)
        raise RuntimeError("Synthetic outbox failure")
    initiative.refresh_from_db()
    assert initiative.version == 2 and initiative.state == "PRD_REVIEW"
    assert initiative.controlling_prd_decision_id is None and PrdReviewDecision.objects.count() == 0


def test_outbox_failure_rolls_back_submission_and_native_pointer_together():
    binding, artifact = capture_fixture()
    with pytest.raises(RuntimeError), transaction.atomic():
        submit(binding, artifact, binding.initiative)
        raise RuntimeError("Synthetic outbox failure")
    initiative = Initiative.objects.get(id=binding.initiative_id)
    artifact.refresh_from_db()
    assert initiative.state == "ALIGNING" and initiative.version == 1
    assert initiative.current_prd_checkpoint_id is None and artifact.current_version_id is None
    assert DocumentCheckpoint.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_repository_requires_outer_command_transaction():
    with pytest.raises(ValidationError, match="PRD_OUTER_TRANSACTION_REQUIRED"):
        record_prd_decision_transition(
            workspace_id=uuid.uuid4(),
            initiative_id=uuid.uuid4(),
            expected_version=1,
            expected_checkpoint_id=None,
            actor={},
            decision=None,
        )


@pytest.mark.django_db(transaction=True)
def test_competing_approval_and_return_have_one_aggregate_winner():
    _, _, initiative, checkpoint, assignment = review_fixture()
    barrier = Barrier(2)

    def apply(state):
        try:
            barrier.wait(timeout=10)
            try:
                decide(initiative, checkpoint, assignment, state)
                return "committed"
            except ValidationError as error:
                assert error.code == "PRD_INITIATIVE_VERSION_CONFLICT"
                return "stale"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(apply, ["APPROVED", "CHANGES_REQUESTED"]))
    assert sorted(outcomes) == ["committed", "stale"]
    initiative.refresh_from_db()
    assert initiative.version == 3 and PrdReviewDecision.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_successor_and_approval_race_cannot_approve_a_different_submission():
    binding, artifact, initiative, checkpoint, assignment = review_fixture()
    barrier = Barrier(2)

    def apply(action):
        try:
            barrier.wait(timeout=10)
            try:
                if action == "submit":
                    submit(binding, artifact, initiative)
                else:
                    decide(initiative, checkpoint, assignment)
                return action
            except ValidationError as error:
                assert error.code == "PRD_INITIATIVE_VERSION_CONFLICT"
                return "stale"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(apply, ["submit", "approve"]))
    assert outcomes.count("stale") == 1
    initiative.refresh_from_db()
    assert initiative.version == 3
    if "approve" in outcomes:
        assert initiative.state == "PLANNING" and initiative.current_prd_checkpoint_id == checkpoint.id
        assert DocumentCheckpoint.objects.count() == 1 and PrdReviewDecision.objects.count() == 1
    else:
        assert initiative.state == "PRD_REVIEW" and initiative.current_prd_checkpoint_id != checkpoint.id
        assert DocumentCheckpoint.objects.count() == 2 and PrdReviewDecision.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_empty_lifecycle_migration_reverses_without_losing_legacy_initiative():
    binding, _ = capture_fixture()
    latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
    try:
        MigrationExecutor(connection).migrate([("curve", "0012_prd_review_decision")])
        with connection.cursor() as cursor:
            cursor.execute("SELECT state, version FROM curve_initiative WHERE id = %s", [binding.initiative_id])
            assert cursor.fetchone() == ("ALIGNING", 1)
    finally:
        MigrationExecutor(connection).migrate(latest)
    assert Initiative.objects.get(id=binding.initiative_id).current_prd_checkpoint_id is None


@pytest.mark.django_db(transaction=True)
def test_migration_reverse_preserves_retained_lifecycle():
    _, _, initiative, _, _ = review_fixture()
    latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
    try:
        with pytest.raises(DatabaseError, match="preservation migration"):
            MigrationExecutor(connection).migrate([("curve", "0012_prd_review_decision")])
    finally:
        MigrationExecutor(connection).migrate(latest)
    initiative.refresh_from_db()
    assert initiative.state == "PRD_REVIEW" and initiative.current_prd_checkpoint_id is not None
