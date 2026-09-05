# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from plane.curve.models import (
    DocumentSynchronizationStatus,
    ExternalDocumentBinding,
    ImmutableRecordError,
    Initiative,
    ProviderConnection,
)
from plane.curve.tests.test_provider_models import ACTOR, connection_values


pytestmark = [pytest.mark.unit, pytest.mark.django_db]


def initiative_values(workspace_id):
    return dict(
        workspace_id=workspace_id,
        product_id=uuid.uuid4(),
        mode="STANDALONE",
        keyword=f"prd-{uuid.uuid4()}",
        title="Synthetic document lifecycle",
        description={"schema_version": "1.0", "format": "MARKDOWN", "body": "Synthetic test"},
        risk_tier="STANDARD",
        creator_user_id=uuid.uuid4(),
        created_by=ACTOR,
        updated_by=ACTOR,
    )


def binding_values(workspace_id=None):
    workspace_id = workspace_id or uuid.uuid4()
    initiative = Initiative.objects.create(**initiative_values(workspace_id))
    provider = ProviderConnection.objects.create(**connection_values(workspace_id))
    return dict(
        workspace_id=workspace_id,
        initiative=initiative,
        provider_connection=provider,
        provider_file_id="synthetic-document",
        provider_container_id="synthetic-container",
        canonical_url="https://docs.example.invalid/documents/synthetic-document",
        current_provider_version="900719925474099312345",
        current_modified_at=timezone.now(),
        created_by=ACTOR,
    )


def sql_update(record, **changes):
    # Keys are test-owned field names; values remain parameterized.
    assignments = ", ".join(f"{connection.ops.quote_name(key)} = %s" for key in changes)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE curve_external_document_binding SET {assignments} WHERE id = %s",
            [*changes.values(), record.id],
        )


def test_round_trip_is_metadata_only_and_workspace_scoped():
    binding = ExternalDocumentBinding.objects.create(**binding_values())
    loaded = ExternalDocumentBinding.objects.find_by_id(workspace_id=binding.workspace_id, record_id=binding.id)
    assert loaded.current_provider_version == "900719925474099312345"
    assert loaded.current_revision_id is None
    assert loaded.version == 1
    assert loaded.access_status == "UNKNOWN"
    assert loaded.synchronization_status == "RECONCILIATION_REQUIRED"
    assert ExternalDocumentBinding.objects.find_by_id(workspace_id=uuid.uuid4(), record_id=binding.id) is None
    with pytest.raises(ValueError, match="workspace_id"):
        ExternalDocumentBinding.objects.for_workspace(None)
    assert not {"body", "normalized_content", "rationale", "credentials", "secret_reference"}.intersection(
        field.name for field in ExternalDocumentBinding._meta.fields
    )


@pytest.mark.parametrize("reference", ["initiative", "provider_connection"])
def test_orm_rejects_foreign_workspace_references(reference):
    values = binding_values()
    values[reference] = binding_values()[reference]
    with pytest.raises(ValidationError, match="workspace"):
        ExternalDocumentBinding.objects.create(**values)


@pytest.mark.parametrize("reference", ["initiative", "provider_connection"])
def test_database_rejects_foreign_workspace_references_without_orm_validation(reference):
    values = binding_values()
    values[reference] = binding_values()[reference]
    record = ExternalDocumentBinding(**values)
    with pytest.raises(IntegrityError), transaction.atomic():
        # save_base deliberately bypasses model save, matching a raw writer.
        record.save_base(force_insert=True)


def test_one_prd_binding_per_initiative_and_colliding_ids_cannot_overwrite():
    values = binding_values()
    record = ExternalDocumentBinding.objects.create(**values)
    with pytest.raises(IntegrityError), transaction.atomic():
        ExternalDocumentBinding.objects.create(**values)
    with pytest.raises(IntegrityError), transaction.atomic():
        ExternalDocumentBinding(id=record.id, version=2, **values).save()
    record.refresh_from_db()
    assert record.version == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "2.0"),
        ("artifact_kind", "IDEA_BRIEF"),
        ("version", 0),
        ("version", 2),
        ("provider_file_id", ""),
        ("provider_file_id", "file/other"),
        ("provider_container_id", "../invalid/"),
        ("current_provider_version", ""),
        ("current_revision_id", ""),
        ("canonical_url", "http://example.invalid"),
        ("canonical_url", "https://example.invalid/\nother"),
        ("synchronization_status", "APPROVED"),
        ("access_status", "ADMIN"),
        ("created_by", {}),
        ("created_by", None),
        ("created_by", {"actor_type": "SERVICE", "actor_id": "fixture"}),
        ("created_by", {"actor_type": "HUMAN", "actor_id": 1}),
        ("created_by", {"actor_type": "HUMAN", "actor_id": ""}),
        ("created_by", {"actor_type": "HUMAN", "actor_id": "a" * 256}),
        ("created_by", {"actor_type": "HUMAN", "actor_id": "fixture", "body": "forbidden"}),
    ],
)
def test_database_validates_closed_bounded_metadata(field, value):
    values = binding_values()
    values[field] = value
    with pytest.raises(IntegrityError), transaction.atomic():
        ExternalDocumentBinding.objects.create(**values)


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "workspace_id",
        "initiative_id",
        "provider_connection_id",
        "provider_file_id",
        "schema_version",
        "artifact_kind",
        "created_at",
        "created_by",
    ],
)
def test_database_protects_identity_and_attribution(field):
    record = ExternalDocumentBinding.objects.create(**binding_values())
    value = uuid.uuid4() if field.endswith("id") and field != "provider_file_id" else "changed"
    if field == "created_at":
        value = timezone.now()
    if field == "created_by":
        value = '{"actor_type":"HUMAN","actor_id":"other-fixture"}'
    with pytest.raises(IntegrityError, match="immutable"), transaction.atomic():
        sql_update(record, **{field: value, "version": 2})


def test_projection_can_change_with_exact_version_and_no_initiative_transition():
    record = ExternalDocumentBinding.objects.create(**binding_values())
    record.version += 1
    record.provider_container_id = "synthetic-moved-container"
    record.current_provider_version = "900719925474099312346"
    record.current_revision_id = "synthetic-revision"
    record.last_reconciled_at = timezone.now()
    record.synchronization_status = DocumentSynchronizationStatus.CHANGED_SINCE_APPROVAL
    record.save()
    record.refresh_from_db()
    assert record.version == 2
    assert record.provider_container_id == "synthetic-moved-container"
    record.initiative.refresh_from_db()
    assert record.initiative.state == "DRAFT"
    assert record.initiative.version == 1
    assert record.initiative.first_external_resource_at is None


def test_stale_instances_and_out_of_order_observations_fail_closed():
    record = ExternalDocumentBinding.objects.create(**binding_values())
    stale = ExternalDocumentBinding.objects.get(pk=record.id)
    record.version = 2
    record.last_reconciled_at = timezone.now()
    record.save()
    stale.version = 2
    with pytest.raises(IntegrityError, match="version conflict"), transaction.atomic():
        stale.save()
    for observed in (None, record.last_reconciled_at - timezone.timedelta(seconds=1)):
        with pytest.raises(IntegrityError, match="regress"), transaction.atomic():
            sql_update(record, version=3, last_reconciled_at=observed)


def test_orm_bulk_paths_and_deletion_are_blocked():
    record = ExternalDocumentBinding.objects.create(**binding_values())
    for action in (
        lambda: ExternalDocumentBinding.objects.bulk_create([]),
        lambda: ExternalDocumentBinding.objects.bulk_update([record], ["version"]),
        lambda: ExternalDocumentBinding.objects.filter(pk=record.id).update(version=2),
        lambda: ExternalDocumentBinding.objects.filter(pk=record.id).delete(),
        record.delete,
    ):
        with pytest.raises(ImmutableRecordError):
            action()
    with pytest.raises(IntegrityError, match="governed"), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM curve_external_document_binding WHERE id = %s", [record.id])


@pytest.mark.parametrize(
    "parent_table,parent_field",
    [
        ("curve_initiative", "initiative_id"),
        ("curve_provider_connection", "provider_connection_id"),
    ],
)
def test_parent_workspace_changes_and_deletion_cannot_break_tenant_linkage(parent_table, parent_field):
    record = ExternalDocumentBinding.objects.create(**binding_values())
    parent_id = getattr(record, parent_field)
    with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f"UPDATE {parent_table} SET workspace_id = %s WHERE id = %s", [uuid.uuid4(), parent_id])
    with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {parent_table} WHERE id = %s", [parent_id])


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_projection_updates_have_one_winner():
    record = ExternalDocumentBinding.objects.create(**binding_values())
    barrier = Barrier(2)

    def write_projection():
        try:
            loaded = ExternalDocumentBinding.objects.get(pk=record.id)
            barrier.wait(timeout=10)
            loaded.version += 1
            loaded.last_reconciled_at = timezone.now()
            try:
                with transaction.atomic():
                    loaded.save()
                return "committed"
            except IntegrityError:
                return "conflict"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: write_projection(), range(2)))
    assert sorted(results) == ["committed", "conflict"]
    record.refresh_from_db()
    assert record.version == 2


@pytest.mark.django_db(transaction=True)
def test_migration_round_trip_preserves_existing_parent_records():
    target = ("curve", "0009_external_document_binding")
    previous = ("curve", "0008_initiative_business_intent")
    values = binding_values()
    initiative_id = values["initiative"].id
    provider_id = values["provider_connection"].id
    try:
        MigrationExecutor(connection).migrate([previous])
        assert "curve_external_document_binding" not in connection.introspection.table_names()
        assert Initiative.objects.filter(pk=initiative_id).exists()
        assert ProviderConnection.objects.filter(pk=provider_id).exists()
    finally:
        MigrationExecutor(connection).migrate([target])
    assert "curve_external_document_binding" in connection.introspection.table_names()
    ExternalDocumentBinding.objects.create(**values)
    with pytest.raises(DatabaseError, match="preservation migration"):
        MigrationExecutor(connection).migrate([previous])
    assert ExternalDocumentBinding.objects.count() == 1
    # The atomic rejected reverse migration leaves every DB guard installed.
    with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM curve_external_document_binding")
