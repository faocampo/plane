# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor

from plane.curve.models import DocumentCheckpoint, GateAssignment, ImmutableRecordError, PrdReviewDecision
from plane.curve.prd_metadata_validation import instant, validate_review_decision_record
from plane.curve.prd_review_rationale import review_decision_wire_record
from plane.curve.tests.test_prd_checkpoint_models import capture_fixture, capture_records, persist_capture
from plane.curve.tests.test_prd_metadata_models import AT
from plane.curve.tests.test_prd_review_rationale import object_ref


pytestmark = [pytest.mark.unit, pytest.mark.django_db]


def decision_fixture(*, workspace_id=None, state="APPROVED"):
    binding, artifact = capture_fixture(workspace_id)
    records = capture_records(binding, artifact)
    persist_capture(artifact, *records)
    checkpoint = records[-1]
    assignments = [
        GateAssignment.objects.create(
            workspace_id=binding.workspace_id,
            initiative_id=binding.initiative_id,
            gate_type=kind,
            approver_user_id=uuid.uuid4(),
            valid_from=AT,
        )
        for kind in ("PRD_APPROVAL", "PLAN_APPROVAL", "CODE_READINESS")
    ]
    decision = decision_for(checkpoint, assignments[0], state=state)
    return binding, artifact, checkpoint, assignments, decision


def decision_for(checkpoint, assignment, *, state="APPROVED"):
    wire = dict(
        schema_version="1.0",
        id=str(uuid.uuid4()),
        workspace_id=str(checkpoint.workspace_id),
        initiative_id=str(checkpoint.initiative_id),
        gate_assignment_id=str(assignment.id),
        checkpoint_id=str(checkpoint.id),
        artifact_version_id=str(checkpoint.artifact_version_id),
        content_digest=checkpoint.content_digest,
        provider_version=checkpoint.provider_version,
        evidence_snapshot_id=str(checkpoint.evidence_snapshot_id),
        access_evaluation_id=str(uuid.uuid4()),
        policy_version_ids=[str(uuid.uuid4())],
        confirmed_risk_tier="STANDARD",
        state=state,
        decided_by=dict(actor_type="HUMAN", actor_id=str(assignment.approver_user_id)),
        decided_at=instant(checkpoint.recorded_at + timedelta(seconds=2)),
        provider_validation_cutoff=instant(checkpoint.recorded_at + timedelta(seconds=1)),
        rationale="Synthetic review rationale.",
    )
    return PrdReviewDecision.from_wire(
        decision=wire,
        rationale_ref=object_ref(wire["rationale"].encode()),
        rationale_access_envelope_id=uuid.uuid4(),
        rationale_retention_policy_version_id=uuid.uuid4(),
    )


@pytest.mark.parametrize("state", ["APPROVED", "CHANGES_REQUESTED", "REJECTED"])
def test_terminal_review_round_trip_contains_protected_reference_only(state):
    _, _, checkpoint, _, decision = decision_fixture(state=state)
    before = decision.as_metadata()
    assert "Synthetic review rationale." not in repr(decision.__dict__)
    decision.save()
    loaded = PrdReviewDecision.objects.find_by_id(workspace_id=decision.workspace_id, record_id=decision.id)
    assert loaded.as_metadata() == before
    validate_review_decision_record(before)
    assert PrdReviewDecision.objects.find_by_id(workspace_id=uuid.uuid4(), record_id=decision.id) is None
    assert not {"rationale", "body", "preview", "raw_response"}.intersection(
        field.name for field in decision._meta.fields
    )
    wire = review_decision_wire_record(metadata=loaded.as_metadata(), rationale_bytes=b"Synthetic review rationale.")
    assert wire["state"] == state and wire["checkpoint_id"] == str(checkpoint.id)


@pytest.mark.parametrize(
    "field",
    [
        "workspace_id",
        "initiative_id",
        "gate_assignment_id",
        "checkpoint_id",
        "artifact_version_id",
        "evidence_snapshot_id",
    ],
)
def test_model_rejects_missing_or_cross_scope_subject(field):
    _, _, _, _, decision = decision_fixture()
    setattr(decision, field, uuid.uuid4())
    with pytest.raises(ValidationError):
        decision.save()
    assert PrdReviewDecision.objects.count() == 0


@pytest.mark.parametrize(
    "field",
    [
        "workspace_id",
        "initiative_id",
        "gate_assignment_id",
        "checkpoint_id",
        "artifact_version_id",
        "evidence_snapshot_id",
    ],
)
@pytest.mark.parametrize("same_workspace", [False])
def test_database_rejects_existing_foreign_subjects(field, same_workspace):
    binding, _, _, _, decision = decision_fixture()
    _, _, _, _, foreign = decision_fixture(workspace_id=binding.workspace_id if same_workspace else None)
    setattr(decision, field, getattr(foreign, field))
    with pytest.raises(DatabaseError), transaction.atomic():
        decision.save_base(force_insert=True)


@pytest.mark.parametrize(
    "field", ["initiative_id", "gate_assignment_id", "checkpoint_id", "artifact_version_id", "evidence_snapshot_id"]
)
def test_database_rejects_existing_other_initiative_subjects(field):
    test_database_rejects_existing_foreign_subjects(field, True)


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "PENDING"),
        ("state", "SUPERSEDED"),
        ("confirmed_risk_tier", "LOW"),
        ("content_digest", "sha256:" + "f" * 64),
        ("provider_version", "different-version"),
        ("rationale_digest", "invalid"),
        ("rationale_size_bytes", 0),
        ("rationale_size_bytes", 8001),
        ("policy_version_ids", []),
        ("policy_version_ids", {}),
        ("policy_version_ids", ["invalid-id"]),
        ("policy_version_ids", ["00000000-0000-4000-8000-000000000001"] * 2),
        ("decided_by", {"actor_type": "SERVICE", "actor_id": "synthetic"}),
        ("provider_validation_cutoff", AT),
        ("decided_at", AT),
    ],
)
def test_raw_decision_insert_enforces_closed_exact_subject(field, value):
    _, _, _, _, decision = decision_fixture()
    setattr(decision, field, value)
    with pytest.raises(DatabaseError), transaction.atomic():
        decision.save_base(force_insert=True)


@pytest.mark.parametrize("index", [1, 2])
def test_technical_or_code_approver_cannot_replace_product_approver(index):
    _, _, checkpoint, assignments, _ = decision_fixture()
    decision = decision_for(checkpoint, assignments[index])
    with pytest.raises(DatabaseError), transaction.atomic():
        decision.save_base(force_insert=True)


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("change", ["expired", "future", "duplicate-human"])
def test_database_checks_all_gate_validity_and_required_separation(index, change):
    _, _, _, assignments, decision = decision_fixture()
    assignment = assignments[index]
    if change == "expired":
        assignment.valid_until = decision.decided_at
    elif change == "future":
        assignment.valid_from = decision.decided_at
    else:
        assignment.approver_user_id = assignments[(index + 1) % 3].approver_user_id
    assignment.save_base(force_update=True)
    with pytest.raises(DatabaseError), transaction.atomic():
        decision.save_base(force_insert=True)


@pytest.mark.parametrize(
    "mutation", ["save", "delete", "update", "query-delete", "bulk-create", "bulk-update", "raw-update", "raw-delete"]
)
def test_review_decision_is_immutable(mutation):
    _, _, _, _, decision = decision_fixture()
    decision.save()
    before = decision.as_metadata()
    if mutation.startswith("raw-"):
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            if mutation == "raw-update":
                cursor.execute("UPDATE curve_prd_review_decision SET state = 'REJECTED' WHERE id = %s", [decision.id])
            else:
                cursor.execute("DELETE FROM curve_prd_review_decision WHERE id = %s", [decision.id])
    else:
        with pytest.raises(ImmutableRecordError):
            if mutation == "save":
                decision.save()
            elif mutation == "delete":
                decision.delete()
            elif mutation == "update":
                PrdReviewDecision.objects.filter(id=decision.id).update(state="REJECTED")
            elif mutation == "query-delete":
                PrdReviewDecision.objects.filter(id=decision.id).delete()
            elif mutation == "bulk-create":
                PrdReviewDecision.objects.bulk_create([decision])
            else:
                PrdReviewDecision.objects.bulk_update([decision], ["state"])
    decision.refresh_from_db()
    assert decision.as_metadata() == before


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("action", ["update", "delete"])
def test_reviewed_assignment_history_remains_available(index, action):
    _, _, _, assignments, decision = decision_fixture()
    decision.save()
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        if action == "update":
            cursor.execute(
                "UPDATE curve_gate_assignment SET approver_user_id = %s WHERE id = %s",
                [uuid.uuid4(), assignments[index].id],
            )
        else:
            cursor.execute("DELETE FROM curve_gate_assignment WHERE id = %s", [assignments[index].id])


@pytest.mark.parametrize("state", ["CHANGES_REQUESTED", "REJECTED"])
def test_negative_review_preserves_exact_submission_after_source_changes(state):
    binding, _, _, _, decision = decision_fixture(state=state)
    binding.current_provider_version = "changed-after-submission"
    binding.version += 1
    binding.save()
    decision.save()
    assert decision.provider_version != binding.current_provider_version


def test_known_source_version_change_prevents_approval():
    binding, _, _, _, decision = decision_fixture()
    binding.current_provider_version = "changed-after-submission"
    binding.version += 1
    binding.save()
    with pytest.raises(DatabaseError), transaction.atomic():
        decision.save()


def test_one_terminal_outcome_per_checkpoint_requires_resubmission():
    _, _, checkpoint, assignments, decision = decision_fixture(state="CHANGES_REQUESTED")
    decision.save()
    other = decision_for(checkpoint, assignments[0], state="APPROVED")
    with pytest.raises(IntegrityError), transaction.atomic():
        other.save()


def test_old_decision_survives_successor_and_another_outcome():
    binding, artifact, checkpoint, assignments, first = decision_fixture(state="CHANGES_REQUESTED")
    first.save()
    before = first.as_metadata()
    second_capture = capture_records(binding, artifact, checkpoint.id)
    persist_capture(artifact, *second_capture)
    second = decision_for(second_capture[-1], assignments[0])
    second.save()
    first.refresh_from_db()
    assert first.as_metadata() == before and PrdReviewDecision.objects.count() == 2


def test_superseded_checkpoint_cannot_receive_delayed_decision():
    binding, artifact, checkpoint, _, first = decision_fixture()
    persist_capture(artifact, *capture_records(binding, artifact, checkpoint.id))
    with pytest.raises(DatabaseError), transaction.atomic():
        first.save()


def test_outer_command_failure_rolls_back_decision():
    _, _, _, _, decision = decision_fixture()
    with pytest.raises(RuntimeError), transaction.atomic():
        decision.save()
        raise RuntimeError("Synthetic outbox failure")
    assert PrdReviewDecision.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_competing_terminal_decisions_have_one_winner():
    _, _, checkpoint, assignments, _ = decision_fixture()
    barrier = Barrier(2)

    def record(state):
        try:
            decision = decision_for(checkpoint, assignments[0], state=state)
            barrier.wait(timeout=10)
            try:
                with transaction.atomic():
                    decision.save()
                return "committed"
            except IntegrityError:
                return "conflict"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(record, ["APPROVED", "CHANGES_REQUESTED"]))
    assert sorted(result) == ["committed", "conflict"]
    assert PrdReviewDecision.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_decision_migration_preserves_parents_and_refuses_retained_history_loss():
    _, _, checkpoint, assignments, decision = decision_fixture()
    latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
    previous = ("curve", "0011_document_checkpoint")
    try:
        MigrationExecutor(connection).migrate([previous])
        assert "curve_prd_review_decision" not in connection.introspection.table_names()
        assert DocumentCheckpoint.objects.filter(id=checkpoint.id).exists()
        assert GateAssignment.objects.filter(id=assignments[0].id).exists()
    finally:
        MigrationExecutor(connection).migrate(latest)
    decision.save()
    try:
        with pytest.raises(DatabaseError, match="preservation migration"):
            MigrationExecutor(connection).migrate([previous])
    finally:
        MigrationExecutor(connection).migrate(latest)
    assert PrdReviewDecision.objects.filter(id=decision.id).exists()
