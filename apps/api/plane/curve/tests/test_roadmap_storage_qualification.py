# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Storage-only qualification preserves the installed command authority."""

from copy import deepcopy
from importlib import import_module
from pathlib import Path

import pytest
from django.db import transaction
from plane.curve import scope_reopening_qualification as root
from plane.curve.prd_commands import PrdCommandError
from plane.curve.tests.test_product_format_qualification import records as product_records

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def records():
    old, product = product_records()
    return root.validate_product_format_successor(old, product), root._read_pinned_successor(
        root.ROADMAP_STORAGE_SUCCESSOR_PATH, root.ROADMAP_STORAGE_SUCCESSOR_DIGEST
    )


def test_storage_successor_preserves_history_and_adds_no_command_authority():
    previous, successor = records()
    before = deepcopy(previous)
    qualified = root.validate_roadmap_storage_successor(previous, successor)
    assert previous == before
    assert qualified["runtime_sources"] == root.current_runtime_sources()
    assert qualified["models"] == root.current_model_catalog()
    for key in ("runtime_writer_inventory", "excluded_writers"):
        assert qualified[key] == previous[key]
    for name, value in previous["migration_digests"].items():
        assert qualified["migration_digests"][name] == value
    with transaction.atomic():
        root.require_reopening_qualification()


@pytest.mark.parametrize(
    "damage",
    [
        "predecessor",
        "writer",
        "model",
        "extra_source",
        "missing_source",
        "unchanged",
        "catalog",
        "migration",
        "extra_field",
    ],
)
def test_storage_successor_rejects_authority_expansion(damage):
    previous, successor = records()
    if damage == "predecessor":
        successor["predecessor_digest"] = "sha256:" + "0" * 64
    elif damage == "writer":
        previous["runtime_writer_inventory"].append("ROADMAP_WRITE")
    elif damage == "model":
        successor["model_additions"][0]["columns"].append("unreviewed_authority")
    elif damage == "extra_source":
        successor["additions"]["unreviewed_writer.py"] = "sha256:" + "0" * 64
    elif damage == "missing_source":
        successor["replacements"].clear()
    elif damage == "unchanged":
        successor["replacements"]["models.py"] = previous["runtime_sources"]["models.py"]
    elif damage == "catalog":
        successor["physical_catalog_digest"] = "sha256:" + "0" * 64
    elif damage == "migration":
        successor["migration_digest"] = "invalid"
    else:
        successor["runtime_writer_inventory"] = ["ROADMAP_WRITE"]
    with pytest.raises(ValueError):
        root.validate_roadmap_storage_successor(previous, successor)


@pytest.mark.parametrize("damage", ["source", "proof", "missing", "symlink", "migration"])
def test_runtime_rejects_missing_or_changed_storage_proof(monkeypatch, damage):
    target = root.ROADMAP_STORAGE_SUCCESSOR_PATH
    if damage == "source":
        sources = root.current_runtime_sources()
        sources["roadmap_models.py"] = "sha256:" + "0" * 64
        monkeypatch.setattr(root, "current_runtime_sources", lambda: sources)
    elif damage in {"proof", "migration"}:
        if damage == "migration":
            target = Path(root.__file__).parent / "migrations/0043_roadmap_domain.py"
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


def test_unqualified_migration_is_refused(monkeypatch):
    migration = import_module("plane.curve.migrations.0043_roadmap_domain")
    monkeypatch.setattr(migration, "CURRENT_CATALOG_DIGEST", None)
    with pytest.raises(RuntimeError, match="QUALIFICATION_REQUIRED"):
        migration.require_qualification(None, None)


@pytest.mark.parametrize(
    "statement",
    [
        "ALTER TABLE curve_roadmap ADD COLUMN unqualified_authority boolean",
        "ALTER TABLE curve_roadmap_item_history DISABLE TRIGGER curve_roadmap_item_history_retained",
        "ALTER TRIGGER curve_mstone_position_recheck ON curve_milestone RENAME TO unqualified_recheck",
    ],
)
def test_runtime_rejects_physical_storage_drift_and_recovers_after_rollback(statement):
    from django.db import connection

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(statement)
        with pytest.raises(PrdCommandError):
            root.require_reopening_qualification()
        transaction.set_rollback(True)
    with transaction.atomic():
        root.require_reopening_qualification()
