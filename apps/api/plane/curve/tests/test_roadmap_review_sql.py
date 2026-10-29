# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Exercise the installed successor SQL against native Item subjects."""

from copy import deepcopy
import json
from uuid import uuid4

from django.db import connection, transaction
import pytest

from plane.curve.tests import test_roadmap_local_context as context_fixtures
from plane.curve.tests import test_local_prd_roadmap as record_fixtures
from plane.curve.models import RoadmapItem

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]
scope = context_fixtures.scope
prepared = context_fixtures.prepared
material = context_fixtures.material
created = context_fixtures.created
subject = record_fixtures.subject


@pytest.fixture
def successor_sql(created):
    with transaction.atomic(), connection.cursor() as cursor:
        yield cursor


def subject_context(scope, created):
    item = RoadmapItem.objects.get(id=created.roadmap_item_id)
    return dict(
        product_id=str(created.product_id),
        product_version=scope.product.version,
        business_intent=created.business_intent,
        roadmap_item_id=str(item.id),
        roadmap_item_scope=item.scope_body,
    )


def is_current(cursor, payload, scope, created):
    cursor.execute(
        "SELECT curve_local_roadmap_review_context(%s::jsonb, %s, %s)",
        [json.dumps(payload), scope.workspace.id, created.id],
    )
    return cursor.fetchone()[0]


def test_successor_sql_accepts_real_reciprocal_item(successor_sql, scope, created):
    payload = subject_context(scope, created)
    assert is_current(successor_sql, payload, scope, created) is True
    successor_sql.execute(
        "SELECT curve_local_new_work_context(%s::jsonb, %s, %s)",
        [json.dumps(payload), scope.workspace.id, created.id],
    )
    assert successor_sql.fetchone()[0] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("product_id", str(uuid4())),
        ("product_version", 999),
        ("business_intent", "MANDATORY"),
        ("roadmap_item_id", str(uuid4())),
    ],
)
def test_changed_context_invalidates_sql_subject(successor_sql, scope, created, field, value):
    payload = subject_context(scope, created)
    payload[field] = value
    assert is_current(successor_sql, payload, scope, created) is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("object_id", str(uuid4())),
        ("digest", "sha256:" + "f" * 64),
        ("size_bytes", 999),
        ("media_type", "text/plain"),
        ("editor_schema_version", "markdown-v2"),
    ],
)
def test_every_scope_coordinate_is_bound_in_sql(successor_sql, scope, created, field, value):
    payload = subject_context(scope, created)
    payload["roadmap_item_scope"][field] = value
    assert is_current(successor_sql, payload, scope, created) is False


def test_closed_sql_shape_accepts_python_record(successor_sql, subject):
    _, record = subject
    successor_sql.execute("SELECT curve_local_roadmap_review_shape(%s::jsonb)", [json.dumps(record)])
    assert successor_sql.fetchone()[0] is True
    for change in (
        {"unknown": "field"},
        {"schema_version": "curve.local-prd-submission/v2-candidate"},
        {"roadmap_item_id": "invalid"},
        {"roadmap_item_scope": {}},
    ):
        altered = deepcopy(record) | change
        successor_sql.execute("SELECT curve_local_roadmap_review_shape(%s::jsonb)", [json.dumps(altered)])
        assert successor_sql.fetchone()[0] is False
