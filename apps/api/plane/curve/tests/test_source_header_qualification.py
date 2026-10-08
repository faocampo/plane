# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Copyright-only source succession preserves every historical authority boundary."""

from copy import deepcopy
from pathlib import Path
import json

import pytest

from plane.curve import scope_reopening_qualification as root

pytestmark = pytest.mark.contract


def records():
    return (
        json.loads(root.GATE2_SUCCESSOR_PATH.read_bytes())["qualification"],
        root._read_pinned_successor(root.HEADER_SUCCESSOR_PATH, root.HEADER_SUCCESSOR_DIGEST),
    )


def test_header_successor_preserves_authority_and_complete_source_closure():
    predecessor, successor = records()
    before = deepcopy(predecessor)
    qualified = root.validate_source_header_successor(predecessor, successor)
    assert predecessor == before
    assert qualified["runtime_sources"] == root.current_runtime_sources()
    assert {key: value for key, value in qualified.items() if key != "runtime_sources"} == {
        key: value for key, value in before.items() if key != "runtime_sources"
    }
    changed = {
        name
        for name in before["runtime_sources"]
        if before["runtime_sources"][name] != qualified["runtime_sources"][name]
    }
    assert changed == root._MANUAL_ADDED_MODULES | root._GATE2_ADDED_MODULES
    assert len(changed) == 20


@pytest.mark.parametrize(
    "damage",
    [
        "unknown_field",
        "missing_field",
        "schema",
        "predecessor",
        "header",
        "extra_module",
        "missing_module",
        "record_field",
        "before",
        "after",
    ],
)
def test_header_successor_rejects_forged_or_broadened_records(damage):
    predecessor, successor = records()
    name = next(iter(successor["replacements"]))
    if damage == "unknown_field":
        successor["allow_code_changes"] = True
    elif damage == "missing_field":
        del successor["header_digest"]
    elif damage in {"schema", "predecessor", "header"}:
        key = {"schema": "schema_version", "predecessor": "predecessor_digest", "header": "header_digest"}[damage]
        successor[key] = "unqualified"
    elif damage == "extra_module":
        successor["replacements"]["new_writer.py"] = successor["replacements"][name]
    elif damage == "missing_module":
        del successor["replacements"][name]
    elif damage == "record_field":
        successor["replacements"][name]["allow_changed_body"] = True
    else:
        successor["replacements"][name][damage] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        root.validate_source_header_successor(predecessor, successor)


@pytest.mark.parametrize("damage", ["body", "missing_header", "double_header", "different_header", "symlink"])
def test_header_successor_rejects_every_non_prefix_source_change(monkeypatch, damage):
    predecessor, successor = records()
    target = Path(root.__file__).parent / next(iter(successor["replacements"]))
    original_read = Path.read_bytes
    original_link = Path.is_symlink

    def read(path):
        raw = original_read(path)
        if path != target:
            return raw
        if damage == "body":
            return raw + b"\nUNQUALIFIED_WRITER = True\n"
        if damage == "missing_header":
            return raw[len(root.SOURCE_HEADER) :]
        if damage == "double_header":
            return root.SOURCE_HEADER + raw
        if damage == "different_header":
            return raw.replace(b"AGPL-3.0-only", b"MIT", 1)
        return raw

    monkeypatch.setattr(Path, "read_bytes", read)
    if damage == "symlink":
        monkeypatch.setattr(Path, "is_symlink", lambda path: path == target or original_link(path))
    with pytest.raises(ValueError):
        root.validate_source_header_successor(predecessor, successor)


@pytest.mark.parametrize("field", ["excluded_writers", "models", "migration_digests", "physical_catalog_digest"])
def test_header_successor_cannot_change_predecessor_authority(field):
    predecessor, successor = records()
    predecessor[field] = None
    with pytest.raises(ValueError):
        root.validate_source_header_successor(predecessor, successor)


def test_header_manifest_has_an_independent_exact_digest(monkeypatch):
    original = Path.read_bytes
    monkeypatch.setattr(
        Path, "read_bytes", lambda path: original(path) + b" " if path == root.HEADER_SUCCESSOR_PATH else original(path)
    )
    with pytest.raises(ValueError, match="proof mismatch"):
        root._read_pinned_successor(root.HEADER_SUCCESSOR_PATH, root.HEADER_SUCCESSOR_DIGEST)
