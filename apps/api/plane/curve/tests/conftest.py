# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Keep immutable-ledger TRUNCATE protection active outside Django test teardown.

Django's PostgreSQL execute_sql_flush() executes its entire generated SQL list in
one transaction.atomic() block, with rollback-safe DDL. Only that generated list
is adapted here: disable the ledger's statement-level TRUNCATE trigger, execute
Django's original fixture cleanup, and enable/check the trigger before commit.
The unmanaged coverage seal is never flushed. There is no application setting,
raw-SQL interception, or test-body interval in which the protection is disabled.
"""

import pytest


@pytest.fixture(scope="session", autouse=True)
def immutable_reopening_ledger_test_teardown():
    from django.db.backends.postgresql.operations import DatabaseOperations

    original = DatabaseOperations.sql_flush

    def sql_flush(operations, style, tables, *, reset_sequences=False, allow_cascade=False):
        statements = original(operations, style, tables, reset_sequences=reset_sequences, allow_cascade=allow_cascade)
        if "curve_scope_reopening" not in tables:
            return statements
        assert "curve_scope_reopening_coverage" not in tables, "Immutable coverage seal must survive fixture cleanup"
        return [
            """DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_trigger
                WHERE tgrelid='curve_scope_reopening'::regclass
                  AND tgname='curve_reopen_no_truncate' AND tgenabled='O') THEN
                RAISE EXCEPTION 'Reopening TRUNCATE guard was not enabled before fixture cleanup';
              END IF;
            END $$;""",
            "ALTER TABLE curve_scope_reopening DISABLE TRIGGER curve_reopen_no_truncate;",
            *statements,
            "ALTER TABLE curve_scope_reopening ENABLE TRIGGER curve_reopen_no_truncate;",
            """DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_trigger
                WHERE tgrelid='curve_scope_reopening'::regclass
                  AND tgname='curve_reopen_no_truncate' AND tgenabled='O') THEN
                RAISE EXCEPTION 'Reopening TRUNCATE guard was not restored after fixture cleanup';
              END IF;
              PERFORM curve_scope_reopening_verify_coverage();
            END $$;""",
        ]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(DatabaseOperations, "sql_flush", sql_flush)
        yield


@pytest.fixture(scope="session", autouse=True)
def manual_draft_test_teardown(immutable_reopening_ledger_test_teardown):
    from django.db.backends.postgresql.operations import DatabaseOperations

    original = DatabaseOperations.sql_flush

    def sql_flush(operations, style, tables, *, reset_sequences=False, allow_cascade=False):
        statements = original(operations, style, tables, reset_sequences=reset_sequences, allow_cascade=allow_cascade)
        if "curve_manual_plan_draft_v2" not in tables:
            return statements
        assert "curve_manual_plan_v2_coverage" not in tables
        guards = (
            ("curve_manual_plan_draft_v2", "curve_mpd2_no_truncate"),
            ("curve_manual_plan_revision_v2", "curve_mpr2_no_truncate"),
        )

        def verify(table, name):
            return f"""DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid='{table}'::regclass
                AND tgname='{name}' AND tgenabled='O') THEN
                RAISE EXCEPTION 'Manual draft TRUNCATE guard missing during test cleanup';
              END IF;
            END $$;"""

        # Restore these guards immediately after Django's TRUNCATE, before the
        # incumbent wrapper restores its own guard and verifies the whole catalog.
        result = []
        for statement in statements:
            if statement.lstrip().upper().startswith("TRUNCATE "):
                result.extend(verify(table, name) for table, name in guards)
                result.extend(f"ALTER TABLE {table} DISABLE TRIGGER {name};" for table, name in guards)
                result.append(statement)
                result.extend(f"ALTER TABLE {table} ENABLE TRIGGER {name};" for table, name in guards)
                result.extend(verify(table, name) for table, name in guards)
            else:
                result.append(statement)
        return result

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(DatabaseOperations, "sql_flush", sql_flush)
        yield


@pytest.fixture(scope="session", autouse=True)
def manual_gate2_test_teardown(manual_draft_test_teardown):
    from django.db.backends.postgresql.operations import DatabaseOperations

    original = DatabaseOperations.sql_flush
    guards = [
        ("curve_manual_gate2_control_v2", "curve_mg2c_no_truncate"),
        ("curve_manual_gate2_record_v2", "curve_mg2r_no_truncate"),
        ("curve_manual_task_claim_v2", "curve_mtc2_no_truncate"),
        ("curve_manual_task_claim_history_v2", "curve_mtch2_no_truncate"),
    ]

    def sql_flush(operations, style, tables, *, reset_sequences=False, allow_cascade=False):
        statements = original(operations, style, tables, reset_sequences=reset_sequences, allow_cascade=allow_cascade)
        if "curve_manual_gate2_record_v2" not in tables:
            return statements
        assert "curve_manual_gate2_v2_coverage" not in tables
        result = []
        for statement in statements:
            if statement.lstrip().upper().startswith("TRUNCATE "):
                for table, name in guards:
                    result.append(
                        f"DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='{table}'::regclass "
                        f"AND tgname='{name}' AND tgenabled='O') THEN RAISE EXCEPTION "
                        "'Gate2 guard missing before fixture cleanup'; END IF; END $$;"
                    )
                    result.append(f"ALTER TABLE {table} DISABLE TRIGGER {name};")
                result.append(statement)
                for table, name in guards:
                    result.append(f"ALTER TABLE {table} ENABLE TRIGGER {name};")
                    result.append(
                        f"DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='{table}'::regclass "
                        f"AND tgname='{name}' AND tgenabled='O') THEN RAISE EXCEPTION "
                        "'Gate2 guard missing after fixture cleanup'; END IF; END $$;"
                    )
            else:
                result.append(statement)
        return result

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(DatabaseOperations, "sql_flush", sql_flush)
        yield
