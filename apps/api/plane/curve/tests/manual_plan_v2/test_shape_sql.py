# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""PostgreSQL function tests; not graph qualification.

Run only in the isolated disposable test database after the Docker access gate.
The tests exercise the actual installed functions with the complete successor gate.
"""

from copy import deepcopy
import json
from pathlib import Path

import pytest
from django.db import connection

ROOT = Path(__file__).resolve().parents[2] / "manual_plan_v2"
pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def shape_cursor():
    assert connection.vendor == "postgresql", "Real PostgreSQL is required; SQLite is not a substitute"
    from plane.curve.scope_reopening_qualification import require_manual_plan_v2_qualification

    require_manual_plan_v2_qualification()
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL standard_conforming_strings = on")
        yield cursor


def fixture(name):
    return json.loads((ROOT / "contract_snapshot/fixtures" / (name + ".valid.json")).read_text())


def accepts(cursor, kind, payload):
    cursor.execute("SELECT curve_mpd2_shape(%s::jsonb, curve_mpd2_schema(%s))", [json.dumps(payload), kind])
    return cursor.fetchone()[0]


@pytest.mark.parametrize(
    "kind,name",
    [("revision", "revision"), ("identity", "input-identity"), ("validation", "validation"), ("event", "event")],
)
def test_exact_closed_fixtures_and_required_properties(shape_cursor, kind, name):
    original = fixture(name)
    assert accepts(shape_cursor, kind, original) is True
    for key in original:
        missing = deepcopy(original)
        del missing[key]
        assert accepts(shape_cursor, kind, missing) is False, key
    assert accepts(shape_cursor, kind, dict(original, unexpected="denied")) is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision", True),
        ("revision", 0),
        ("revision", 9007199254740992),
        ("recorded_at", "2026-02-30T00:00:00Z"),
        ("recorded_at", "2026-10-06T00:00:00+00:00"),
        ("controlling", True),
        ("predecessor_id", "bad-id"),
        ("definition_ref", {}),
    ],
)
def test_invalid_typed_revision_fields_are_rejected(shape_cursor, field, value):
    assert accepts(shape_cursor, "revision", dict(fixture("revision"), **{field: value})) is False


def test_private_receipt_constraints_and_sorted_gate_types(shape_cursor):
    identity = fixture("input-identity")
    identity["gate_assignments"].reverse()
    assert accepts(shape_cursor, "identity", identity) is False
    identity = fixture("input-identity")
    identity["protected_inputs"][0]["classification"] = "PUBLIC"
    assert accepts(shape_cursor, "identity", identity) is False
    receipt = fixture("validation")
    receipt["required_conditions"] = "ALREADY_SATISFIED"
    assert accepts(shape_cursor, "validation", receipt) is False


def test_sql_metadata_digest_matches_python_fixture(shape_cursor):
    # Incumbent canonicalization is reused, including in the proposed SQL guards.
    payload = fixture("revision")
    expected = payload.pop("digest")
    shape_cursor.execute("SELECT curve_sprd_digest(%s::jsonb)", [json.dumps(payload)])
    assert shape_cursor.fetchone()[0] == expected
