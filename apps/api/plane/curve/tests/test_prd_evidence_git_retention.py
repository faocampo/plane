# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid
from copy import deepcopy

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from plane.curve.models import PrdEvidenceItemVersion
from plane.curve.prd_metadata_repository import append_prd_submission_metadata
from plane.curve.prd_metadata_validation import metadata_digest
from plane.curve.tests.test_prd_metadata_models import (
    artifact_fixture,
    evidence_fixture,
    snapshot_entry,
    submission_records,
)

pytestmark = [pytest.mark.unit, pytest.mark.django_db]
COMMIT = "ab" * 20


def successor(legacy):
    record = deepcopy(legacy.record)
    record["schema_version"] = "2.0-candidate"
    record["version"] = legacy.version + 1
    record["retention_policy_version_id"] = COMMIT
    envelope = record["access_envelope"]
    envelope["effective_principal"] = deepcopy(envelope["effective_principal"])
    envelope["schema_version"] = "2.0"
    envelope["id"] = str(uuid.uuid4())
    envelope["retention_policy_ref"]["resource_id"] = COMMIT
    return PrdEvidenceItemVersion(
        evidence_id=legacy.evidence_id,
        workspace_id=legacy.workspace_id,
        version=record["version"],
        provider_connection=legacy.provider_connection,
        record=record,
        envelope_digest=metadata_digest(envelope),
    )


def test_v2_evidence_successor_keeps_historical_envelope_and_snapshot_digests():
    artifact = artifact_fixture()
    legacy = evidence_fixture(artifact.workspace_id)
    original = (deepcopy(legacy.record), legacy.envelope_digest)
    snapshot, version = submission_records(artifact, [snapshot_entry(legacy)])
    append_prd_submission_metadata(
        workspace_id=artifact.workspace_id,
        artifact_id=artifact.id,
        expected_parent_version_id=None,
        snapshot=snapshot,
        version=version,
    )
    snapshot_original = snapshot.as_record()
    item = successor(legacy)
    item.save()
    item.refresh_from_db()
    assert item.envelope_digest == metadata_digest(item.record["access_envelope"])
    assert item.envelope_digest != legacy.envelope_digest
    artifact.refresh_from_db()
    next_snapshot, next_version = submission_records(artifact, [snapshot_entry(item)])
    next_version.metadata_schema_version = "2.0-candidate"
    next_version.retention_policy_version_id = COMMIT
    append_prd_submission_metadata(
        workspace_id=artifact.workspace_id,
        artifact_id=artifact.id,
        expected_parent_version_id=version.id,
        snapshot=next_snapshot,
        version=next_version,
    )
    legacy.refresh_from_db()
    snapshot.refresh_from_db()
    assert (legacy.record, legacy.envelope_digest) == original
    assert snapshot.as_record() == snapshot_original
    assert next_snapshot.items[0]["access_envelope_digest"] == item.envelope_digest


@pytest.mark.parametrize("value", ["main", "HEAD", "a" * 12, "A" * 40, "a" * 40 + "\n", None, 7])
def test_invalid_commit_rejected_by_orm_and_direct_insert(value):
    item = successor(evidence_fixture(uuid.uuid4()))
    item.record["retention_policy_version_id"] = value
    item.record["access_envelope"]["retention_policy_ref"]["resource_id"] = value
    with pytest.raises(ValidationError):
        item.save()
    with pytest.raises(DatabaseError), transaction.atomic():
        item.save_base(force_insert=True)


@pytest.mark.parametrize(
    "mutation", ["edition", "commit", "type", "counter", "raw", "principal", "classification", "redaction", "source"]
)
def test_v2_envelope_mismatch_and_extra_retention_fields_are_rejected(mutation):
    item = successor(evidence_fixture(uuid.uuid4()))
    envelope = item.record["access_envelope"]
    ref = envelope["retention_policy_ref"]
    if mutation == "edition":
        envelope["schema_version"] = "1.0"
    elif mutation == "commit":
        ref["resource_id"] = "cd" * 20
    elif mutation == "type":
        ref["resource_type"] = "ARTIFACT"
    elif mutation == "counter":
        ref["resource_version"] = 1
    elif mutation == "raw":
        ref["raw_body"] = "Synthetic prohibited body"
    elif mutation == "principal":
        envelope["effective_principal"]["actor_id"] = str(uuid.uuid4())
    elif mutation == "classification":
        envelope["classification"] = "RESTRICTED"
    elif mutation == "redaction":
        envelope["redaction_state"] = "REDACTED"
    else:
        envelope["source_refs"] = []
    with pytest.raises(ValidationError):
        item.save()
    with pytest.raises(DatabaseError), transaction.atomic():
        item.save_base(force_insert=True)


@pytest.mark.django_db(transaction=True)
def test_legacy_envelope_is_unchanged_across_migration_round_trip():
    item = evidence_fixture(uuid.uuid4())
    original = (deepcopy(item.record), item.envelope_digest)
    latest = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0018_prd_rationale_git_retention")])
        item.refresh_from_db()
        assert (item.record, item.envelope_digest) == original
        # The restored guard continues rejecting v2 direct inserts.
        with pytest.raises(DatabaseError), transaction.atomic():
            successor(item).save_base(force_insert=True)
    finally:
        MigrationExecutor(connection).migrate(latest)
    item.refresh_from_db()
    assert (item.record, item.envelope_digest) == original


@pytest.mark.django_db(transaction=True)
def test_reverse_refuses_retained_v2_evidence_without_rewriting_it():
    item = successor(evidence_fixture(uuid.uuid4()))
    item.save()
    original = (deepcopy(item.record), item.envelope_digest)
    latest = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        with pytest.raises(DatabaseError, match="preservation migration"):
            MigrationExecutor(connection).migrate([("curve", "0018_prd_rationale_git_retention")])
    finally:
        MigrationExecutor(connection).migrate(latest)
    item.refresh_from_db()
    assert (item.record, item.envelope_digest) == original
