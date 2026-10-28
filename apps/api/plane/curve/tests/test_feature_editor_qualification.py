# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Closed storage successor preserves previous authority and detects source drift."""

from copy import deepcopy
from pathlib import Path

import pytest

from plane.curve import scope_reopening_qualification as root
from plane.curve.prd_commands import PrdCommandError
from plane.curve.tests.test_roadmap_metadata_storage import records as metadata_records

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def records():
    storage, metadata = metadata_records()
    previous = root.validate_roadmap_metadata_successor(storage, metadata)
    previous = root.validate_roadmap_hierarchy_successor(
        previous,
        root._read_pinned_successor(root.ROADMAP_HIERARCHY_SUCCESSOR_PATH, root.ROADMAP_HIERARCHY_SUCCESSOR_DIGEST),
    )
    return previous, root._read_pinned_successor(
        root.FEATURE_EDITOR_STORAGE_SUCCESSOR_PATH, root.FEATURE_EDITOR_STORAGE_SUCCESSOR_DIGEST
    )


def test_storage_successor_preserves_models_writers_and_historical_pins():
    previous, successor = records()
    before = deepcopy(previous)
    current = root.validate_feature_editor_storage_successor(previous, successor)
    assert previous == before
    for key in ("models", "runtime_writer_inventory", "excluded_writers"):
        assert current[key] == previous[key]
    assert all(current["migration_digests"][key] == value for key, value in previous["migration_digests"].items())
    installed = root.validate_feature_editor_command_successor(
        current,
        root._read_pinned_successor(
            root.FEATURE_EDITOR_COMMAND_SUCCESSOR_PATH, root.FEATURE_EDITOR_COMMAND_SUCCESSOR_DIGEST
        ),
    )
    assert installed["runtime_sources"] == root.current_runtime_sources()
    root.require_reopening_qualification()


@pytest.mark.parametrize(
    "damage", ["schema", "predecessor", "writer", "extra_source", "missing_source", "catalog", "external", "migration"]
)
def test_unreviewed_successor_changes_are_rejected(damage):
    previous, successor = records()
    if damage == "schema":
        successor["schema_version"] = "unsupported"
    elif damage == "predecessor":
        successor["predecessor_digest"] = "sha256:" + "0" * 64
    elif damage == "writer":
        successor["runtime_writer_inventory"] = ["GRANT_FEATURE_EDITOR"]
    elif damage == "extra_source":
        successor["additions"]["feature_editor_api.py"] = "sha256:" + "0" * 64
    elif damage == "missing_source":
        successor["additions"].clear()
    elif damage == "catalog":
        successor["physical_catalog_digest"] = "sha256:" + "0" * 64
    elif damage == "external":
        successor["external_catalog_digest"] = "sha256:" + "0" * 64
    else:
        successor["migration_digest"] = "invalid"
    with pytest.raises(ValueError):
        root.validate_feature_editor_storage_successor(previous, successor)


@pytest.mark.parametrize(
    "name",
    [
        "membership-lifetime.sql",
        "grants.sql",
        "external-catalog.sql",
        "coverage-forward.sql",
        "coverage-reverse.sql",
        "storage-reverse.sql",
    ],
)
def test_runtime_rejects_changed_sql_even_after_migration_module_import(monkeypatch, name):
    root.require_reopening_qualification()
    target = Path(root.__file__).parent / "feature_editors" / name
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda path: original(path) + b" " if path == target else original(path))
    with pytest.raises(PrdCommandError):
        root.require_reopening_qualification()
