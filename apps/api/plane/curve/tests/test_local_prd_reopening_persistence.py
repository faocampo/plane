# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811
from importlib import import_module
import json
import uuid
import pytest
from django.db import connection, transaction, DatabaseError
from plane.curve.models import LocalPrdSubmission, LocalPrdDecision, LocalPrdReopening
from plane.curve.local_prd_review import _pin
from plane.curve.local_prd_reopening import create_reopening
from plane.curve.local_document_store import LocalDocumentUnavailable
from plane.curve.tests.test_scoped_prd_bridge import context, configuration, bridge  # noqa: F401
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage  # noqa: F401
from plane.curve.tests.test_local_document_authority import local  # noqa: F401
from plane.curve.tests.test_local_document_services import store  # noqa: F401
from plane.curve.tests.test_local_plan_authority import approved  # noqa: F401

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def make(local, approved):
    _, subject, decision = approved
    return LocalPrdReopening.from_record(
        create_reopening(
            submission=subject,
            decision=decision,
            initiative_version=local.initiative.version,
            reopened_by=str(local.user.id),
            reopened_at="2099-01-01T00:00:00Z",
        ),
        LocalPrdSubmission.objects.get(id=subject["id"]),
        LocalPrdDecision.objects.get(id=decision["id"]),
    )


def raw(record):
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_local_prd_reopening(id,workspace_id,initiative_id,submission_id,decision_id,"
            "initiative_version,digest,payload) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
            [
                record.id,
                record.workspace_id,
                record.initiative_id,
                record.submission_id,
                record.decision_id,
                record.initiative_version,
                record.digest,
                json.dumps(record.payload),
            ],
        )


def test_retains_approved_history_and_rejects_a_second_reopening(local, approved):
    record = make(local, approved)
    record.save()
    record.refresh_from_db()
    record.validate_metadata()
    assert record.as_record()["decision_digest"] == approved[2]["digest"]
    assert LocalPrdDecision.objects.get(id=record.decision_id).state == "APPROVED"
    with transaction.atomic(), pytest.raises(DatabaseError):
        make(local, approved).save()
    module = import_module("plane.curve.migrations.0039_local_prd_reopening")
    with transaction.atomic(), connection.schema_editor() as editor:
        with pytest.raises(RuntimeError, match="RETAINED_EVIDENCE"):
            module.require_empty_reverse(None, editor)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", "00000000-0000-4000-8000-000000000001"),
        ("source_digest", "sha256:" + "a" * 64),
        ("submission_digest", "sha256:" + "a" * 64),
        ("decision_digest", "sha256:" + "a" * 64),
        ("reopened_by", "00000000-0000-4000-8000-000000000001"),
        ("reopened_at", "2000-01-01T00:00:00Z"),
        ("extra", "unexpected"),
    ],
)
def test_rehashed_raw_forgery_is_rejected(local, approved, field, value):
    record = make(local, approved)
    record.payload[field] = value
    record.digest = record.payload["digest"] = _pin(record.payload)
    with transaction.atomic(), pytest.raises(DatabaseError):
        raw(record)


def test_rehashed_stale_initiative_version_is_rejected(local, approved):
    record = make(local, approved)
    record.initiative_version += 1
    record.payload["initiative_version"] = record.initiative_version
    record.digest = record.payload["digest"] = _pin(record.payload)
    with transaction.atomic(), pytest.raises(DatabaseError):
        raw(record)


@pytest.mark.parametrize("mutation", ["update", "delete", "truncate"])
def test_reopening_is_append_only(local, approved, mutation):
    make(local, approved).save()
    with transaction.atomic(), pytest.raises(DatabaseError), connection.cursor() as cursor:
        cursor.execute(
            {
                "update": "UPDATE curve_local_prd_reopening SET initiative_version=initiative_version+1",
                "delete": "DELETE FROM curve_local_prd_reopening",
                "truncate": "TRUNCATE curve_local_prd_reopening",
            }[mutation]
        )


def test_model_column_and_payload_must_match(local, approved):
    record = make(local, approved)
    record.id = uuid.uuid4()
    with pytest.raises(LocalDocumentUnavailable):
        record.validate_metadata()


def test_empty_reopening_migration_roundtrip():
    from django.db.migrations.executor import MigrationExecutor

    module = import_module("plane.curve.migrations.0039_local_prd_reopening")
    leaves = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0038_local_plan_review_commands")])
        with connection.cursor() as cursor:
            assert module._catalog(cursor) == module.BASELINE_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
        MigrationExecutor(connection).migrate([("curve", "0039_local_prd_reopening")])
        with connection.cursor() as cursor:
            assert module._catalog(cursor) == module.CURRENT_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    finally:
        MigrationExecutor(connection).migrate(leaves)
