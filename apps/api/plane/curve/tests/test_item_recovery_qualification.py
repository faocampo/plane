# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
import json

import pytest

from plane.curve import scope_reopening_qualification as qualification


def records(monkeypatch, tmp_path):
    baseline = json.loads(qualification.QUALIFICATION_PATH.read_bytes())
    successor = json.loads(qualification.ITEM_RECOVERY_SUCCESSOR_PATH.read_bytes())
    with monkeypatch.context() as patch:
        patch.setattr(qualification, "ITEM_RECOVERY_SUCCESSOR_PATH", tmp_path / "absent")
        predecessor = qualification._current_qualification(baseline)
    return predecessor, successor


def test_command_successor_preserves_prior_authority(monkeypatch, tmp_path):
    predecessor, successor = records(monkeypatch, tmp_path)
    result = qualification.validate_item_recovery_successor(predecessor, successor)
    assert result["runtime_writer_inventory"] == predecessor["runtime_writer_inventory"] + [
        "ITEM_CREATION_RECEIPT_READ"
    ]
    assert result["models"] == predecessor["models"]
    assert result["excluded_writers"] == predecessor["excluded_writers"]
    assert result["external_catalog_digest"] == predecessor["external_catalog_digest"]
    assert all(result["migration_digests"][key] == value for key, value in predecessor["migration_digests"].items())


@pytest.mark.parametrize("mutation", ["unknown", "missing_source", "extra_writer", "external", "predecessor"])
def test_command_successor_rejects_unreviewed_delta(monkeypatch, tmp_path, mutation):
    predecessor, original = records(monkeypatch, tmp_path)
    successor = deepcopy(original)
    if mutation == "unknown":
        successor["extra"] = True
    elif mutation == "missing_source":
        successor["additions"].pop("item_recovery_services.py")
    elif mutation == "extra_writer":
        successor["additions"]["unreviewed_writer.py"] = "sha256:" + "0" * 64
    elif mutation == "external":
        successor["external_catalog_digest"] = "sha256:" + "0" * 64
    else:
        successor["predecessor_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        qualification.validate_item_recovery_successor(predecessor, successor)
