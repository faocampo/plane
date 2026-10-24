# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811

from io import BytesIO
from importlib import import_module
import json
from types import SimpleNamespace
import uuid

import pytest
from django.db import connection, transaction, DatabaseError
from django.db.migrations.executor import MigrationExecutor

from plane.curve.models import Initiative, ImmutableRecordError, LocalPrdSource
from plane.curve.local_document_record import create_local_document_record, _metadata_digest
from plane.curve.local_document_store import LocalDocumentStore
from plane.curve.tests.test_project_association_api import context  # noqa: F401

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def uploaded(context, tmp_path):
    actor = dict(actor_type="HUMAN", actor_id=str(context.user.id))
    initiative = Initiative.objects.create(
        workspace_id=context.workspace.id,
        product_id=context.product.id,
        schema_version="1.2",
        mode="STANDALONE",
        keyword="upload",
        title="Uploaded requirements",
        description={},
        risk_tier="STANDARD",
        business_intent="BUSINESS_IMPROVEMENT",
        creator_user_id=context.user.id,
        created_by=actor,
        updated_by=actor,
    )
    root = tmp_path / "documents"
    root.mkdir(mode=0o700)

    def make(predecessor=None):
        with LocalDocumentStore(root) as store:
            original = store.put(
                workspace_id=str(context.workspace.id), filename="prd.md", stream=BytesIO(b"# Synthetic requirements")
            )
            snapshot = store.put_snapshot(workspace_id=str(context.workspace.id), source=original)
            return create_local_document_record(
                store=store,
                workspace_id=str(context.workspace.id),
                initiative_id=str(initiative.id),
                actor_id=str(context.user.id),
                uploaded_at="2026-10-21T12:00:00Z",
                snapshot=snapshot,
                predecessor=predecessor,
            )

    return make


def test_native_upload_versions_roundtrip_and_preserve_predecessor(uploaded):
    first = LocalPrdSource.from_record(uploaded())
    first.save()
    second = LocalPrdSource.from_record(uploaded(first.as_record()))
    second.save()
    assert LocalPrdSource.objects.get(id=first.id).as_record() == first.as_record()
    assert LocalPrdSource.objects.get(id=second.id).predecessor_id == uuid.UUID(str(first.id))
    assert second.version == 2
    with pytest.raises(ImmutableRecordError):
        first.save()
    with pytest.raises(ImmutableRecordError):
        LocalPrdSource.objects.filter(id=first.id).update(version=4)


@pytest.mark.parametrize(
    "verb",
    [
        "UPDATE curve_local_prd_source SET version=5",
        "DELETE FROM curve_local_prd_source",
        "TRUNCATE curve_local_prd_source",
    ],
)
def test_database_prevents_rewriting_retained_versions(uploaded, verb):
    LocalPrdSource.from_record(uploaded()).save()
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(verb)
    assert LocalPrdSource.objects.count() == 1


@pytest.mark.parametrize(
    "change",
    [
        "workspace",
        "version",
        "digest",
        "reference",
        "extra",
        "predecessor",
        "schema_version",
        "source_kind",
        "normalization_schema_version",
    ],
)
def test_direct_sql_rejects_invalid_source_graph(uploaded, change):
    value = uploaded()
    if change in {"schema_version", "source_kind", "normalization_schema_version"}:
        value[change] = None
    elif change == "workspace":
        value["workspace_id"] = str(uuid.uuid4())
    elif change == "version":
        value["version"] = 2
    elif change == "reference":
        value["original"]["size_bytes"] = 10 * 1024 * 1024 + 1
    elif change == "extra":
        value["canonical_url"] = "https://example.invalid"
    elif change == "predecessor":
        value["predecessor_id"] = str(uuid.uuid4())
    value["digest"] = _metadata_digest(value) if change != "digest" else "sha256:" + "0" * 64
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_local_prd_source(id,workspace_id,initiative_id,predecessor_id,version,"
            "uploaded_by,digest,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
            [
                value["id"],
                value["workspace_id"],
                value["initiative_id"],
                value["predecessor_id"],
                value["version"],
                value["uploaded_by"],
                value["digest"],
                json.dumps(value),
            ],
        )
    assert not LocalPrdSource.objects.exists()


def test_duplicate_version_is_rejected(uploaded):
    LocalPrdSource.from_record(uploaded()).save()
    with pytest.raises(DatabaseError), transaction.atomic():
        LocalPrdSource.from_record(uploaded()).save()


def test_reverse_preserves_retained_upload(uploaded):
    LocalPrdSource.from_record(uploaded()).save()
    migration = import_module("plane.curve.migrations.0030_local_prd_source")
    with pytest.raises(RuntimeError, match="RETAINED_EVIDENCE"), transaction.atomic():
        migration.require_empty_reverse(None, SimpleNamespace(connection=connection))


def test_empty_migration_roundtrip_restores_exact_catalogs():
    old = import_module("plane.curve.migrations.0029_technical_review_two_stage")
    new = import_module("plane.curve.migrations.0030_local_prd_source")
    leaves = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0029_technical_review_two_stage")])
        with connection.cursor() as cursor:
            assert old._catalog(cursor) == old.CURRENT_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
        MigrationExecutor(connection).migrate([("curve", "0030_local_prd_source")])
        with connection.cursor() as cursor:
            assert new._catalog(cursor) == new.CURRENT_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    finally:
        MigrationExecutor(connection).migrate(leaves)
