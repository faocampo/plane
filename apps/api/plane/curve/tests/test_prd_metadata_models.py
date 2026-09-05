# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor

from plane.curve.models import (
    ImmutableRecordError,
    Initiative,
    PrdArtifact,
    PrdArtifactVersion,
    PrdEvidenceItemVersion,
    PrdEvidenceSnapshot,
    ProviderConnection,
)
from plane.curve.prd_metadata_validation import instant, metadata_digest, validate_record
from plane.curve.prd_metadata_repository import append_prd_submission_metadata
from plane.curve.tests.test_external_document_models import initiative_values
from plane.curve.tests.test_provider_models import ACTOR, connection_values


pytestmark = [pytest.mark.unit, pytest.mark.django_db]
AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64


def artifact_fixture(workspace_id=None):
    workspace_id = workspace_id or uuid.uuid4()
    initiative = Initiative.objects.create(**initiative_values(workspace_id))
    return PrdArtifact.objects.create(workspace_id=workspace_id, initiative=initiative, created_at=AT)


def evidence_fixture(workspace_id):
    provider = ProviderConnection.objects.create(**connection_values(workspace_id))
    policy_id = str(uuid.uuid4())
    source_ref = dict(resource_type="SOURCE_DOCUMENT", resource_id=str(uuid.uuid4()), resource_version=1)
    envelope = dict(
        schema_version="1.0",
        id=str(uuid.uuid4()),
        workspace_id=str(workspace_id),
        source_refs=[source_ref],
        effective_principal=ACTOR,
        source_authorization_digest=DIGEST,
        classification="INTERNAL",
        allowed_audiences=["WORKSPACE_MEMBERS"],
        allowed_destinations=["PROTECTED_STORAGE"],
        retention_policy_ref=dict(resource_type="RETENTION_POLICY_VERSION", resource_id=policy_id),
        redaction_state="SANITIZED_METADATA_ONLY",
        legal_hold=False,
        created_at=instant(AT),
    )
    evidence_id = uuid.uuid4()
    record = dict(
        schema_version="1.0-candidate",
        id=str(evidence_id),
        workspace_id=str(workspace_id),
        created_at=instant(AT),
        version=1,
        source=dict(
            provider_connection_id=str(provider.id),
            resource_id="synthetic-source",
            resource_type="DOCUMENT",
            source_ref=source_ref,
        ),
        source_version="source-version-one",
        retrieved_at=instant(AT),
        effective_principal=ACTOR,
        content=None,
        content_digest=DIGEST,
        classification="INTERNAL",
        access_envelope=envelope,
        trust_flags=[],
        redaction_state="SANITIZED_METADATA_ONLY",
        retention_policy_version_id=policy_id,
    )
    return PrdEvidenceItemVersion.objects.create(
        evidence_id=evidence_id, workspace_id=workspace_id, version=1, provider_connection=provider, record=record
    )


def snapshot_entry(item, *, ordinal=0):
    return dict(
        ordinal=ordinal,
        evidence_item_id=str(item.evidence_id),
        evidence_item_version=item.version,
        content_digest=item.record["content_digest"],
        source_version=item.record["source_version"],
        access_envelope_id=item.record["access_envelope"]["id"],
        access_envelope_digest=item.envelope_digest,
        material=True,
        claim_refs=["requirement-one"],
        selected_excerpt_ref=None,
    )


def submission_records(artifact, items=(), *, version_number=None):
    parent_id = artifact.current_version_id
    number = version_number or (artifact.current_version.version_number + 1 if parent_id else 1)
    version_id = uuid.uuid4()
    snapshot = PrdEvidenceSnapshot(
        workspace_id=artifact.workspace_id,
        initiative_id=artifact.initiative_id,
        artifact_version_id=version_id,
        created_at=AT + timedelta(seconds=number),
        items=list(items),
    )
    snapshot.digest = snapshot.compute_digest()
    version = PrdArtifactVersion(
        id=version_id,
        workspace_id=artifact.workspace_id,
        initiative_id=artifact.initiative_id,
        artifact=artifact,
        version_number=number,
        parent_version_id=parent_id,
        evidence_snapshot=snapshot,
        body_object_id=uuid.uuid4(),
        body_digest=DIGEST,
        body_size_bytes=123,
        body_schema_id="curve.normalized-prd/v1-candidate",
        body_schema_version=1,
        access_envelope_id=uuid.uuid4(),
        retention_policy_version_id=uuid.uuid4(),
        created_by=ACTOR,
        created_at=snapshot.created_at,
    )
    return snapshot, version


def persist_submission(artifact, snapshot, version):
    with transaction.atomic():
        persisted = append_prd_submission_metadata(
            workspace_id=artifact.workspace_id,
            artifact_id=artifact.id,
            expected_parent_version_id=version.parent_version_id,
            snapshot=snapshot,
            version=version,
        )
        artifact.current_version = persisted.current_version
        # Exercise deferred commit constraints even under pytest's outer transaction.
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")


@pytest.mark.parametrize("with_evidence", [False, True])
def test_submitted_prd_round_trip_preserves_exact_snapshot_and_source_versions(with_evidence):
    artifact = artifact_fixture()
    item = evidence_fixture(artifact.workspace_id) if with_evidence else None
    snapshot, version = submission_records(artifact, [snapshot_entry(item)] if item else [])
    persist_submission(artifact, snapshot, version)
    artifact.refresh_from_db()
    version.refresh_from_db()
    snapshot.refresh_from_db()
    assert artifact.current_version_id == version.id
    assert version.evidence_snapshot_id == snapshot.id
    assert snapshot.artifact_version_id == version.id
    assert snapshot.digest == snapshot.compute_digest()
    assert version.as_record()["state"] == "SUBMITTED"
    for kind, record in (("Artifact", artifact), ("ArtifactVersion", version), ("EvidenceSnapshot", snapshot)):
        validate_record(kind, record.as_record())
    assert version.body_object_id
    assert not hasattr(version, "normalized_content")
    assert artifact.initiative.state == "DRAFT"


def test_successor_preserves_previous_capture_and_exact_parent():
    artifact = artifact_fixture()
    first_snapshot, first = submission_records(artifact)
    persist_submission(artifact, first_snapshot, first)
    original = deepcopy(first.as_record())
    successor_snapshot, successor = submission_records(artifact)
    persist_submission(artifact, successor_snapshot, successor)
    first.refresh_from_db()
    assert first.as_record() == original
    assert successor.parent_version_id == first.id
    assert successor.version_number == 2
    assert PrdArtifactVersion.objects.count() == 2
    with pytest.raises(IntegrityError), transaction.atomic():
        artifact.current_version = first
        artifact.save()


def test_existing_version_cannot_receive_a_second_unpaired_snapshot():
    artifact = artifact_fixture()
    snapshot, version = submission_records(artifact)
    persist_submission(artifact, snapshot, version)
    additional = PrdEvidenceSnapshot(
        workspace_id=artifact.workspace_id,
        initiative_id=artifact.initiative_id,
        artifact_version_id=version.id,
        created_at=snapshot.created_at,
        items=[],
    )
    additional.digest = additional.compute_digest()
    with pytest.raises(IntegrityError), transaction.atomic():
        additional.save()


@pytest.mark.parametrize("omit", ["version", "snapshot", "pointer"])
def test_incomplete_submission_rolls_back_all_records(omit):
    artifact = artifact_fixture()
    snapshot, version = submission_records(artifact)
    with pytest.raises(IntegrityError), transaction.atomic():
        if omit != "snapshot":
            snapshot.save()
        if omit != "version":
            version.save()
        if omit != "pointer":
            artifact.current_version = version
            artifact.save()
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    artifact.refresh_from_db()
    assert artifact.current_version_id is None
    assert PrdArtifactVersion.objects.count() == 0
    assert PrdEvidenceSnapshot.objects.count() == 0


@pytest.mark.parametrize("field", ["workspace_id", "initiative_id", "artifact_id", "parent_version_id"])
def test_version_references_cannot_cross_scope(field):
    artifact = artifact_fixture()
    foreign = artifact_fixture()
    snapshot, version = submission_records(artifact)
    setattr(version, field, getattr(foreign, field, foreign.id) if field != "artifact_id" else foreign.id)
    with pytest.raises((IntegrityError, ValidationError)), transaction.atomic():
        persist_submission(artifact, snapshot, version)


@pytest.mark.parametrize(
    "field,value",
    [
        ("content_digest", OTHER_DIGEST),
        ("source_version", "replaced-source"),
        ("access_envelope_id", "00000000-0000-4000-8000-000000000099"),
        ("access_envelope_digest", OTHER_DIGEST),
        ("evidence_item_version", 2),
        ("ordinal", 1),
        ("evidence_item_id", "00000000-0000-4000-8000-000000000098"),
        ("claim_refs", []),
    ],
)
def test_snapshot_rejects_substituted_evidence_or_missing_claim(field, value):
    artifact = artifact_fixture()
    item = evidence_fixture(artifact.workspace_id)
    entry = snapshot_entry(item)
    entry[field] = value
    snapshot, version = submission_records(artifact, [entry])
    with pytest.raises((IntegrityError, ValidationError)), transaction.atomic():
        persist_submission(artifact, snapshot, version)


def test_cross_workspace_evidence_and_duplicate_membership_are_rejected():
    artifact = artifact_fixture()
    foreign_item = evidence_fixture(uuid.uuid4())
    snapshot, version = submission_records(artifact, [snapshot_entry(foreign_item)])
    with pytest.raises(IntegrityError), transaction.atomic():
        persist_submission(artifact, snapshot, version)
    item = evidence_fixture(artifact.workspace_id)
    snapshot, version = submission_records(artifact, [snapshot_entry(item), snapshot_entry(item, ordinal=1)])
    with pytest.raises(ValidationError), transaction.atomic():
        persist_submission(artifact, snapshot, version)


def test_snapshot_digest_changes_with_claims_order_and_identity():
    artifact = artifact_fixture()
    item = evidence_fixture(artifact.workspace_id)
    snapshot, version = submission_records(artifact, [snapshot_entry(item)])
    original = snapshot.digest
    snapshot.items[0]["claim_refs"] = ["different-claim"]
    assert snapshot.compute_digest() != original
    with pytest.raises(ValidationError, match="DIGEST"), transaction.atomic():
        persist_submission(artifact, snapshot, version)


@pytest.mark.parametrize(
    "table,key",
    [
        ("curve_prd_artifact_version", "version"),
        ("curve_prd_evidence_snapshot", "snapshot"),
        ("curve_prd_evidence_item_version", "item"),
    ],
)
def test_immutable_history_is_protected_in_orm_bulk_and_direct_sql(table, key):
    artifact = artifact_fixture()
    item = evidence_fixture(artifact.workspace_id)
    snapshot, version = submission_records(artifact, [snapshot_entry(item)])
    persist_submission(artifact, snapshot, version)
    record = dict(item=item, snapshot=snapshot, version=version)[key]
    for call in (
        record.save,
        record.delete,
        lambda: type(record).objects.update(workspace_id=uuid.uuid4()),
        lambda: type(record).objects.bulk_create([]),
        lambda: type(record).objects.delete(),
    ):
        with pytest.raises(ImmutableRecordError):
            call()
    for statement in (f"DELETE FROM {table}", f"UPDATE {table} SET workspace_id = workspace_id"):
        with pytest.raises(IntegrityError, match="immutable"), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(statement)


@pytest.mark.parametrize("mutation", ["body", "principal", "scope", "policy", "digest", "extra"])
def test_evidence_metadata_rejects_injected_content_and_inconsistent_envelopes(mutation):
    original = evidence_fixture(uuid.uuid4())
    record = deepcopy(original.record)
    record["id"] = str(uuid.uuid4())
    if mutation == "body":
        record["content"] = "protected text must not be stored here"
    elif mutation == "principal":
        record["effective_principal"] = dict(actor_type="SERVICE", actor_id="synthetic-service")
    elif mutation == "scope":
        record["access_envelope"]["workspace_id"] = str(uuid.uuid4())
    elif mutation == "policy":
        record["retention_policy_version_id"] = str(uuid.uuid4())
    elif mutation == "digest":
        record["content"] = dict(
            object_id=str(uuid.uuid4()), digest=OTHER_DIGEST, size_bytes=2, media_type="text/plain"
        )
    else:
        record["access_envelope"]["raw_text"] = "forbidden"
    with pytest.raises(ValidationError) as error:
        PrdEvidenceItemVersion.objects.create(
            evidence_id=record["id"],
            version=1,
            workspace_id=original.workspace_id,
            provider_connection_id=original.provider_connection_id,
            record=record,
        )
    assert "protected text" not in str(error.value) and "forbidden" not in str(error.value)


@pytest.mark.django_db(transaction=True)
def test_two_successor_submissions_have_one_transaction_winner():
    artifact = artifact_fixture()
    snapshot, version = submission_records(artifact)
    persist_submission(artifact, snapshot, version)
    barrier = Barrier(2)

    def submit():
        try:
            loaded = PrdArtifact.objects.get(pk=artifact.id)
            next_snapshot, next_version = submission_records(loaded)
            barrier.wait(timeout=10)
            try:
                persist_submission(loaded, next_snapshot, next_version)
                return "committed"
            except (IntegrityError, ValidationError):
                return "conflict"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert sorted(results) == ["committed", "conflict"]
    assert PrdArtifactVersion.objects.count() == 2
    assert PrdEvidenceSnapshot.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_prd_migration_reverses_only_when_empty_and_preserves_parent_rows():
    current = MigrationExecutor(connection).loader.graph.leaf_nodes()
    previous = ("curve", "0009_external_document_binding")
    initiative = Initiative.objects.create(**initiative_values(uuid.uuid4()))
    try:
        MigrationExecutor(connection).migrate([previous])
        assert "curve_prd_artifact" not in connection.introspection.table_names()
        assert Initiative.objects.filter(pk=initiative.id).exists()
    finally:
        MigrationExecutor(connection).migrate(current)
    artifact_fixture()
    try:
        with pytest.raises(DatabaseError, match="preservation migration"):
            MigrationExecutor(connection).migrate([previous])
    finally:
        MigrationExecutor(connection).migrate(current)
    assert PrdArtifact.objects.count() == 1


def test_metadata_canonical_digest_matches_public_reference_vector():
    # JSON.stringify({a:[1,true,null,"é"],z:"fixture"}) encoded as UTF-8.
    assert metadata_digest({"z": "fixture", "a": [1, True, None, "é"]}) == (
        "sha256:" + __import__("hashlib").sha256('{"a":[1,true,null,"é"],"z":"fixture"}'.encode()).hexdigest()
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1.5, 9007199254740992, {1: "invalid-key"}])
def test_digest_rejects_values_without_a_stable_candidate_integer_encoding(value):
    with pytest.raises(ValidationError):
        metadata_digest(value)


def test_outer_command_failure_rolls_back_metadata_commit():
    artifact = artifact_fixture()
    snapshot, version = submission_records(artifact)
    with pytest.raises(RuntimeError), transaction.atomic():
        append_prd_submission_metadata(
            workspace_id=artifact.workspace_id,
            artifact_id=artifact.id,
            expected_parent_version_id=None,
            snapshot=snapshot,
            version=version,
        )
        raise RuntimeError("synthetic outbox failure")
    artifact.refresh_from_db()
    assert artifact.current_version_id is None
    assert PrdArtifactVersion.objects.count() == PrdEvidenceSnapshot.objects.count() == 0


@pytest.mark.parametrize("field", ["content", "source", "access_envelope"])
def test_raw_insert_cannot_add_inline_bodies_or_unknown_metadata_fields(field):
    item = evidence_fixture(uuid.uuid4())
    item.row_id = uuid.uuid4()
    item.evidence_id = uuid.uuid4()
    item.record["id"] = str(item.evidence_id)
    if field == "content":
        item.record[field] = "inline body is prohibited"
    else:
        item.record[field]["raw_body"] = "inline body is prohibited"
    with pytest.raises(DatabaseError), transaction.atomic():
        item.save_base(force_insert=True)
