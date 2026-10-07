# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""The reviewed read-only successor must not qualify unrelated source or DB drift."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json

import pytest
from django.db import connection, transaction

from plane.curve.prd_commands import PrdCommandError
import plane.curve.scope_reopening_qualification as qualification

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def test_predecessor_is_immutable_and_successor_changes_only_reviewed_read_source():
    raw = qualification.QUALIFICATION_PATH.read_bytes()
    assert (
        "sha256:" + sha256(raw).hexdigest() == "sha256:72bdb3b987ec1925754e6a14dee36cecec3c85706605c052d443628d84e7fb52"
    )
    predecessor = json.loads(raw)
    successor = json.loads(qualification.READ_SUCCESSOR_PATH.read_bytes())
    updated = successor["qualification"]
    assert len(predecessor["runtime_sources"]) == 120 and len(updated["runtime_sources"]) == 122
    assert {key: value for key, value in predecessor.items() if key != "runtime_sources"} == {
        key: value for key, value in updated.items() if key != "runtime_sources"
    }
    assert (
        qualification._current_qualification(predecessor)["runtime_sources"] == qualification.current_runtime_sources()
    )
    with transaction.atomic():
        qualification.require_reopening_qualification()


@pytest.mark.parametrize("path_name", ["QUALIFICATION_PATH", "READ_SUCCESSOR_PATH"])
def test_either_qualification_document_corruption_denies(monkeypatch, path_name):
    path = getattr(qualification, path_name)
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda p: original(p) + b" " if p == path else original(p))
    with pytest.raises(PrdCommandError), transaction.atomic():
        qualification.require_reopening_qualification()


@pytest.mark.parametrize(
    "damage",
    [
        "unknown_field",
        "predecessor",
        "edition",
        "models",
        "migrations",
        "catalog",
        "writers",
        "unknown_module",
        "unrelated_module",
        "removed_module",
        "missing_read",
        "unchanged_url",
    ],
)
def test_successor_closed_shape_and_delta_remain_enforced_even_with_matching_hash(monkeypatch, damage):
    successor = json.loads(qualification.READ_SUCCESSOR_PATH.read_bytes())
    predecessor = json.loads(qualification.QUALIFICATION_PATH.read_bytes())
    changed = deepcopy(successor)
    q = changed["qualification"]
    if damage == "unknown_field":
        changed["trust_deployed_state"] = True
    elif damage == "predecessor":
        changed["predecessor_digest"] = "sha256:" + "0" * 64
    elif damage == "edition":
        changed["read_edition"] = "FUTURE_WRITER"
    elif damage == "models":
        q["models"].append({"model_name": "plan", "db_table": "curve_plan", "columns": ["id"]})
    elif damage == "migrations":
        q["migration_digests"]["9999_plan.py"] = "sha256:" + "0" * 64
    elif damage == "catalog":
        q["physical_catalog_digest"] = "sha256:" + "0" * 64
    elif damage == "writers":
        q["runtime_writer_inventory"].append("PLAN_APPROVAL")
    elif damage == "unknown_module":
        q["runtime_sources"]["new_plan_writer.py"] = "sha256:" + "0" * 64
    elif damage == "unrelated_module":
        q["runtime_sources"]["scope_proposal_services.py"] = "sha256:" + "0" * 64
    elif damage == "removed_module":
        del q["runtime_sources"]["scope_proposal_services.py"]
    elif damage == "missing_read":
        del q["runtime_sources"]["project_association_read.py"]
    else:
        q["runtime_sources"]["urls.py"] = predecessor["runtime_sources"]["urls.py"]
    raw = json.dumps(changed).encode()
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda p: raw if p == qualification.READ_SUCCESSOR_PATH else original(p))
    monkeypatch.setattr(qualification, "READ_SUCCESSOR_DIGEST", "sha256:" + sha256(raw).hexdigest())
    # Even an observed runtime matching the tampered file cannot expand its allowed delta.
    monkeypatch.setattr(qualification, "current_runtime_sources", lambda: q["runtime_sources"])
    with pytest.raises(PrdCommandError), transaction.atomic():
        qualification.require_reopening_qualification()


@pytest.mark.parametrize("damage", ["unknown_writer", "changed_writer", "changed_read"])
def test_live_runtime_drift_stays_unqualified(monkeypatch, damage):
    sources = qualification.current_runtime_sources()
    name = {
        "unknown_writer": "new_plan_writer.py",
        "changed_writer": "scope_proposal_services.py",
        "changed_read": "project_association_read.py",
    }[damage]
    sources[name] = "sha256:" + "0" * 64
    monkeypatch.setattr(qualification, "current_runtime_sources", lambda: sources)
    with pytest.raises(PrdCommandError), transaction.atomic():
        qualification.require_reopening_qualification()


def test_physical_catalog_drift_denies_and_clean_rollback_remains_qualified():
    with pytest.raises(PrdCommandError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("CREATE TABLE curve_unqualified_plan (id uuid PRIMARY KEY)")
        qualification.require_reopening_qualification()
    with transaction.atomic():
        qualification.require_reopening_qualification()
