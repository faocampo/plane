# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811

from io import BytesIO
from types import SimpleNamespace
from importlib import import_module

import pytest
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from plane.db.models import WorkspaceMember
from plane.curve.models import LocalPrdSource, IdempotencyRecord, DomainEvent, OutboxEvent, AuditEvent, PolicyDecision
from plane.curve.local_document_services import upload_local_document
from plane.curve.local_document_store import LocalDocumentStore
from plane.curve.prd_commands import PrdCommandError
from plane.curve.services import IdempotencyConflict
from plane.curve.tests.test_scoped_prd_bridge import context, configuration, bridge  # noqa: F401
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage  # noqa: F401
from plane.curve.tests.test_local_document_authority import local  # noqa: F401

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "documents"
    root.mkdir(mode=0o700)
    with LocalDocumentStore(root) as value:
        yield value


def upload(local, store, **overrides):
    args = dict(
        request=local.request,
        workspace_slug=local.workspace.slug,
        initiative_id=local.initiative.id,
        expected_version=local.initiative.version,
        expected_source_version=0,
        raw_idempotency_key="upload-test",
        filename="prd.md",
        stream=BytesIO(b"# Synthetic requirements"),
        store=store,
    )
    return upload_local_document(**(args | overrides))


def test_upload_retry_and_replacement_are_exact_and_atomic(local, store, tmp_path):
    first = upload(local, store)
    replay = upload(local, store)
    assert first.data == replay.data and replay.replayed and not first.replayed
    assert len(list((tmp_path / "documents").iterdir())) == 2
    second = upload(
        local,
        store,
        raw_idempotency_key="replacement",
        expected_source_version=1,
        stream=BytesIO(b"# Revised requirements"),
    )
    assert second.data["version"] == 2 and second.data["predecessor_id"] == first.data["id"]
    assert LocalPrdSource.objects.count() == 2
    assert (
        IdempotencyRecord.objects.filter(command_scope__startswith="CURVE.LOCAL_PRD.UPLOAD:", state="COMPLETED").count()
        == 2
    )
    assert DomainEvent.objects.filter(event_type="CURVE.LOCAL_PRD.UPLOADED_V1").count() == 2
    assert OutboxEvent.objects.filter(destination="CURVE_LOCAL_PRD_SOURCE_V1").count() == 2
    assert AuditEvent.objects.filter(action="CURVE.LOCAL_PRD.UPLOAD", outcome="SUCCEEDED").count() == 2
    assert AuditEvent.objects.filter(action="CURVE.LOCAL_PRD.UPLOAD", outcome="NO_EFFECT").count() == 1
    assert PolicyDecision.objects.filter(policy_key="CURVE_LOCAL_PRD_POLICY", effect="ALLOW").exists()


def test_reused_key_with_changed_content_is_rejected_before_storage(local, store, tmp_path):
    upload(local, store)
    with pytest.raises(IdempotencyConflict):
        upload(local, store, stream=BytesIO(b"Different content"))
    assert LocalPrdSource.objects.count() == 1
    assert len(list((tmp_path / "documents").iterdir())) == 2


def test_stale_source_version_is_rejected_before_storage(local, store, tmp_path):
    upload(local, store)
    with pytest.raises(PrdCommandError, match="LOCAL_PRD_SOURCE_CHANGED"):
        upload(local, store, raw_idempotency_key="new-key")
    assert len(list((tmp_path / "documents").iterdir())) == 2


def test_access_revoked_during_preparation_prevents_commit(local, store, monkeypatch):
    original = LocalDocumentStore.put_snapshot

    def revoke(self, **kwargs):
        assert not transaction.get_connection().in_atomic_block
        result = original(self, **kwargs)
        WorkspaceMember.objects.filter(workspace=local.workspace, member=local.reviewers[1]).update(is_active=False)
        return result

    monkeypatch.setattr(LocalDocumentStore, "put_snapshot", revoke)
    with pytest.raises(PrdCommandError):
        upload(local, store)
    assert not LocalPrdSource.objects.exists()
    assert not IdempotencyRecord.objects.filter(command_scope__startswith="CURVE.LOCAL_PRD.UPLOAD:").exists()
    assert not DomainEvent.objects.filter(event_type="CURVE.LOCAL_PRD.UPLOADED_V1").exists()


def test_event_failure_rolls_back_source_and_retry_record(local, store, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("synthetic outbox failure")

    monkeypatch.setattr(OutboxEvent.objects, "create", fail)
    with pytest.raises(RuntimeError, match="synthetic outbox failure"):
        upload(local, store)
    assert not LocalPrdSource.objects.exists()
    assert not IdempotencyRecord.objects.filter(command_scope__startswith="CURVE.LOCAL_PRD.UPLOAD:").exists()
    assert not DomainEvent.objects.filter(event_type="CURVE.LOCAL_PRD.UPLOADED_V1").exists()
    assert not AuditEvent.objects.filter(action="CURVE.LOCAL_PRD.UPLOAD", outcome="SUCCEEDED").exists()


def test_replay_checks_current_access_before_reading_file(local, store):
    upload(local, store)
    WorkspaceMember.objects.filter(workspace=local.workspace, member=local.user).update(is_active=False)

    class Unreadable:
        def read(self, *_args):
            pytest.fail("Upload body was consumed before current authorization")

    with pytest.raises(PrdCommandError):
        upload(local, store, stream=Unreadable())


def test_command_cannot_inherit_database_locks(local, store):
    with transaction.atomic(), pytest.raises(PrdCommandError, match="TRANSACTION_REQUIRED"):
        upload(local, store)


def test_policy_migration_cannot_reverse_retained_upload_decisions(local, store):
    upload(local, store)
    migration = import_module("plane.curve.migrations.0031_local_prd_command")
    with transaction.atomic(), pytest.raises(RuntimeError, match="RETAINED_EVIDENCE"):
        migration.require_empty_reverse(None, SimpleNamespace(connection=connection))


def test_empty_policy_migration_roundtrip():
    old = import_module("plane.curve.migrations.0030_local_prd_source")
    new = import_module("plane.curve.migrations.0031_local_prd_command")
    leaves = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0030_local_prd_source")])
        with connection.cursor() as cursor:
            assert old._catalog(cursor) == old.CURRENT_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
        MigrationExecutor(connection).migrate([("curve", "0031_local_prd_command")])
        with connection.cursor() as cursor:
            assert new._catalog(cursor) == new.CURRENT_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    finally:
        MigrationExecutor(connection).migrate(leaves)
