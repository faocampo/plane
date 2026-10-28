# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from django.middleware.csrf import _get_new_csrf_string
from django.urls import reverse
from rest_framework.test import APIClient

from plane.curve.tests.test_feature_commands import counts
from plane.curve.tests.test_roadmap_commands import scope as roadmap_scope
from plane.db.models import WorkspaceMember

scope = roadmap_scope
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def api_settings(settings):
    settings.ROOT_URLCONF = "plane.curve.tests.urls"
    settings.CURVE_FEATURE_COMMANDS_ENABLED = True


def endpoint(scope, feature_id=None):
    kwargs = {"slug": scope.workspace.slug, "product_id": scope.product.id}
    if feature_id:
        kwargs["feature_id"] = feature_id
    return reverse("curve-feature-detail" if feature_id else "curve-features", kwargs=kwargs)


def session(scope, settings):
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(scope.owner)
    token = _get_new_csrf_string()
    client.cookies[settings.CSRF_COOKIE_NAME] = token
    return client, token


def test_registered_session_create_update_read_and_replay(scope, settings):
    client, token = session(scope, settings)
    payload = {"name": "Synthetic Feature", "description": None}
    denied = client.post(endpoint(scope), payload, format="json", HTTP_IDEMPOTENCY_KEY="synthetic-http-create")
    assert denied.status_code == 403
    assert counts(scope) == [0, 0, 0, 0]
    created = client.post(
        endpoint(scope), payload, format="json", HTTP_IDEMPOTENCY_KEY="synthetic-http-create", HTTP_X_CSRFTOKEN=token
    )
    assert created.status_code == 201, created.data
    identity = created.data["resource_ref"]["resource_id"]
    detail = client.get(endpoint(scope, identity))
    assert detail.status_code == 200, detail.data
    assert detail["ETag"] == created["ETag"]
    assert detail.data["can_edit"] is True
    updated = client.patch(
        endpoint(scope, identity),
        {**payload, "name": "Updated Feature"},
        format="json",
        HTTP_IF_MATCH=detail["ETag"],
        HTTP_IDEMPOTENCY_KEY="synthetic-http-update",
        HTTP_X_CSRFTOKEN=token,
    )
    assert updated.status_code == 200, updated.data
    replay = client.patch(
        endpoint(scope, identity),
        {**payload, "name": "Updated Feature"},
        format="json",
        HTTP_IF_MATCH=detail["ETag"],
        HTTP_IDEMPOTENCY_KEY="synthetic-http-update",
        HTTP_X_CSRFTOKEN=token,
    )
    assert replay.status_code == 200, replay.data
    assert replay["Idempotent-Replay"] == "true"
    assert replay.data == updated.data
    assert counts(scope) == [1, 2, 2, 2]
    listing = client.get(endpoint(scope))
    assert listing.status_code == 200 and listing["Cache-Control"] == "no-store"
    assert listing.data["results"][0]["name"] == "Updated Feature"
    assert "description" not in listing.data["results"][0]
    client.logout()
    assert client.get(endpoint(scope)).status_code == 401


def test_disabled_registered_endpoints_and_lost_membership(scope, settings):
    client, token = session(scope, settings)
    settings.CURVE_FEATURE_COMMANDS_ENABLED = False
    assert client.get(endpoint(scope)).status_code == 404
    settings.CURVE_FEATURE_COMMANDS_ENABLED = True
    assert client.get(endpoint(scope)).status_code == 200
    WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.owner).update(is_active=False)
    denied = client.post(
        endpoint(scope),
        {"name": "Example", "description": None},
        format="json",
        HTTP_IDEMPOTENCY_KEY="synthetic-removed",
        HTTP_X_CSRFTOKEN=token,
    )
    assert denied.status_code == 403, denied.data
    assert counts(scope) == [0, 0, 0, 0]


@pytest.mark.parametrize("name", ["bad\x00name", "bad\ud800name", "bad\udfffname"])
def test_unsupported_text_returns_validation_and_preserves_retry_key(scope, settings, name):
    import json

    client, token = session(scope, settings)
    headers = {"HTTP_IDEMPOTENCY_KEY": "synthetic-text-retry", "HTTP_X_CSRFTOKEN": token}
    response = client.post(
        endpoint(scope), json.dumps({"name": name, "description": None}), content_type="application/json", **headers
    )
    assert response.status_code == 422, response.data
    assert counts(scope) == [0, 0, 0, 0]
    accepted = client.post(endpoint(scope), {"name": "Valid Feature 🚀", "description": None}, format="json", **headers)
    assert accepted.status_code == 201, accepted.data
    assert counts(scope) == [1, 1, 1, 1]
