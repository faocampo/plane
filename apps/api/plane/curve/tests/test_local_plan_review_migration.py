# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F401, F811
from importlib import import_module
import uuid
import pytest
from django.db import connection, transaction, DatabaseError
from django.db.migrations.executor import MigrationExecutor
from plane.curve.local_prd_review import _pin
from plane.curve.models import LocalPlanDecision, LocalPlanSubmission
from plane.curve.tests.test_local_plan_review_persistence import (
    records,
    context,
    configuration,
    bridge,
    two_stage,
    local,
    store,
    approved,
)

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def test_one_submission_and_decision_per_plan_and_retained_reverse(local, approved):
    submission, decision = records(local, approved)
    decision.save()
    for model, row, parent in (
        (LocalPlanSubmission, submission, submission.plan_revision),
        (LocalPlanDecision, decision, submission),
    ):
        value = row.as_record()
        value["id"] = str(uuid.uuid4())
        value["digest"] = _pin(value)
        with transaction.atomic(), pytest.raises(DatabaseError):
            model.from_record(value, parent).save()
    module = import_module("plane.curve.migrations.0037_local_plan_review_records")
    with transaction.atomic(), connection.schema_editor() as editor:
        with pytest.raises(RuntimeError, match="RETAINED_EVIDENCE"):
            module.require_empty_reverse(None, editor)


def test_empty_technical_review_migration_roundtrip():
    from django.db.migrations.executor import MigrationExecutor

    module = import_module("plane.curve.migrations.0037_local_plan_review_records")
    leaves = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0036_local_plan_upload")])
        with connection.cursor() as cursor:
            assert module._catalog(cursor) == module.BASELINE_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
        MigrationExecutor(connection).migrate([("curve", "0037_local_plan_review_records")])
        with connection.cursor() as cursor:
            assert module._catalog(cursor) == module.CURRENT_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    finally:
        MigrationExecutor(connection).migrate(leaves)
