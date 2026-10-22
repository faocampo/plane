# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""The two-stage runtime is bound to exact sources, preserved history and actual storage."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
from django.db import transaction
from plane.curve import scope_reopening_qualification as root
from plane.curve.prd_commands import PrdCommandError

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def records():
    old = json.loads(root.GATE2_SUCCESSOR_PATH.read_bytes())["qualification"]
    new = root._read_pinned_successor(root.TWO_STAGE_SUCCESSOR_PATH, root.TWO_STAGE_SUCCESSOR_DIGEST)
    return old, new


def test_successor_verifies_complete_runtime_and_preserves_old_authority():
    old, new = records()
    before = deepcopy(old)
    qualified = root.validate_two_stage_successor(old, new)
    assert old == before
    assert qualified["models"] == root.current_model_catalog()
    assert qualified["runtime_sources"] == root.current_runtime_sources()
    assert qualified["excluded_writers"] == old["excluded_writers"]
    assert "EXECUTION" in qualified["excluded_writers"]
    for name, value in old["migration_digests"].items():
        assert qualified["migration_digests"][name] == value
    with transaction.atomic():
        root.require_manual_plan_v3_qualification()
        root.require_manual_plan_v2_qualification()


@pytest.mark.parametrize(
    "damage",
    ["writer", "exclusions", "model", "catalog", "old_migration", "extra_source", "missing_source", "predecessor"],
)
def test_successor_cannot_expand_the_declared_delta(damage):
    old, new = records()
    q = new["qualification"]
    if damage == "writer":
        q["runtime_writer_inventory"].append("EXECUTION")
    elif damage == "exclusions":
        q["excluded_writers"] = []
    elif damage == "model":
        q["models"].pop()
    elif damage == "catalog":
        q["physical_catalog_digest"] = "sha256:" + "0" * 64
    elif damage == "old_migration":
        q["migration_digests"][next(iter(old["migration_digests"]))] = "sha256:" + "0" * 64
    elif damage == "extra_source":
        q["runtime_sources"]["unqualified.py"] = "sha256:" + "0" * 64
    elif damage == "missing_source":
        q["runtime_sources"].pop("manual_plan_v3/services.py")
    else:
        new["predecessor_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        root.validate_two_stage_successor(old, new)


@pytest.mark.parametrize("damage", ["source", "proof", "missing_proof", "symlink"])
def test_runtime_rejects_changed_or_unavailable_proof(monkeypatch, damage):
    original = Path.read_bytes
    target = root.TWO_STAGE_SUCCESSOR_PATH
    if damage == "source":
        sources = root.current_runtime_sources()
        sources["manual_plan_v3/services.py"] = "sha256:" + "0" * 64
        monkeypatch.setattr(root, "current_runtime_sources", lambda: sources)
    elif damage == "proof":
        monkeypatch.setattr(Path, "read_bytes", lambda p: original(p) + b" " if p == target else original(p))
    elif damage == "missing_proof":
        exists = Path.exists
        monkeypatch.setattr(Path, "exists", lambda p: False if p == target else exists(p))
    else:
        is_link = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda p: p == target or is_link(p))
    with transaction.atomic(), pytest.raises(PrdCommandError):
        root.require_manual_plan_v3_qualification()
