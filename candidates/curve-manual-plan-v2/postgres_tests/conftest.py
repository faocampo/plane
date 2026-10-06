"""Keep immutable guards active throughout tests, adapting only atomic cleanup."""

import pytest


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
