# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from importlib import import_module
from pathlib import Path

import pytest
from django.db import connection, transaction, DatabaseError
from django.db.migrations.executor import MigrationExecutor

from plane.curve.prd_commands import PrdCommandError
from plane.curve.scope_reopening_qualification import require_feature_command_qualification
from plane.curve.tests.test_feature_commands import command, counts
from plane.curve.tests.test_roadmap_commands import scope as roadmap_scope

scope = roadmap_scope
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def test_empty_command_migration_reverses_to_exact_editor_catalog(scope):
    predecessor = import_module("plane.curve.migrations.0047_feature_editor_commands")
    with transaction.atomic():
        executor = MigrationExecutor(connection)
        executor.migrate([("curve", "0047_feature_editor_commands")])
        with connection.cursor() as cursor:
            assert predecessor._catalog(cursor) == predecessor.CURRENT_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
        transaction.set_rollback(True)
    with transaction.atomic():
        require_feature_command_qualification()


def test_retained_command_policy_prevents_reversal(scope):
    command(scope)
    before = counts(scope)
    with pytest.raises(RuntimeError, match="RETAINED_EVIDENCE_PREVENTS_REVERSE"):
        with transaction.atomic():
            MigrationExecutor(connection).migrate([("curve", "0047_feature_editor_commands")])
    assert counts(scope) == before
    with transaction.atomic():
        require_feature_command_qualification()


@pytest.mark.parametrize(
    "name", ["command-policy-v1.json", "command-event-v1.schema.json", "command-coverage-forward.sql"]
)
def test_cached_modules_do_not_hide_changed_contract_bytes(scope, monkeypatch, name):
    with transaction.atomic():
        require_feature_command_qualification()
    original = Path.read_bytes

    def read(path):
        value = original(path)
        return value + b" " if path.name == name else value

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", read)
        with transaction.atomic(), pytest.raises(PrdCommandError):
            require_feature_command_qualification()
    assert counts(scope) == [0, 0, 0, 0]
    with transaction.atomic():
        require_feature_command_qualification()


def test_historical_storage_seal_remains_immutable_authority(scope):
    with pytest.raises(DatabaseError, match="FEATURE_COMMAND_PREDECESSOR_INVALID"):
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE curve_feature_editor_command_coverage DISABLE TRIGGER "
                "curve_feature_editor_command_coverage_immutable"
            )
            cursor.execute("UPDATE curve_feature_editor_command_coverage SET catalog_digest=%s", ["sha256:" + "0" * 64])
            cursor.execute(
                "ALTER TABLE curve_feature_editor_command_coverage ENABLE TRIGGER "
                "curve_feature_editor_command_coverage_immutable"
            )
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    with transaction.atomic():
        require_feature_command_qualification()
