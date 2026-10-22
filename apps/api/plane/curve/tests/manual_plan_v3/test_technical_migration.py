# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Exact catalog succession and retained Technical evidence rollback denial."""

# ruff: noqa: F401,F811 -- pytest fixture dependencies.
from importlib import import_module
from types import SimpleNamespace
import pytest
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from plane.curve.tests.test_scoped_prd_bridge import configuration, context, bridge
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage
from plane.curve.tests.manual_plan_v3.test_technical_decisions import native, command, execute, counts
from plane.curve.manual_gate2_v3.policy import require_edition

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def test_retained_technical_subject_prevents_reverse(native):
    migration = import_module("plane.curve.migrations.0029_technical_review_two_stage")
    execute(native, command(native, "PREPARE"))
    before = counts()
    with transaction.atomic(), pytest.raises(RuntimeError, match="TECHNICAL_V3_RETAINED_EVIDENCE_PREVENTS_REVERSE"):
        migration.require_empty_reverse(None, SimpleNamespace(connection=connection))
    assert counts() == before


def test_empty_technical_successor_roundtrip_restores_exact_catalogs():
    previous = import_module("plane.curve.migrations.0028_manual_plan_two_stage")
    current = import_module("plane.curve.migrations.0029_technical_review_two_stage")
    leaves = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0028_manual_plan_two_stage")])
        with connection.cursor() as cursor:
            assert previous._catalog(cursor) == previous.CURRENT_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    finally:
        MigrationExecutor(connection).migrate(leaves)
    with transaction.atomic(), connection.cursor() as cursor:
        assert current._catalog(cursor) == current.CURRENT_CATALOG_DIGEST
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
        require_edition()
