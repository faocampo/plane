# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy

import pytest
from django.urls import reverse

from plane.curve.tests.test_feature_http import session
from plane.curve.tests.test_item_creation_commands import (
    scope as scope_fixture,
    prepared as prepared_fixture,
    material as material_fixture,
    counts,
)

scope = scope_fixture
prepared = prepared_fixture
material = material_fixture
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def api_settings(settings):
    settings.ROOT_URLCONF = "plane.curve.tests.urls"
    settings.CURVE_ITEM_CREATION_ENABLED = True


def endpoint(scope, prepared):
    return reverse(
        "curve-roadmap-item-create",
        kwargs={"slug": scope.workspace.slug, "product_id": scope.product.id, "roadmap_id": prepared[0].id},
    )


def payload(prepared, material):
    value = deepcopy(prepared[3])
    value["scope_body"] = material.reference
    return value


def headers(prepared, token):
    return {
        "HTTP_X_CSRFTOKEN": token,
        "HTTP_IDEMPOTENCY_KEY": "synthetic-http-item",
        "HTTP_IF_MATCH": f'"curve-roadmap:{prepared[0].id}:v{prepared[0].version}"',
    }


def test_session_creation_requires_csrf_and_retains_exact_replay(scope, prepared, material, settings):
    client, token = session(scope, settings)
    before = counts(scope)
    request_headers = headers(prepared, token)
    no_csrf = {k: v for k, v in request_headers.items() if k != "HTTP_X_CSRFTOKEN"}
    denied = client.post(endpoint(scope, prepared), payload(prepared, material), format="json", **no_csrf)
    assert denied.status_code == 403 and counts(scope) == before
    created = client.post(endpoint(scope, prepared), payload(prepared, material), format="json", **request_headers)
    assert created.status_code == 201, created.data
    assert created["Cache-Control"] == "no-store"
    assert created["Idempotent-Replay"] == "false"
    assert created["Location"].endswith(created.data["resource_ref"]["initiative_ref"]["resource_id"] + "/")
    after = counts(scope)
    replay = client.post(endpoint(scope, prepared), payload(prepared, material), format="json", **request_headers)
    assert replay.status_code == 201 and replay.data == created.data
    assert replay["Idempotent-Replay"] == "true" and counts(scope) == after
    client.logout()
    response = client.post(endpoint(scope, prepared), payload(prepared, material), format="json", **request_headers)
    assert response.status_code == 401 and counts(scope) == after


@pytest.mark.parametrize(
    "variant,expected",
    [
        ("disabled", 404),
        ("missing_version", 428),
        ("foreign_version", 412),
        ("stale_version", 412),
        ("missing_key", 422),
        ("query", 422),
        ("code_approver", 422),
    ],
)
def test_invalid_or_disabled_requests_leave_no_partial_pair(scope, prepared, material, settings, variant, expected):
    client, token = session(scope, settings)
    request_headers = headers(prepared, token)
    value = payload(prepared, material)
    url = endpoint(scope, prepared)
    if variant == "disabled":
        settings.CURVE_ITEM_CREATION_ENABLED = False
    elif variant == "missing_version":
        request_headers.pop("HTTP_IF_MATCH")
    elif variant == "foreign_version":
        request_headers["HTTP_IF_MATCH"] = f'"curve-roadmap:{scope.product.id}:v1"'
    elif variant == "stale_version":
        request_headers["HTTP_IF_MATCH"] = f'"curve-roadmap:{prepared[0].id}:v{prepared[0].version + 1}"'
    elif variant == "missing_key":
        request_headers.pop("HTTP_IDEMPOTENCY_KEY")
    elif variant == "query":
        url += "?owner=forged"
    else:
        value["initiative"]["gate_assignments"][0]["gate_type"] = "CODE_READINESS"
    before = counts(scope)
    response = client.post(url, value, format="json", **request_headers)
    assert response.status_code == expected, response.data
    assert response["Cache-Control"] == "no-store"
    assert counts(scope) == before
