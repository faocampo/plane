# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811
from importlib import import_module
from copy import deepcopy
import uuid
import json
import pytest
from django.db import connection, transaction, DatabaseError
from plane.curve.models import LocalPrdSubmission, LocalPrdDecision, LocalPlanRevision
from plane.curve.local_plan_review import create_plan_revision
from plane.curve.local_prd_review import _pin
from plane.curve.tests.test_scoped_prd_bridge import context, configuration, bridge  # noqa: F401
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage  # noqa: F401
from plane.curve.tests.test_local_document_authority import local  # noqa: F401
from plane.curve.tests.test_local_document_services import store  # noqa: F401
from plane.curve.tests.test_local_plan_authority import approved  # noqa: F401

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def make(local, approved, previous=None):
    source, subject, approval = approved
    record = create_plan_revision(
        submission=subject,
        approval=approval,
        initiative_version=local.initiative.version,
        version=previous.version + 1 if previous else 1,
        predecessor_id=str(previous.id) if previous else None,
        original=source["original"],
        snapshot=source["snapshot"],
        uploaded_by=str(local.user.id),
        uploaded_at="2099-01-01T00:00:00Z",
    )
    return LocalPlanRevision.from_record(
        record, LocalPrdSubmission.objects.get(id=subject["id"]), LocalPrdDecision.objects.get(id=approval["id"])
    )


def test_persists_plan_revision_chain(local, approved):
    first = make(local, approved)
    first.save()
    first.refresh_from_db()
    first.validate_metadata()
    second = make(local, approved, first)
    second.save()
    second.refresh_from_db()
    second.validate_metadata()
    assert second.predecessor_id == first.id and second.version == 2


@pytest.mark.parametrize("damage", ["approval_digest", "scope", "missing_predecessor", "bad_snapshot", "extra_field"])
def test_direct_database_writes_cannot_forge_plan_identity(local, approved, damage):
    record = make(local, approved)
    value = deepcopy(record.payload)
    if damage == "approval_digest":
        value["prd_decision_digest"] = "sha256:" + "0" * 64
    elif damage == "scope":
        value["workspace_id"] = str(uuid.uuid4())
    elif damage == "missing_predecessor":
        value.pop("predecessor_id")
    elif damage == "bad_snapshot":
        value["snapshot"]["media_type"] = "text/plain"
    else:
        value["hidden"] = "not permitted"
    value["digest"] = _pin(value)
    record.payload = value
    record.digest = value["digest"]
    with transaction.atomic(), pytest.raises(DatabaseError):
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO curve_local_plan_revision (id,workspace_id,initiative_id,"
                "prd_submission_id,prd_decision_id,"
                "predecessor_id,version,initiative_version,digest,payload) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                [
                    record.id,
                    record.workspace_id,
                    record.initiative_id,
                    record.prd_submission_id,
                    record.prd_decision_id,
                    record.predecessor_id,
                    record.version,
                    record.initiative_version,
                    record.digest,
                    json.dumps(record.payload),
                ],
            )


@pytest.mark.parametrize("mutation", ["update", "delete", "truncate"])
def test_database_preserves_saved_revision(local, approved, mutation):
    record = make(local, approved)
    record.save()
    with transaction.atomic(), pytest.raises(DatabaseError), connection.cursor() as cursor:
        cursor.execute(
            {
                "update": "UPDATE curve_local_plan_revision SET version=2",
                "delete": "DELETE FROM curve_local_plan_revision",
                "truncate": "TRUNCATE curve_local_plan_revision CASCADE",
            }[mutation]
        )
    assert LocalPlanRevision.objects.count() == 1


def test_reverse_refuses_retained_plan(local, approved):
    make(local, approved).save()
    module = import_module("plane.curve.migrations.0035_local_plan_revision")
    with (
        transaction.atomic(),
        connection.schema_editor() as editor,
        pytest.raises(RuntimeError, match="RETAINED_EVIDENCE"),
    ):
        module.require_empty_reverse(None, editor)


def test_empty_plan_migration_roundtrip():
    from django.db.migrations.executor import MigrationExecutor

    module = import_module("plane.curve.migrations.0035_local_plan_revision")
    leaves = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0034_local_review_commands")])
        with connection.cursor() as cursor:
            assert module._catalog(cursor) == module.BASELINE_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
        MigrationExecutor(connection).migrate([("curve", "0035_local_plan_revision")])
        with connection.cursor() as cursor:
            assert module._catalog(cursor) == module.CURRENT_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    finally:
        MigrationExecutor(connection).migrate(leaves)
