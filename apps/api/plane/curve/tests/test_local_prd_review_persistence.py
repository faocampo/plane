# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811
from copy import deepcopy
from importlib import import_module
import json
import uuid
import pytest
from django.db import connection, transaction, DatabaseError
from plane.curve.models import LocalPrdSource, LocalPrdSubmission, LocalPrdDecision, ImmutableRecordError
from plane.curve.local_prd_review import create_submission, create_decision, _pin
from plane.curve.tests.test_project_association_api import context  # noqa: F401
from plane.curve.tests.test_local_document_persistence import uploaded  # noqa: F401

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def submission(uploaded):
    source = LocalPrdSource.from_record(uploaded())
    source.save()
    reviewers = [
        dict(gate_type=gate, gate_assignment_id=str(uuid.uuid4()), approver_user_id=str(uuid.uuid4()))
        for gate in ("PLAN_APPROVAL", "PRD_APPROVAL")
    ]
    value = create_submission(
        source=source.as_record(),
        initiative_version=2,
        scope_revision_id=str(uuid.uuid4()),
        scope_revision=1,
        membership_digest="sha256:" + "a" * 64,
        reviewers=reviewers,
        risk_tier="STANDARD",
        submitted_by=str(source.uploaded_by),
        submitted_at="2026-10-21T12:01:00Z",
    )
    record = LocalPrdSubmission.from_record(value)
    record.save()
    return record


def decision(submission):
    return create_decision(
        submission=submission.as_record(),
        initiative_version=3,
        state="APPROVED",
        decided_by=submission.payload["reviewers"][1]["approver_user_id"],
        decided_at="2026-10-21T12:02:00Z",
    )


def insert_raw_submission(value):
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_local_prd_submission"
            "(id,workspace_id,initiative_id,source_id,initiative_version,digest,payload) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)",
            [value[k] for k in ("id", "workspace_id", "initiative_id", "source_id", "initiative_version", "digest")]
            + [json.dumps(value)],
        )


def insert_raw_decision(value):
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_local_prd_decision"
            "(id,workspace_id,initiative_id,submission_id,initiative_version,state,digest,payload) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
            [
                value[k]
                for k in (
                    "id",
                    "workspace_id",
                    "initiative_id",
                    "submission_id",
                    "initiative_version",
                    "state",
                    "digest",
                )
            ]
            + [json.dumps(value)],
        )


def test_submission_and_decision_persist_exact_records(submission):
    item = LocalPrdDecision.from_record(decision(submission), submission)
    item.save()
    item.refresh_from_db()
    item.validate_metadata()
    assert str(item.submission_id) == str(submission.id)
    assert item.as_record()["source_digest"] == submission.payload["source_digest"]
    with pytest.raises(ImmutableRecordError):
        item.save()
    with pytest.raises(ImmutableRecordError):
        submission.delete()


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", None),
        ("source_digest", "sha256:" + "b" * 64),
        ("content_digest", "sha256:" + "b" * 64),
        ("risk_tier", "INVALID"),
        ("reviewers", []),
    ],
)
def test_database_rejects_rehashed_invalid_submission(submission, field, value):
    changed = deepcopy(submission.payload)
    changed.update(id=str(uuid.uuid4()), initiative_version=4)
    changed[field] = value
    changed["digest"] = _pin(changed)
    with pytest.raises(DatabaseError), transaction.atomic():
        insert_raw_submission(changed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", None),
        ("source_digest", "sha256:" + "b" * 64),
        ("decided_by", "00000000-0000-4000-8000-000000000001"),
        ("state", "CHANGES_REQUESTED"),
        ("initiative_version", 2),
    ],
)
def test_database_rejects_rehashed_invalid_decision(submission, field, value):
    changed = decision(submission)
    changed[field] = value
    changed["digest"] = _pin(changed)
    with pytest.raises(DatabaseError), transaction.atomic():
        insert_raw_decision(changed)


def test_one_decision_per_submission(submission):
    first = LocalPrdDecision.from_record(decision(submission), submission)
    first.save()
    second = decision(submission)
    second["initiative_version"] = 4
    second["digest"] = _pin(second)
    with pytest.raises(DatabaseError), transaction.atomic():
        insert_raw_decision(second)


@pytest.mark.parametrize("table", ["curve_local_prd_submission", "curve_local_prd_decision"])
def test_sql_erasure_and_rewrite_are_rejected(submission, table):
    item = LocalPrdDecision.from_record(decision(submission), submission)
    item.save()
    for statement in (f"DELETE FROM {table}", f"UPDATE {table} SET digest=digest", f"TRUNCATE {table} CASCADE"):
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(statement)


def test_reverse_refuses_retained_review(submission):
    module = import_module("plane.curve.migrations.0032_local_prd_review")
    with (
        pytest.raises(RuntimeError, match="RETAINED_EVIDENCE"),
        transaction.atomic(),
        connection.schema_editor() as editor,
    ):
        module.require_empty_reverse(None, editor)


def test_changes_requested_persists_private_feedback_reference(submission):
    value = create_decision(
        submission=submission.as_record(),
        initiative_version=3,
        state="CHANGES_REQUESTED",
        decided_by=submission.payload["reviewers"][1]["approver_user_id"],
        decided_at="2026-10-21T12:02:00Z",
        feedback=dict(object_id=str(uuid.uuid4()), digest="sha256:" + "b" * 64, size_bytes=24, media_type="text/plain"),
    )
    item = LocalPrdDecision.from_record(value, submission)
    item.save()
    item.refresh_from_db()
    item.validate_metadata()
    assert item.state == "CHANGES_REQUESTED"


def test_cross_workspace_raw_submission_is_rejected(submission):
    value = deepcopy(submission.payload)
    value.update(id=str(uuid.uuid4()), workspace_id=str(uuid.uuid4()), initiative_version=5)
    value["digest"] = _pin(value)
    with pytest.raises(DatabaseError), transaction.atomic():
        insert_raw_submission(value)


def test_empty_migration_roundtrip_restores_exact_catalog():
    from django.db.migrations.executor import MigrationExecutor

    module = import_module("plane.curve.migrations.0032_local_prd_review")
    leaves = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0031_local_prd_command")])
        with connection.cursor() as cursor:
            assert module._catalog(cursor) == module.BASELINE_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
        MigrationExecutor(connection).migrate([("curve", "0032_local_prd_review")])
        with connection.cursor() as cursor:
            assert module._catalog(cursor) == module.CURRENT_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    finally:
        MigrationExecutor(connection).migrate(leaves)
