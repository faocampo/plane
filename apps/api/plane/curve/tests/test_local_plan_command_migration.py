# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F401, F811
from importlib import import_module
import pytest
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from plane.curve.tests.test_local_plan_review_services import (
    command,
    plan,
    context,
    configuration,
    bridge,
    two_stage,
    local,
    store,
    approved,
)

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def test_retained_technical_command_prevents_reverse(local, store, approved, plan):
    command(local, store, approved, plan)
    module = import_module("plane.curve.migrations.0038_local_plan_review_commands")
    with transaction.atomic(), connection.schema_editor() as editor:
        with pytest.raises(RuntimeError, match="RETAINED_EVIDENCE"):
            module.require_empty_reverse(None, editor)


def test_empty_technical_command_migration_roundtrip():
    module = import_module("plane.curve.migrations.0038_local_plan_review_commands")
    leaves = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0037_local_plan_review_records")])
        with connection.cursor() as cursor:
            assert module._catalog(cursor) == module.BASELINE_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
        MigrationExecutor(connection).migrate([("curve", "0038_local_plan_review_commands")])
        with connection.cursor() as cursor:
            assert module._catalog(cursor) == module.CURRENT_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    finally:
        MigrationExecutor(connection).migrate(leaves)
