"""Transactional DDL experiment, explicitly distinct from installed qualification.

The unset production gate is tested, never patched. Only the declared DDL/state
operations are exercised and reversed in a disposable test transaction. No seal
value, successor proof, migration recorder entry or runtime module is installed.
"""

import base64
from importlib import import_module, util
import json
from pathlib import Path
import zlib

import pytest
from django.db import DatabaseError, connection, migrations, transaction
from django.db.migrations.loader import MigrationLoader

ROOT = Path(__file__).resolve().parents[1]
pytestmark = [pytest.mark.contract, pytest.mark.django_db]
NEW_TABLES = {
    "curve_manual_plan_draft_v2",
    "curve_manual_plan_revision_v2",
    "curve_manual_plan_v2_coverage",
}
NEW_FUNCTIONS = {
    "curve_mpd2_shape",
    "curve_mpd2_schema",
    "curve_mpd2_immutable",
    "curve_mpd2_head_guard",
    "curve_mpr2_insert_guard",
    "curve_mpr2_commit_guard",
}
FOREIGN_KEYS = {
    "curve_mpd2_init_fk",
    "curve_mpd2_revision_fk",
    "curve_mpr2_draft_fk",
    "curve_mpr2_previous_fk",
    "curve_mpr2_policy_fk",
    "curve_mpr2_event_fk",
}


def candidate():
    spec = util.spec_from_file_location(
        "manual_ddl_experiment", ROOT / "overlay/migrations/0024_manual_draft_reconstruction.py"
    )
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def catalog():
    predecessor = import_module("plane.curve.migrations.0023_scope_reopening")
    with connection.cursor() as cursor:
        cursor.execute("SHOW search_path")
        previous_path = cursor.fetchone()[0]
        cursor.execute("SET LOCAL search_path = pg_catalog, public")
        cursor.execute(predecessor.CATALOG_SQL)
        value = cursor.fetchone()[0]
        cursor.execute(
            "SELECT 'sha256:' || encode(sha256(convert_to((" + predecessor.CATALOG_SQL + ")::text,'UTF8')),'hex')"
        )
        digest = cursor.fetchone()[0]
        cursor.execute("SELECT set_config('search_path', %s, true)", [previous_path])
        return json.loads(value) if isinstance(value, str) else value, digest


def normalized(row):
    return json.dumps(row, sort_keys=True, separators=(",", ":"))


def checked_delta(before, after):
    delta = {}
    for section in before:
        old = {normalized(row): row for row in before[section]}
        new = {normalized(row): row for row in after[section]}
        removed = [old[key] for key in sorted(old.keys() - new.keys())]
        added = [new[key] for key in sorted(new.keys() - old.keys())]
        delta[section] = dict(removed=removed, added=added)
        for row in removed:
            assert (
                section == "constraints"
                and row["table_name"] == "curve_policy_decision"
                and row["name"] == "curve_policy_identity_ck"
            ) or (section == "functions" and row["name"] == "curve_scope_reopening_verify_coverage"), row
        for row in added:
            assert row["schema"] == "public"
            if section == "tables":
                assert row["name"] in NEW_TABLES
            elif section == "functions":
                assert row["name"] in NEW_FUNCTIONS | {"curve_scope_reopening_verify_coverage"}
            elif row["table_name"] not in NEW_TABLES:
                assert (
                    section == "constraints"
                    and row["table_name"] == "curve_policy_decision"
                    and row["name"] == "curve_policy_identity_ck"
                ) or (section == "triggers" and row["internal"] is True and row["constraint_name"] in FOREIGN_KEYS), row
    assert {row["name"] for row in delta["tables"]["added"]} == NEW_TABLES
    assert {row["name"] for row in delta["functions"]["added"]} == NEW_FUNCTIONS | {
        "curve_scope_reopening_verify_coverage"
    }
    return delta


def test_declared_ddl_delta_and_empty_reverse_preserve_the_original_catalog():
    assert connection.vendor == "postgresql"
    module = candidate()
    assert module.CURRENT_CATALOG_DIGEST is None
    before, before_digest = catalog()
    assert before_digest == module.BASELINE_CATALOG_DIGEST
    with pytest.raises(RuntimeError, match="POSTGRESQL_QUALIFICATION_REQUIRED"):
        module.verify_predecessor(None, None)
    assert catalog() == (before, before_digest)
    state = MigrationLoader(connection).project_state()
    applied = []
    # The complete migration remains blocked. This explicit subset tests DDL,
    # never equates the observed catalog with an approved/installed successor.
    operations = module.Migration.operations
    assert operations[0].code is module.verify_predecessor
    assert operations[-1].code is module.verify_successor
    with connection.schema_editor(atomic=False) as editor:
        for operation in operations[1:-1]:
            if isinstance(operation, migrations.RunPython):
                assert operation.code is module.install_seal
                continue
            old_state = state.clone()
            operation.state_forwards("curve", state)
            operation.database_forwards("curve", editor, old_state, state)
            applied.append((operation, old_state, state.clone()))
        for sql in editor.deferred_sql:
            editor.execute(sql)
        editor.deferred_sql = []
        after, after_digest = catalog()
        delta = checked_delta(before, after)
        assert after_digest != before_digest
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM curve_manual_plan_v2_coverage")
            assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT name FROM django_migrations WHERE app='curve' ORDER BY name")
            assert [row[0] + ".py" for row in cursor.fetchall()] == sorted(module.PREDECESSOR_MIGRATIONS)
        for statement in (
            "SELECT curve_scope_reopening_verify_coverage()",
            "TRUNCATE curve_manual_plan_revision_v2 CASCADE",
            "TRUNCATE curve_manual_plan_draft_v2 CASCADE",
            "TRUNCATE curve_manual_plan_v2_coverage CASCADE",
            "INSERT INTO curve_manual_plan_v2_coverage VALUES ('unqualified','sha256:unqualified')",
        ):
            with pytest.raises(DatabaseError):
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute(statement)
        module.require_empty_reverse(state.apps, editor)
        for operation, old_state, new_state in reversed(applied):
            operation.database_backwards("curve", editor, new_state, old_state)
        assert not editor.deferred_sql
        assert catalog() == (before, before_digest)
        module.verify_empty_predecessor(state.apps, editor)
    evidence = dict(
        status="EXPERIMENT_ONLY_NOT_QUALIFIED",
        baseline_catalog_digest=before_digest,
        observed_candidate_catalog_digest=after_digest,
        delta=delta,
        empty_reverse_restored_exact_catalog=True,
    )
    encoded = base64.b64encode(zlib.compress(json.dumps(evidence, sort_keys=True).encode())).decode()
    print("CATALOG_REVIEW_EVIDENCE=" + encoded)
