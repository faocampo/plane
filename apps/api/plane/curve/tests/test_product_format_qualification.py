# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""The Product application-format successor preserves all historical authority."""

from copy import deepcopy
from pathlib import Path

import pytest
from django.db import transaction
from plane.curve import scope_reopening_qualification as root
from plane.curve.prd_commands import PrdCommandError

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def records():
    old = root._read_pinned_successor(root.TWO_STAGE_SUCCESSOR_PATH, root.TWO_STAGE_SUCCESSOR_DIGEST)["qualification"]
    previous = root.validate_review_read_successor(
        old, root._read_pinned_successor(root.REVIEW_READ_SUCCESSOR_PATH, root.REVIEW_READ_SUCCESSOR_DIGEST)
    )
    successor = root._read_pinned_successor(root.PRODUCT_FORMAT_SUCCESSOR_PATH, root.PRODUCT_FORMAT_SUCCESSOR_DIGEST)
    return previous, successor


def test_product_format_successor_preserves_history_catalog_and_writer_authority():
    previous, successor = records()
    before = deepcopy(previous)
    qualified = root.validate_product_format_successor(previous, successor)
    assert previous == before
    installed = root.validate_roadmap_storage_successor(
        qualified,
        root._read_pinned_successor(root.ROADMAP_STORAGE_SUCCESSOR_PATH, root.ROADMAP_STORAGE_SUCCESSOR_DIGEST),
    )
    installed = root.validate_roadmap_metadata_successor(
        installed,
        root._read_pinned_successor(root.ROADMAP_METADATA_SUCCESSOR_PATH, root.ROADMAP_METADATA_SUCCESSOR_DIGEST),
    )
    installed = root.validate_roadmap_hierarchy_successor(
        installed,
        root._read_pinned_successor(root.ROADMAP_HIERARCHY_SUCCESSOR_PATH, root.ROADMAP_HIERARCHY_SUCCESSOR_DIGEST),
    )
    installed = root.validate_feature_editor_storage_successor(
        installed,
        root._read_pinned_successor(
            root.FEATURE_EDITOR_STORAGE_SUCCESSOR_PATH, root.FEATURE_EDITOR_STORAGE_SUCCESSOR_DIGEST
        ),
    )
    assert installed["runtime_sources"] == root.current_runtime_sources()
    assert {key for key in qualified if qualified[key] != previous[key]} == {"runtime_sources"}
    with transaction.atomic():
        root.require_reopening_qualification()


@pytest.mark.parametrize(
    "damage",
    [
        "predecessor",
        "prior_authority",
        "extra",
        "missing",
        "invalid_digest",
        "unchanged",
        "authority",
        "addition",
    ],
)
def test_product_format_successor_rejects_changes_outside_its_exact_delta(damage):
    previous, successor = records()
    if damage == "predecessor":
        successor["predecessor_digest"] = "sha256:" + "0" * 64
    elif damage == "prior_authority":
        previous["runtime_writer_inventory"] = ["EXECUTION"]
    elif damage == "extra":
        successor["replacements"]["models.py"] = "sha256:" + "0" * 64
    elif damage == "missing":
        successor["replacements"].pop("product_services.py")
    elif damage == "invalid_digest":
        successor["additions"]["product_format.py"] = "invalid"
    elif damage == "unchanged":
        successor["replacements"]["product_services.py"] = previous["runtime_sources"]["product_services.py"]
    elif damage == "addition":
        successor["additions"]["extra_writer.py"] = "sha256:" + "0" * 64
    else:
        successor["runtime_writer_inventory"] = ["EXECUTION"]
    with pytest.raises(ValueError):
        root.validate_product_format_successor(previous, successor)


@pytest.mark.parametrize("damage", ["source", "proof", "missing_proof", "symlink"])
def test_runtime_rejects_unavailable_or_modified_product_format_qualification(monkeypatch, damage):
    target = root.PRODUCT_FORMAT_SUCCESSOR_PATH
    if damage == "source":
        sources = root.current_runtime_sources()
        sources["product_format.py"] = "sha256:" + "0" * 64
        monkeypatch.setattr(root, "current_runtime_sources", lambda: sources)
    elif damage == "proof":
        original = Path.read_bytes
        monkeypatch.setattr(
            Path, "read_bytes", lambda path: original(path) + b" " if path == target else original(path)
        )
    elif damage == "missing_proof":
        original = Path.exists
        monkeypatch.setattr(Path, "exists", lambda path: False if path == target else original(path))
    else:
        original = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda path: path == target or original(path))
    with transaction.atomic(), pytest.raises(PrdCommandError):
        root.require_reopening_qualification()
