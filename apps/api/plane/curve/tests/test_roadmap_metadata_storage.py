# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Additive metadata history persistence and independent qualification boundaries."""

from copy import deepcopy
from importlib import import_module
from pathlib import Path

import pytest
from django.db import connection, transaction, DatabaseError
from django.db.migrations.executor import MigrationExecutor
from plane.curve import scope_reopening_qualification as root
from plane.curve.models import RoadmapItemHistory
from plane.curve.prd_commands import PrdCommandError
from plane.curve.tests.test_roadmap_storage import graph as roadmap_graph, pair, sql
from plane.curve.tests.test_roadmap_storage_qualification import records as storage_records

graph = roadmap_graph

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]
TYPES = ["PRIORITY_CHANGED", "HEALTH_CHANGED", "CONFIDENCE_CHANGED", "SCHEDULE_CHANGED"]


def history(item, kind):
    return RoadmapItemHistory.objects.create(
        workspace_id=item.workspace_id,
        product_id=item.product_id,
        roadmap_item_id=item.id,
        sequence=1,
        before_version=1,
        after_version=2,
        recorded_at=item.updated_at,
        recorded_by=item.updated_by,
        change_type=kind,
        payload={"before": {}, "after": {}, "rationale": "Synthetic storage fixture"},
    )


@pytest.mark.parametrize("kind", TYPES)
def test_new_history_round_trip_is_immutable_and_prevents_lossy_reverse(graph, kind):
    item = pair(graph)
    record = history(item, kind)
    before = RoadmapItemHistory.objects.filter(id=record.id).values().get()
    for statement in [
        "UPDATE curve_roadmap_item_history SET sequence=2",
        "DELETE FROM curve_roadmap_item_history",
        "TRUNCATE curve_roadmap_item_history",
    ]:
        with pytest.raises(DatabaseError), transaction.atomic():
            sql(statement)
    with pytest.raises(RuntimeError, match="RETAINED_EVIDENCE"), transaction.atomic():
        MigrationExecutor(connection).migrate([("curve", "0043_roadmap_domain")])
    assert RoadmapItemHistory.objects.filter(id=record.id).values().get() == before
    with transaction.atomic():
        root.require_reopening_qualification()


@pytest.mark.parametrize("kind", ["PROGRESS_CHANGED", "MILESTONE_MOVED"])
def test_old_history_and_seal_survive_repeated_upgrade_and_reverse(graph, kind):
    item = pair(graph)
    record = history(item, kind)
    before = RoadmapItemHistory.objects.filter(id=record.id).values().get()
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM curve_roadmap_domain_coverage")
        seal = cursor.fetchall()
    leaves = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        for _ in range(2):
            MigrationExecutor(connection).migrate([("curve", "0043_roadmap_domain")])
            assert RoadmapItemHistory.objects.filter(id=record.id).values().get() == before
            sql("SELECT curve_scope_reopening_verify_coverage()")
            MigrationExecutor(connection).migrate(leaves)
            assert RoadmapItemHistory.objects.filter(id=record.id).values().get() == before
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM curve_roadmap_domain_coverage")
                assert cursor.fetchall() == seal
            with transaction.atomic():
                root.require_reopening_qualification()
    finally:
        MigrationExecutor(connection).migrate(leaves)


@pytest.mark.parametrize("kind", ["UNSUPPORTED", "STATUS_CHANGED", "OWNER_CHANGED", "SCOPE_CHANGED", ""])
def test_unqualified_history_type_is_rejected(graph, kind):
    item = pair(graph)
    with pytest.raises(DatabaseError), transaction.atomic():
        history(item, kind)
    assert not RoadmapItemHistory.objects.exists()


def records():
    old, storage = storage_records()
    return root.validate_roadmap_storage_successor(old, storage), root._read_pinned_successor(
        root.ROADMAP_METADATA_SUCCESSOR_PATH, root.ROADMAP_METADATA_SUCCESSOR_DIGEST
    )


def test_metadata_qualification_preserves_models_writers_and_migration_history():
    old, successor = records()
    original = deepcopy(old)
    current = root.validate_roadmap_metadata_successor(old, successor)
    assert old == original
    installed = root.validate_roadmap_hierarchy_successor(
        current,
        root._read_pinned_successor(root.ROADMAP_HIERARCHY_SUCCESSOR_PATH, root.ROADMAP_HIERARCHY_SUCCESSOR_DIGEST),
    )
    installed = root.validate_feature_editor_storage_successor(
        installed,
        root._read_pinned_successor(
            root.FEATURE_EDITOR_STORAGE_SUCCESSOR_PATH, root.FEATURE_EDITOR_STORAGE_SUCCESSOR_DIGEST
        ),
    )
    installed = root.validate_feature_editor_command_successor(
        installed,
        root._read_pinned_successor(
            root.FEATURE_EDITOR_COMMAND_SUCCESSOR_PATH, root.FEATURE_EDITOR_COMMAND_SUCCESSOR_DIGEST
        ),
    )
    installed = root.validate_feature_command_successor(
        installed,
        root._read_pinned_successor(root.FEATURE_COMMAND_SUCCESSOR_PATH, root.FEATURE_COMMAND_SUCCESSOR_DIGEST),
    )
    installed = root.validate_item_creation_successor(
        installed,
        root._read_pinned_successor(root.ITEM_CREATION_SUCCESSOR_PATH, root.ITEM_CREATION_SUCCESSOR_DIGEST),
    )
    installed = root.validate_item_read_successor(
        installed,
        root._read_pinned_successor(root.ITEM_READ_SUCCESSOR_PATH, root.ITEM_READ_SUCCESSOR_DIGEST),
    )
    installed = root.validate_item_scope_successor(
        installed,
        root._read_pinned_successor(root.ITEM_SCOPE_SUCCESSOR_PATH, root.ITEM_SCOPE_SUCCESSOR_DIGEST),
    )
    installed = root.validate_item_recovery_successor(
        installed,
        root._read_pinned_successor(root.ITEM_RECOVERY_SUCCESSOR_PATH, root.ITEM_RECOVERY_SUCCESSOR_DIGEST),
    )
    installed = root.validate_item_cancellation_successor(
        installed,
        root._read_pinned_successor(root.ITEM_CANCELLATION_SUCCESSOR_PATH, root.ITEM_CANCELLATION_SUCCESSOR_DIGEST),
    )
    installed = root.validate_roadmap_review_successor(
        installed,
        root._read_pinned_successor(
            root.ROADMAP_REVIEW_SUCCESSOR_PATH, root.ROADMAP_REVIEW_SUCCESSOR_DIGEST
        ),
    )
    assert installed["runtime_sources"] == root.current_runtime_sources()
    assert current["models"] == old["models"] == root.current_model_catalog()
    for key in ("runtime_writer_inventory", "excluded_writers"):
        assert current[key] == old[key]
    assert all(current["migration_digests"][k] == v for k, v in old["migration_digests"].items())
    with transaction.atomic():
        root.require_reopening_qualification()


@pytest.mark.parametrize(
    "damage",
    ["predecessor", "writer", "extra_source", "missing_source", "unchanged", "catalog", "migration", "extra_field"],
)
def test_metadata_qualification_rejects_authority_expansion(damage):
    old, successor = records()
    if damage == "predecessor":
        successor["predecessor_digest"] = "sha256:" + "0" * 64
    elif damage == "writer":
        old["runtime_writer_inventory"].append("ROADMAP_WRITE")
    elif damage == "extra_source":
        successor["replacements"]["unreviewed.py"] = "sha256:" + "0" * 64
    elif damage == "missing_source":
        successor["replacements"].clear()
    elif damage == "unchanged":
        successor["replacements"]["roadmap_models.py"] = old["runtime_sources"]["roadmap_models.py"]
    elif damage == "catalog":
        successor["physical_catalog_digest"] = "sha256:" + "0" * 64
    elif damage == "migration":
        successor["migration_digest"] = "invalid"
    else:
        successor["writer"] = "ROADMAP_WRITE"
    with pytest.raises(ValueError):
        root.validate_roadmap_metadata_successor(old, successor)


@pytest.mark.parametrize("damage", ["proof", "missing", "symlink", "migration"])
def test_runtime_requires_exact_metadata_proof(monkeypatch, damage):
    target = root.ROADMAP_METADATA_SUCCESSOR_PATH
    if damage in {"proof", "migration"}:
        if damage == "migration":
            target = Path(root.__file__).parent / "migrations/0044_roadmap_metadata_history.py"
        original = Path.read_bytes
        monkeypatch.setattr(
            Path, "read_bytes", lambda path: original(path) + b" " if path == target else original(path)
        )
    elif damage == "missing":
        original = Path.exists
        monkeypatch.setattr(Path, "exists", lambda path: False if path == target else original(path))
    else:
        original = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda path: path == target or original(path))
    with transaction.atomic(), pytest.raises(PrdCommandError):
        root.require_reopening_qualification()


def test_unqualified_metadata_migration_refuses_installation(monkeypatch):
    migration = import_module("plane.curve.migrations.0044_roadmap_metadata_history")
    monkeypatch.setattr(migration, "CURRENT_CATALOG_DIGEST", None)
    with pytest.raises(RuntimeError, match="QUALIFICATION_REQUIRED"):
        migration.require_qualification(None, None)
