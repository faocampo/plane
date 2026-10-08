# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor

from plane.curve.models import (
    DocumentCheckpoint,
    ExternalDocumentBinding,
    ImmutableRecordError,
    Initiative,
    PrdArtifact,
    PrdArtifactVersion,
    PrdEvidenceSnapshot,
)
from plane.curve.prd_checkpoint_repository import append_document_checkpoint_metadata
from plane.curve.prd_metadata_validation import validate_external_record
from plane.curve.tests.test_external_document_models import binding_values, initiative_values
from plane.curve.tests.test_prd_metadata_models import AT, OTHER_DIGEST, persist_submission, submission_records


pytestmark = [pytest.mark.unit, pytest.mark.django_db]


def capture_fixture(workspace_id=None):
    if workspace_id is None:
        values = binding_values()
    else:
        # The public local-provider profile permits one connection per workspace.
        # A second Initiative shares that connection rather than fabricating one.
        existing = ExternalDocumentBinding.objects.for_workspace(workspace_id).first()
        values = dict(
            workspace_id=workspace_id,
            initiative=Initiative.objects.create(**initiative_values(workspace_id)),
            provider_connection_id=existing.provider_connection_id,
            provider_file_id="synthetic-other-document",
            provider_container_id="synthetic-container",
            canonical_url="https://docs.example.invalid/documents/synthetic-other-document",
            current_provider_version="900719925474099312345",
            current_modified_at=AT,
            created_by=deepcopy(existing.created_by),
        )
    values["created_at"] = AT
    binding = ExternalDocumentBinding.objects.create(**values)
    initiative = binding.initiative
    initiative.state = "ALIGNING"
    initiative.workflow_version_id = uuid.uuid4()
    initiative.save()
    artifact = PrdArtifact.objects.create(workspace_id=binding.workspace_id, initiative=initiative, created_at=AT)
    return binding, artifact


def capture_records(binding, artifact, predecessor_id=None):
    snapshot, version = submission_records(artifact)
    checkpoint = DocumentCheckpoint(
        workspace_id=artifact.workspace_id,
        initiative_id=artifact.initiative_id,
        external_document_binding=binding,
        artifact_version=version,
        evidence_snapshot=snapshot,
        predecessor_id=predecessor_id,
        checkpoint_number=version.version_number,
        provider_connection_id=binding.provider_connection_id,
        provider_file_id=binding.provider_file_id,
        provider_container_id=binding.provider_container_id,
        provider_version=binding.current_provider_version,
        revision_id=None,
        body_object_id=version.body_object_id,
        content_digest=version.body_digest,
        body_size_bytes=version.body_size_bytes,
        normalization_schema_version=version.body_schema_id,
        access_evaluation_id=uuid.uuid4(),
        completeness_check_id=uuid.uuid4(),
        retention_policy_version_id=version.retention_policy_version_id,
        access_envelope_id=version.access_envelope_id,
        submitted_or_approved_by=deepcopy(version.created_by),
        recorded_at=version.created_at,
    )
    return snapshot, version, checkpoint


def persist_capture(artifact, snapshot, version, checkpoint, **overrides):
    args = dict(
        workspace_id=artifact.workspace_id,
        initiative_id=artifact.initiative_id,
        expected_initiative_version=1,
        artifact_id=artifact.id,
        expected_parent_version_id=version.parent_version_id,
        expected_predecessor_id=checkpoint.predecessor_id,
        snapshot=snapshot,
        version=version,
        checkpoint=checkpoint,
    )
    args.update(overrides)
    with transaction.atomic():
        result = append_document_checkpoint_metadata(**args)
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    artifact.refresh_from_db()
    return result


def native_capture_fixture():
    binding, artifact = capture_fixture()
    snapshot, version, checkpoint = capture_records(binding, artifact)
    persist_submission(artifact, snapshot, version)
    return binding, artifact, snapshot, version, checkpoint


def test_checkpoint_round_trip_is_closed_scoped_metadata():
    binding, artifact = capture_fixture()
    snapshot, version, checkpoint = capture_records(binding, artifact)
    original = checkpoint.as_record()
    result = persist_capture(artifact, snapshot, version, checkpoint)
    loaded = DocumentCheckpoint.objects.find_by_id(workspace_id=artifact.workspace_id, record_id=result.id)
    assert loaded.as_record() == original
    validate_external_record("Checkpoint", loaded.as_record())
    validate_external_record("Binding", binding.as_record())
    assert DocumentCheckpoint.objects.find_by_id(workspace_id=uuid.uuid4(), record_id=result.id) is None
    with pytest.raises(ValueError, match="workspace_id"):
        DocumentCheckpoint.objects.for_workspace(None)
    assert not {"body", "rationale", "normalized_content", "credentials", "raw_response"}.intersection(
        field.name for field in DocumentCheckpoint._meta.fields
    )
    # Metadata persistence itself does not authorize or perform the transition.
    artifact.initiative.refresh_from_db()
    assert artifact.initiative.state == "ALIGNING" and artifact.initiative.version == 1


def test_successive_captures_preserve_full_history_and_unchanged_body_digest():
    binding, artifact = capture_fixture()
    first = capture_records(binding, artifact)
    persist_capture(artifact, *first)
    previous = first[-1].as_record()
    second = capture_records(binding, artifact, first[-1].id)
    persist_capture(artifact, *second)
    first[-1].refresh_from_db()
    assert first[-1].as_record() == previous
    assert second[-1].checkpoint_number == 2
    assert second[-1].content_digest == first[-1].content_digest
    assert second[-1].artifact_version_id != first[-1].artifact_version_id
    assert (
        DocumentCheckpoint.objects.count()
        == PrdArtifactVersion.objects.count()
        == PrdEvidenceSnapshot.objects.count()
        == 2
    )


def test_container_move_preserves_capture_provenance():
    binding, artifact, snapshot, version, checkpoint = native_capture_fixture()
    binding.provider_container_id = "synthetic-moved-container"
    binding.current_provider_version = "new-source-version"
    binding.version += 1
    binding.save()
    checkpoint.save()
    assert checkpoint.as_record()["provider_container_id"] == "synthetic-container"
    assert checkpoint.provider_version != binding.current_provider_version


@pytest.mark.parametrize(
    "field",
    [
        "workspace_id",
        "initiative_id",
        "external_document_binding_id",
        "artifact_version_id",
        "evidence_snapshot_id",
        "predecessor_id",
    ],
)
def test_model_references_are_loaded_workspace_first(field):
    _, _, _, _, checkpoint = native_capture_fixture()
    setattr(checkpoint, field, uuid.uuid4())
    with pytest.raises(ValidationError):
        checkpoint.save()
    assert DocumentCheckpoint.objects.count() == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("content_digest", OTHER_DIGEST),
        ("body_size_bytes", 0),
        ("body_size_bytes", 124),
        ("body_size_bytes", 9007199254740992),
        ("checkpoint_number", 0),
        ("checkpoint_number", 2),
        ("provider_file_id", "wrong-document"),
        ("provider_container_id", "inline/body"),
        ("provider_version", ""),
        ("provider_version", "source/version"),
        ("revision_id", ""),
        ("normalization_schema_version", "wrong-schema"),
        ("submitted_or_approved_by", {"actor_type": "SERVICE", "actor_id": "synthetic"}),
        ("submitted_or_approved_by", {"actor_type": "HUMAN", "actor_id": "synthetic", "body": "forbidden"}),
        ("recorded_at", AT - timedelta(seconds=1)),
    ],
)
def test_database_rejects_invalid_checkpoint_metadata_without_model_validation(field, value):
    _, _, _, _, checkpoint = native_capture_fixture()
    setattr(checkpoint, field, value)
    with pytest.raises(DatabaseError), transaction.atomic():
        checkpoint.save_base(force_insert=True)
    assert DocumentCheckpoint.objects.count() == 0


@pytest.mark.parametrize(
    "field",
    [
        "workspace_id",
        "initiative_id",
        "external_document_binding_id",
        "artifact_version_id",
        "evidence_snapshot_id",
        "provider_connection_id",
        "predecessor_id",
        "body_object_id",
        "access_envelope_id",
        "retention_policy_version_id",
    ],
)
def test_database_rejects_fabricated_subject_references(field):
    _, _, _, _, checkpoint = native_capture_fixture()
    setattr(checkpoint, field, uuid.uuid4())
    with pytest.raises(DatabaseError), transaction.atomic():
        checkpoint.save_base(force_insert=True)


@pytest.mark.parametrize(
    "field",
    [
        "external_document_binding_id",
        "artifact_version_id",
        "evidence_snapshot_id",
        "provider_connection_id",
        "initiative_id",
    ],
)
def test_database_rejects_existing_foreign_tenant_references(field):
    _, _, _, _, checkpoint = native_capture_fixture()
    _, _, _, _, foreign = native_capture_fixture()
    setattr(checkpoint, field, getattr(foreign, field))
    with pytest.raises(DatabaseError), transaction.atomic():
        checkpoint.save_base(force_insert=True)


@pytest.mark.parametrize(
    "field", ["external_document_binding_id", "artifact_version_id", "evidence_snapshot_id", "initiative_id"]
)
def test_database_rejects_other_initiative_references_within_same_workspace(field):
    binding, _, _, _, checkpoint = native_capture_fixture()
    other_binding, other_artifact = capture_fixture(binding.workspace_id)
    other_snapshot, other_version, other_checkpoint = capture_records(other_binding, other_artifact)
    persist_submission(other_artifact, other_snapshot, other_version)
    setattr(checkpoint, field, getattr(other_checkpoint, field))
    with pytest.raises(DatabaseError), transaction.atomic():
        checkpoint.save_base(force_insert=True)


@pytest.mark.parametrize(
    "mutation", ["save", "delete", "update", "query-delete", "bulk-create", "bulk-update", "raw-update", "raw-delete"]
)
def test_checkpoint_history_is_immutable_through_all_write_paths(mutation):
    _, _, _, _, checkpoint = native_capture_fixture()
    checkpoint.save()
    before = checkpoint.as_record()
    if mutation.startswith("raw-"):
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            if mutation == "raw-update":
                cursor.execute(
                    "UPDATE curve_document_checkpoint SET provider_version = %s WHERE id = %s",
                    ["replacement", checkpoint.id],
                )
            else:
                cursor.execute("DELETE FROM curve_document_checkpoint WHERE id = %s", [checkpoint.id])
    else:
        with pytest.raises(ImmutableRecordError):
            if mutation == "save":
                checkpoint.save()
            elif mutation == "delete":
                checkpoint.delete()
            elif mutation == "update":
                DocumentCheckpoint.objects.filter(id=checkpoint.id).update(provider_version="replacement")
            elif mutation == "query-delete":
                DocumentCheckpoint.objects.filter(id=checkpoint.id).delete()
            elif mutation == "bulk-create":
                DocumentCheckpoint.objects.bulk_create([checkpoint])
            else:
                DocumentCheckpoint.objects.bulk_update([checkpoint], ["provider_version"])
    checkpoint.refresh_from_db()
    assert checkpoint.as_record() == before


def test_colliding_checkpoint_id_cannot_rewrite_capture():
    binding, artifact, _, _, checkpoint = native_capture_fixture()
    checkpoint.save()
    original = checkpoint.as_record()
    clone = DocumentCheckpoint(
        **{field.attname: getattr(checkpoint, field.attname) for field in checkpoint._meta.fields}
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        clone.save()
    checkpoint.refresh_from_db()
    assert checkpoint.as_record() == original


def test_two_checkpoints_cannot_bind_one_artifact_version():
    _, _, _, _, checkpoint = native_capture_fixture()
    checkpoint.save()
    clone = DocumentCheckpoint(
        **{field.attname: getattr(checkpoint, field.attname) for field in checkpoint._meta.fields}
    )
    clone.id = uuid.uuid4()
    with pytest.raises(DatabaseError), transaction.atomic():
        clone.save_base(force_insert=True)


def test_incomplete_checkpoint_failure_rolls_back_entire_new_metadata_graph():
    binding, artifact = capture_fixture()
    snapshot, version, checkpoint = capture_records(binding, artifact)
    checkpoint.body_size_bytes += 1
    with pytest.raises(ValidationError):
        persist_capture(artifact, snapshot, version, checkpoint)
    artifact.refresh_from_db()
    assert artifact.current_version_id is None
    assert (
        DocumentCheckpoint.objects.count()
        == PrdArtifactVersion.objects.count()
        == PrdEvidenceSnapshot.objects.count()
        == 0
    )


def test_outer_command_outbox_failure_rolls_back_checkpoint_and_native_records():
    binding, artifact = capture_fixture()
    records = capture_records(binding, artifact)
    with pytest.raises(RuntimeError), transaction.atomic():
        persist_capture(artifact, *records)
        raise RuntimeError("Synthetic outbox failure")
    artifact.refresh_from_db()
    assert artifact.current_version_id is None
    assert (
        DocumentCheckpoint.objects.count()
        == PrdArtifactVersion.objects.count()
        == PrdEvidenceSnapshot.objects.count()
        == 0
    )


@pytest.mark.parametrize("state", ["DRAFT", "PAUSED", "CANCELLED"])
def test_submission_metadata_requires_aligning_and_cancellation_fence(state):
    binding, artifact = capture_fixture()
    initiative = artifact.initiative
    initiative.state = state
    if state == "DRAFT":
        initiative.workflow_version_id = None
    if state == "PAUSED":
        initiative.paused_from_state = "ALIGNING"
    initiative.save()
    with pytest.raises(ValidationError) as error:
        persist_capture(artifact, *capture_records(binding, artifact))
    assert error.value.code == "CHECKPOINT_INITIATIVE_STATE_CONFLICT"
    assert DocumentCheckpoint.objects.count() == PrdArtifactVersion.objects.count() == 0


def test_stale_initiative_version_prevents_capture_commit():
    binding, artifact = capture_fixture()
    with pytest.raises(ValidationError) as error:
        persist_capture(artifact, *capture_records(binding, artifact), expected_initiative_version=2)
    assert error.value.code == "CHECKPOINT_INITIATIVE_VERSION_CONFLICT"
    assert DocumentCheckpoint.objects.count() == PrdArtifactVersion.objects.count() == 0


def test_boolean_is_not_an_initiative_version():
    binding, artifact = capture_fixture()
    with pytest.raises(ValidationError) as error:
        persist_capture(artifact, *capture_records(binding, artifact), expected_initiative_version=True)
    assert error.value.code == "CHECKPOINT_INITIATIVE_VERSION_CONFLICT"


def test_cross_initiative_native_graph_is_rejected_before_append():
    binding, artifact = capture_fixture()
    _, _, checkpoint = capture_records(binding, artifact)
    other_binding, other_artifact = capture_fixture(binding.workspace_id)
    snapshot, version, _ = capture_records(other_binding, other_artifact)
    checkpoint.artifact_version = version
    checkpoint.evidence_snapshot = snapshot
    with pytest.raises(ValidationError) as error:
        persist_capture(other_artifact, snapshot, version, checkpoint, initiative_id=artifact.initiative_id)
    assert error.value.code == "CHECKPOINT_SUBMISSION_LINKAGE_INVALID"
    assert DocumentCheckpoint.objects.count() == PrdArtifactVersion.objects.count() == 0


def test_raw_successor_cannot_fork_an_older_checkpoint():
    binding, artifact = capture_fixture()
    first = capture_records(binding, artifact)
    persist_capture(artifact, *first)
    second = capture_records(binding, artifact, first[-1].id)
    persist_capture(artifact, *second)
    snapshot, version, third = capture_records(binding, artifact, first[-1].id)
    persist_submission(artifact, snapshot, version)
    with pytest.raises(DatabaseError), transaction.atomic():
        third.save_base(force_insert=True)
    assert DocumentCheckpoint.objects.count() == 2


def test_delayed_checkpoint_cannot_attach_to_an_obsolete_native_version():
    _, artifact, _, _, checkpoint = native_capture_fixture()
    snapshot2, version2 = submission_records(artifact)
    persist_submission(artifact, snapshot2, version2)
    with pytest.raises(DatabaseError), transaction.atomic():
        checkpoint.save_base(force_insert=True)


@pytest.mark.django_db(transaction=True)
def test_competing_capture_commands_have_one_metadata_winner():
    binding, artifact = capture_fixture()
    first = capture_records(binding, artifact)
    persist_capture(artifact, *first)
    barrier = Barrier(2)

    def submit():
        try:
            local_binding = ExternalDocumentBinding.objects.get(pk=binding.id)
            local_artifact = PrdArtifact.objects.get(pk=artifact.id)
            records = capture_records(local_binding, local_artifact, first[-1].id)
            barrier.wait(timeout=10)
            try:
                persist_capture(local_artifact, *records)
                return "committed"
            except (IntegrityError, ValidationError):
                return "conflict"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: submit(), range(2)))
    assert sorted(outcomes) == ["committed", "conflict"]
    assert (
        DocumentCheckpoint.objects.count()
        == PrdArtifactVersion.objects.count()
        == PrdEvidenceSnapshot.objects.count()
        == 2
    )


@pytest.mark.django_db(transaction=True)
def test_checkpoint_migration_reverses_only_when_empty_and_preserves_native_records():
    binding, artifact, snapshot, version, checkpoint = native_capture_fixture()
    latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
    previous = ("curve", "0010_prd_artifact_evidence")
    try:
        MigrationExecutor(connection).migrate([previous])
        assert "curve_document_checkpoint" not in connection.introspection.table_names()
        assert PrdArtifactVersion.objects.filter(id=version.id).exists()
        assert PrdEvidenceSnapshot.objects.filter(id=snapshot.id).exists()
        assert ExternalDocumentBinding.objects.filter(id=binding.id).exists()
    finally:
        MigrationExecutor(connection).migrate(latest)
    checkpoint.save()
    try:
        with pytest.raises(DatabaseError, match="preservation migration"):
            MigrationExecutor(connection).migrate([previous])
    finally:
        MigrationExecutor(connection).migrate(latest)
    assert DocumentCheckpoint.objects.filter(id=checkpoint.id).exists()
