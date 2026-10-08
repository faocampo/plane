# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Prospective installed smoke tests, not sufficient alone for qualification.

This file intentionally fails when the reviewed 0024/proof are missing. It never
patches the proof, supplies observed hashes, or skips an unavailable edition.
"""

from importlib import import_module
from io import StringIO

import pytest
from django.db import DatabaseError, connection, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.core.management import call_command

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def qualified_candidate():
    assert connection.vendor == "postgresql"
    assert MigrationRecorder.Migration.objects.filter(app="curve", name="0024_manual_draft_reconstruction").exists()
    migration = import_module("plane.curve.migrations.0024_manual_draft_reconstruction")
    assert migration.CURRENT_CATALOG_DIGEST is not None
    root = import_module("plane.curve.scope_reopening_qualification")
    require = getattr(root, "require_manual_plan_v2_qualification", None)
    assert callable(require), "Reviewed successor loader is required"
    with transaction.atomic():
        require()
    return migration


def test_historical_and_successor_seals_are_distinct_and_exact(qualified_candidate):
    with connection.cursor() as cursor:
        cursor.execute("SELECT edition,catalog_digest FROM curve_scope_reopening_coverage")
        assert cursor.fetchall() == [("CURVE_PRE_PLAN_C2B_V1", qualified_candidate.BASELINE_CATALOG_DIGEST)]
        cursor.execute("SELECT edition,catalog_digest FROM curve_manual_plan_v2_coverage")
        assert cursor.fetchall() == [
            ("CURVE_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2", qualified_candidate.CURRENT_CATALOG_DIGEST)
        ]
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


@pytest.mark.parametrize(
    "table", ["curve_manual_plan_revision_v2", "curve_manual_plan_draft_v2", "curve_manual_plan_v2_coverage"]
)
def test_direct_truncate_is_rejected_even_without_records(qualified_candidate, table):
    # Static allowlisted table names only; no request-derived identifier.
    with pytest.raises(DatabaseError):
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("TRUNCATE " + table + " CASCADE")


def test_direct_seal_rewrite_is_rejected(qualified_candidate):
    with pytest.raises(DatabaseError):
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("UPDATE curve_manual_plan_v2_coverage SET catalog_digest=%s", ["sha256:" + "0" * 64])


def test_registered_models_match_migration_state(qualified_candidate):
    call_command("makemigrations", "curve", dry_run=True, check=True, interactive=False, stdout=StringIO())
