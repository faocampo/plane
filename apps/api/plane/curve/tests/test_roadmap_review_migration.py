# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Verify the installed successor reverses safely and preserves retained evidence."""

from importlib import import_module
from io import BytesIO

from django.db import connection, transaction
from django.db.migrations.state import ProjectState
import pytest

from plane.curve.tests import test_roadmap_local_context as fixtures
from plane.curve.local_document_models import LocalPrdSource
from plane.curve.local_document_record import create_local_document_record
from plane.curve.local_document_store import LocalDocumentStore

scope, prepared, material, created = fixtures.scope, fixtures.prepared, fixtures.material, fixtures.created
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def migration():
    return import_module("plane.curve.migrations.0054_roadmap_review")


def test_exact_migration_installs_and_reverses_empty_successor(migration, created):
    with transaction.atomic(), connection.schema_editor(atomic=False) as editor:
        instance = migration.Migration("0054_roadmap_review", "curve")
        state = ProjectState()
        migration.verify_successor(None, editor)
        instance.unapply(state, editor)
        migration.verify_predecessor(None, editor)
        instance.apply(state, editor)
        migration.verify_successor(None, editor)
        transaction.set_rollback(True)


def test_retained_roadmap_upload_blocks_reversal(migration, scope, created, tmp_path):
    root = tmp_path / "documents"
    root.mkdir(mode=0o700)
    with LocalDocumentStore(root) as store:
        original = store.put(
            workspace_id=str(scope.workspace.id), filename="requirements.md", stream=BytesIO(b"# Synthetic PRD")
        )
        snapshot = store.put_snapshot(workspace_id=str(scope.workspace.id), source=original)
        record = create_local_document_record(
            store=store,
            workspace_id=str(scope.workspace.id),
            initiative_id=str(created.id),
            actor_id=str(scope.owner.id),
            uploaded_at="2026-10-28T12:00:00Z",
            snapshot=snapshot,
            predecessor=None,
        )
        with transaction.atomic(), connection.schema_editor(atomic=False) as editor:
            instance = migration.Migration("0054_roadmap_review", "curve")
            state = ProjectState()
            LocalPrdSource.from_record(record).save(force_insert=True)
            with pytest.raises(RuntimeError, match="RETAINED_EVIDENCE_PREVENTS_REVERSE"):
                instance.unapply(state, editor)
            assert LocalPrdSource.objects.filter(id=record["id"]).exists()
            migration.verify_successor(None, editor)
            transaction.set_rollback(True)
