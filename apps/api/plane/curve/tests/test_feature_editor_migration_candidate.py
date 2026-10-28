# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Installed storage migration and retained-history qualification."""

import json
from importlib import import_module
from pathlib import Path

import pytest
from django.db import connection, DatabaseError, transaction

from plane.curve.tests.test_feature_editor_grant_storage import scope as grant_scope, grant, revoke, rows
from plane.curve.tests.test_feature_membership_lifetime import sql, membership as membership_fixture

scope = grant_scope
membership = membership_fixture
pytestmark = [pytest.mark.contract, pytest.mark.django_db]
ROOT = Path(__file__).resolve().parents[1] / "feature_editors"


def catalog():
    with connection.cursor() as cursor:
        return import_module("plane.curve.migrations.0045_roadmap_hierarchy_commands")._catalog(cursor)


def install_external():
    assert sql("SELECT to_regprocedure('curve_feature_editor_external_catalog()')")[0][0] is not None


def external():
    return json.loads(sql("SELECT curve_feature_editor_external_catalog()::text")[0][0])


@pytest.mark.parametrize("revoked", [False, True])
def test_reverse_preserves_any_retained_grant(scope, revoked):
    install_external()
    grant_id = grant(scope)
    if revoked:
        revoke(scope, grant_id)
    before, fingerprint = rows(), catalog()
    sql("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(DatabaseError, match="RETAINED_GRANTS_PREVENT_REVERSE"), transaction.atomic():
        sql((ROOT / "storage-reverse.sql").read_text())
    assert rows() == before
    assert catalog() == fingerprint
    assert len(external()) == 2


def test_empty_reverse_restores_exact_predecessor_catalog(scope):
    install_external()
    sql("SET CONSTRAINTS ALL IMMEDIATE")
    sql((ROOT / "coverage-reverse.sql").read_text())
    sql((ROOT / "storage-reverse.sql").read_text())
    predecessor = import_module("plane.curve.migrations.0045_roadmap_hierarchy_commands")
    assert catalog() == predecessor.CURRENT_CATALOG_DIGEST
    sql("SELECT curve_scope_reopening_verify_coverage()")
    assert sql(
        "SELECT to_regclass('curve_feature_editor_grant'), to_regclass('curve_feature_membership_lifetime')"
    ) == [(None, None)]


@pytest.mark.parametrize("operation", ["DISABLE", "DROP"])
@pytest.mark.parametrize(
    "name", ["curve_feature_membership_lifetime_track", "curve_feature_membership_lifetime_track_truncate"]
)
def test_external_fingerprint_detects_missing_or_disabled_membership_trigger(scope, operation, name):
    install_external()
    before = external()
    assert len(before) == 2
    sql("SET CONSTRAINTS ALL IMMEDIATE")
    if operation == "DROP":
        sql("DROP TRIGGER " + name + " ON workspace_members")
    else:
        sql("ALTER TABLE workspace_members DISABLE TRIGGER " + name)
    assert external() != before


def test_external_fingerprint_detects_replaced_trigger_body(scope):
    install_external()
    before = external()
    sql("""CREATE OR REPLACE FUNCTION curve_feature_membership_lifetime_track() RETURNS trigger
           LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$""")
    assert external() != before


def test_installed_successor_passes_runtime_qualification(scope):
    from plane.curve.scope_reopening_qualification import require_reopening_qualification

    require_reopening_qualification()


@pytest.mark.parametrize("operation", ["DISABLE", "DROP"])
def test_runtime_rejects_unavailable_membership_tracking(scope, operation):
    from plane.curve.scope_reopening_qualification import require_reopening_qualification
    from plane.curve.prd_commands import PrdCommandError

    sql("SET CONSTRAINTS ALL IMMEDIATE")
    if operation == "DROP":
        sql("DROP TRIGGER curve_feature_membership_lifetime_track ON workspace_members")
    else:
        sql("ALTER TABLE workspace_members DISABLE TRIGGER curve_feature_membership_lifetime_track")
    with pytest.raises(PrdCommandError, match="SCOPE_REOPENING_EDITION_UNAVAILABLE"):
        require_reopening_qualification()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("active", [True, False])
def test_registered_migration_backfills_existing_memberships_without_changing_them(membership, active):
    from django.db.migrations.executor import MigrationExecutor
    from plane.curve.tests.test_feature_membership_lifetime import generation
    from plane.db.models import WorkspaceMember

    latest = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0045_roadmap_hierarchy_commands")])
        WorkspaceMember.objects.filter(id=membership.id).update(is_active=active, company_role="Synthetic role")
        before = WorkspaceMember.objects.filter(id=membership.id).values().get()
        MigrationExecutor(connection).migrate(latest)
        assert WorkspaceMember.objects.filter(id=membership.id).values().get() == before
        assert generation(membership) == 0
        sql("SELECT curve_scope_reopening_verify_coverage()")
    finally:
        MigrationExecutor(connection).migrate(latest)
