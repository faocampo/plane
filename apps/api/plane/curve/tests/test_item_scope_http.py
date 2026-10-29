# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from django.middleware.csrf import _get_new_csrf_string
from django.urls import reverse
from rest_framework.test import APIClient

from plane.curve.tests.test_item_scope_commands import (
    scope as native_scope,
    parent as native_parent,
    material as native_material,
    enabled as scope_enabled,
    counts,
)

scope, parent, material, enabled = native_scope, native_parent, native_material, scope_enabled
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def api_settings(settings):
    settings.ROOT_URLCONF = "plane.curve.tests.urls"


def session(scope, settings):
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(scope.member)
    token = _get_new_csrf_string()
    client.cookies[settings.CSRF_COOKIE_NAME] = token
    return client, token


def endpoint(scope, parent):
    return reverse(
        "curve-roadmap-item-scope",
        kwargs={
            "slug": scope.workspace.slug,
            "product_id": scope.product.id,
            "roadmap_id": parent.id,
        },
    )


def headers(parent, token):
    return dict(
        HTTP_X_CSRFTOKEN=token,
        HTTP_IDEMPOTENCY_KEY="synthetic-scope-http",
        HTTP_IF_MATCH=f'"curve-roadmap:{parent.id}:v{parent.version}"',
    )


def test_session_csrf_preparation_and_exact_replay(scope, parent, settings):
    client, token = session(scope, settings)
    url = endpoint(scope, parent)
    payload = {"body": "Synthetic scope"}
    request_headers = headers(parent, token)
    denied = client.post(
        url, payload, format="json", **{k: v for k, v in request_headers.items() if k != "HTTP_X_CSRFTOKEN"}
    )
    assert denied.status_code == 403 and counts() == [0, 0, 0]
    response = client.post(url, payload, format="json", **request_headers)
    assert response.status_code == 201, response.data
    assert response["Cache-Control"] == "no-store"
    assert response["Idempotent-Replay"] == "false"
    assert set(response.data) == {"resource_ref"}
    assert "Synthetic scope" not in str(response.data)
    replay = client.post(url, payload, format="json", **request_headers)
    assert replay.status_code == 201 and replay.data == response.data
    assert replay["Idempotent-Replay"] == "true" and counts() == [1, 1, 1]
    client.logout()
    assert client.post(url, payload, format="json", **request_headers).status_code == 401
    assert counts() == [1, 1, 1]


@pytest.mark.parametrize(
    "variant,status",
    [
        ("disabled", 404),
        ("missing_version", 428),
        ("stale_version", 412),
        ("weak_version", 412),
        ("missing_key", 422),
        ("extra_field", 422),
        ("empty", 422),
        ("query", 422),
        ("get", 405),
    ],
)
def test_invalid_or_disabled_scope_requests_have_no_effect(scope, parent, settings, variant, status):
    client, token = session(scope, settings)
    url = endpoint(scope, parent)
    request_headers = headers(parent, token)
    payload = {"body": "Synthetic scope"}
    if variant == "disabled":
        settings.CURVE_ITEM_SCOPE_PREPARATION_ENABLED = False
    elif variant == "missing_version":
        request_headers.pop("HTTP_IF_MATCH")
    elif variant == "stale_version":
        request_headers["HTTP_IF_MATCH"] = f'"curve-roadmap:{parent.id}:v999"'
    elif variant == "weak_version":
        request_headers["HTTP_IF_MATCH"] = "W/" + request_headers["HTTP_IF_MATCH"]
    elif variant == "missing_key":
        request_headers.pop("HTTP_IDEMPOTENCY_KEY")
    elif variant == "extra_field":
        payload["grants"] = {}
    elif variant == "empty":
        payload["body"] = ""
    elif variant == "query":
        url += "?actor=synthetic"
    response = client.get(url) if variant == "get" else client.post(url, payload, format="json", **request_headers)
    assert response.status_code == status, response.data
    assert counts() == [0, 0, 0]
