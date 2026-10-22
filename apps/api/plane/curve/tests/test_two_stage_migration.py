# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from importlib import import_module

import pytest
from django.db import connection, DatabaseError, transaction

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def test_successor_catalog_matches_qualified_pin_and_retains_predecessor_seals():
    migration = import_module("plane.curve.migrations.0026_two_stage_approval_policy")
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT catalog_digest FROM curve_two_stage_v2_coverage WHERE edition='CURVE_TWO_STAGE_REVIEW_V2'"
        )
        assert cursor.fetchone()[0] == migration.CURRENT_CATALOG_DIGEST
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
        for table in (
            "curve_scope_reopening_coverage",
            "curve_manual_plan_v2_coverage",
            "curve_manual_gate2_v2_coverage",
        ):
            cursor.execute(f"SELECT count(*) FROM {table}")
            assert cursor.fetchone()[0] == 1


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO curve_two_stage_v2_coverage VALUES ('other', 'invalid')",
        "UPDATE curve_two_stage_v2_coverage SET catalog_digest='invalid'",
        "DELETE FROM curve_two_stage_v2_coverage",
        "TRUNCATE curve_two_stage_v2_coverage",
    ],
)
def test_successor_seal_is_immutable(statement):
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(statement)
    with connection.cursor() as cursor:
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def test_catalog_drift_denies_and_rollback_restores_verification():
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("CREATE INDEX curve_two_stage_drift_probe ON curve_initiative(title)")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    with connection.cursor() as cursor:
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
