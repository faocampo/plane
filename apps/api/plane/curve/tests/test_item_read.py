# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
import json

import pytest

from plane.curve.models import Feature
from plane.curve.tests.test_feature_http import session
from plane.curve.tests.test_item_creation_commands import (
    scope as scope_fixture,
    prepared as prepared_fixture,
    material as material_fixture,
    command,
    counts,
)
from plane.curve.tests.test_item_creation_http import endpoint
from plane.db.models import WorkspaceMember

scope = scope_fixture
prepared = prepared_fixture
material = material_fixture
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def read_settings(settings):
    settings.ROOT_URLCONF = "plane.curve.tests.urls"
    settings.CURVE_ITEM_READ_ENABLED = True


def test_registered_read_has_two_assigned_stages_and_excludes_protected_material(scope, prepared, material, settings):
    created = command(scope, prepared, material)
    client, _ = session(scope, settings)
    before = counts(scope)
    response = client.get(endpoint(scope, prepared))
    assert response.status_code == 200, response.data
    assert response["Cache-Control"] == "no-store"
    assert response.data["can_create"] is True
    item = response.data["results"][0]
    assert item["id"] == created.resource_ref["resource_id"]
    assert item["initiative"]["id"] == created.resource_ref["initiative_ref"]["resource_id"]
    assert item["initiative"]["state"] == "DRAFT"
    assert item["approval_stages"] == [
        {"role": "PRODUCT", "gate_type": "PRD_APPROVAL", "approver_user_id": str(scope.member.id)},
        {"role": "TECHNICAL", "gate_type": "PLAN_APPROVAL", "approver_user_id": str(scope.admin.id)},
    ]
    raw = json.dumps(response.data)
    for excluded in (
        "scope_body",
        "description",
        "progress_note",
        "approved_prd_version_id",
        "CODE_READINESS",
        material.reference["object_id"],
        material.reference["digest"],
    ):
        assert excluded not in raw
    assert counts(scope) == before


def test_active_member_can_read_metadata_without_creation_or_document_access(scope, prepared, material, settings):
    command(scope, prepared, material)
    client, _ = session(scope, settings)
    client.force_login(scope.member)
    (material.root / material.reference["object_id"]).unlink()
    result = client.get(endpoint(scope, prepared))
    assert result.status_code == 200, result.data
    assert result.data["can_create"] is False
    assert len(result.data["results"]) == 1
    WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.member).update(is_active=False)
    assert client.get(endpoint(scope, prepared)).status_code == 403


def test_item_pagination_is_bounded_and_has_no_duplicates(scope, prepared, material, settings):
    first = command(scope, prepared, material)
    actor = {"actor_type": "HUMAN", "actor_id": str(scope.owner.id)}
    feature = Feature.objects.create(
        workspace_id=scope.workspace.id,
        product_id=scope.product.id,
        name="Second synthetic capability",
        created_by=actor,
        updated_by=actor,
    )
    changed = deepcopy(prepared[3])
    changed["feature_id"] = str(feature.id)
    changed["initiative"]["keyword"] = "SECOND-ITEM"
    second = command(scope, prepared, material, payload=changed, key="second-item")
    client, _ = session(scope, settings)
    url = endpoint(scope, prepared)
    page = client.get(url + "?page_size=1")
    assert page.status_code == 200 and len(page.data["results"]) == 1
    cursor = page.data["next_cursor"]
    assert cursor
    other = client.get(url + "?page_size=1&after=" + cursor)
    assert other.status_code == 200 and other.data["next_cursor"] is None
    assert {page.data["results"][0]["id"], other.data["results"][0]["id"]} == {
        first.resource_ref["resource_id"],
        second.resource_ref["resource_id"],
    }


@pytest.mark.parametrize(
    "query",
    ["page_size=0", "page_size=101", "page_size=01", "page_size=1&page_size=2", "after=invalid", "owner=forged"],
)
def test_invalid_item_queries_are_rejected(scope, prepared, settings, query):
    client, _ = session(scope, settings)
    response = client.get(endpoint(scope, prepared) + "?" + query)
    assert response.status_code == 422 and response["Cache-Control"] == "no-store"


def test_item_read_is_independently_disabled_and_unavailable_scopes_are_hidden(scope, prepared, settings):
    client, _ = session(scope, settings)
    settings.CURVE_ITEM_READ_ENABLED = False
    assert client.get(endpoint(scope, prepared)).status_code == 404
    settings.CURVE_ITEM_READ_ENABLED = True
    wrong = endpoint(scope, prepared).replace(str(prepared[0].id), str(scope.product.id))
    assert client.get(wrong).status_code == 404
    client.logout()
    assert client.get(endpoint(scope, prepared)).status_code == 401
