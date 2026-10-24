# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor

from plane.curve.models import DocumentCheckpoint, PrdArtifactVersion
from plane.curve.tests.test_prd_checkpoint_models import capture_fixture, capture_records, persist_capture

pytestmark = [pytest.mark.unit, pytest.mark.django_db]
COMMIT = "ab" * 20


def prepared(edition=2):
    binding, artifact = capture_fixture()
    snapshot, version, checkpoint = capture_records(binding, artifact)
    if edition == 2:
        version.metadata_schema_version = "2.0-candidate"
        checkpoint.metadata_schema_version = "2.0"
        version.retention_policy_version_id = checkpoint.retention_policy_version_id = COMMIT
    return artifact, snapshot, version, checkpoint


@pytest.mark.parametrize("edition", [1, 2])
def test_exact_retention_identity_round_trips_without_changing_other_fields(edition):
    artifact, snapshot, version, checkpoint = prepared(edition)
    before = (version.as_record(), checkpoint.as_record())
    persist_capture(artifact, snapshot, version, checkpoint)
    version.refresh_from_db()
    checkpoint.refresh_from_db()
    assert before == (version.as_record(), checkpoint.as_record())
    assert len(checkpoint.retention_policy_version_id) == (40 if edition == 2 else 36)


@pytest.mark.parametrize(
    "value",
    ["main", "HEAD", "a" * 12, "A" * 40, "a" * 40 + "~1", "a" * 40 + "\n", "00000000-0000-4000-8000-000000000001"],
)
def test_v2_refuses_moving_malformed_and_legacy_identifiers_in_orm_and_database(value):
    artifact, snapshot, version, checkpoint = prepared()
    version.retention_policy_version_id = checkpoint.retention_policy_version_id = value
    with pytest.raises(ValidationError):
        persist_capture(artifact, snapshot, version, checkpoint)
    artifact, snapshot, version, checkpoint = prepared()
    version.retention_policy_version_id = checkpoint.retention_policy_version_id = value
    with (
        patch.object(PrdArtifactVersion, "validate_metadata"),
        patch.object(DocumentCheckpoint, "validate_metadata"),
        pytest.raises(DatabaseError),
    ):
        persist_capture(artifact, snapshot, version, checkpoint)


def test_v1_does_not_silently_accept_commit_identity():
    artifact, snapshot, version, checkpoint = prepared(1)
    version.retention_policy_version_id = checkpoint.retention_policy_version_id = COMMIT
    with pytest.raises(ValidationError):
        persist_capture(artifact, snapshot, version, checkpoint)


def test_v2_successor_preserves_legacy_parent_and_checkpoint():
    artifact, snapshot, version, checkpoint = prepared(1)
    persist_capture(artifact, snapshot, version, checkpoint)
    original = checkpoint.as_record()
    next_snapshot, next_version, next_checkpoint = capture_records(
        checkpoint.external_document_binding, artifact, checkpoint.id
    )
    next_version.metadata_schema_version = "2.0-candidate"
    next_checkpoint.metadata_schema_version = "2.0"
    next_version.retention_policy_version_id = next_checkpoint.retention_policy_version_id = COMMIT
    persist_capture(artifact, next_snapshot, next_version, next_checkpoint)
    assert next_version.parent_version_id == version.id
    checkpoint.refresh_from_db()
    assert checkpoint.as_record() == original


def test_different_valid_policy_commits_cannot_bind_one_checkpoint_body():
    artifact, snapshot, version, checkpoint = prepared()
    checkpoint.retention_policy_version_id = "cd" * 20
    with patch.object(DocumentCheckpoint, "validate_metadata"), pytest.raises(DatabaseError):
        persist_capture(artifact, snapshot, version, checkpoint)


@pytest.mark.django_db(transaction=True)
def test_legacy_values_survive_reverse_and_forward_migration():
    artifact, snapshot, version, checkpoint = prepared(1)
    persist_capture(artifact, snapshot, version, checkpoint)
    original = checkpoint.as_record()
    latest = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0016_prd_readiness_record")])
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT retention_policy_version_id::text FROM curve_document_checkpoint WHERE id=%s", [checkpoint.id]
            )
            assert cursor.fetchone()[0] == original["retention_policy_version_id"]
    finally:
        MigrationExecutor(connection).migrate(latest)
    checkpoint.refresh_from_db()
    assert checkpoint.as_record() == original


@pytest.mark.django_db(transaction=True)
def test_reverse_refuses_retained_commit_records_without_altering_them():
    artifact, snapshot, version, checkpoint = prepared()
    persist_capture(artifact, snapshot, version, checkpoint)
    original = checkpoint.as_record()
    latest = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        with pytest.raises(DatabaseError, match="preservation migration"):
            MigrationExecutor(connection).migrate([("curve", "0016_prd_readiness_record")])
    finally:
        MigrationExecutor(connection).migrate(latest)
    checkpoint.refresh_from_db()
    assert checkpoint.as_record() == original
