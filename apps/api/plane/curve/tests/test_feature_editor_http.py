# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from plane.curve.tests.test_roadmap_commands import scope as roadmap_scope

scope = roadmap_scope
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def endpoint(scope, grant_id=None):
    kwargs = {"slug": scope.workspace.slug, "product_id": scope.product.id}
    if grant_id:
        kwargs["grant_id"] = grant_id
    return reverse("curve-feature-editor-detail" if grant_id else "curve-feature-editors", kwargs=kwargs)


def client(scope):
    result = APIClient()
    result.force_authenticate(scope.owner)
    return result


def test_registered_endpoints_default_off(scope, settings):
    settings.CURVE_FEATURE_EDITOR_COMMANDS_ENABLED = False
    response = client(scope).get(endpoint(scope))
    assert response.status_code == 404
    assert response["Cache-Control"] == "no-store"


def test_registered_grant_read_revoke_flow(scope, settings):
    settings.CURVE_FEATURE_EDITOR_COMMANDS_ENABLED = True
    api = client(scope)
    created = api.post(
        endpoint(scope), {"member_id": str(scope.member.id)}, format="json", HTTP_IDEMPOTENCY_KEY="synthetic-http-grant"
    )
    assert created.status_code == 201, created.data
    grant_id = created.data["resource_ref"]["resource_id"]
    detail = api.get(endpoint(scope, grant_id))
    assert detail.status_code == 200, detail.data
    assert detail.data["status"] == "ACTIVE"
    assert detail["ETag"] == created["ETag"]
    revoked = api.delete(
        endpoint(scope, grant_id),
        {},
        format="json",
        HTTP_IF_MATCH=detail["ETag"],
        HTTP_IDEMPOTENCY_KEY="synthetic-http-revoke",
    )
    assert revoked.status_code == 200, revoked.data
    history = api.get(endpoint(scope, grant_id))
    assert history.data["status"] == "REVOKED"
    assert history["ETag"] == revoked["ETag"]
    listing = api.get(endpoint(scope))
    assert listing.status_code == 200
    assert len(listing.data["results"]) == 1
    assert listing["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "query", ["?page_size=0", "?page_size=101", "?after=invalid", "?page_size=1&page_size=2", "?extra=1"]
)
def test_closed_list_query(scope, settings, query):
    settings.CURVE_FEATURE_EDITOR_COMMANDS_ENABLED = True
    assert client(scope).get(endpoint(scope) + query).status_code == 422


def test_real_session_csrf_and_replay(scope, settings):
    from django.middleware.csrf import _get_new_csrf_string
    from plane.curve.tests.test_feature_editor_commands import counts

    settings.CURVE_FEATURE_EDITOR_COMMANDS_ENABLED = True
    api = APIClient(enforce_csrf_checks=True)
    api.force_login(scope.owner)
    payload = {"member_id": str(scope.member.id)}
    denied = api.post(endpoint(scope), payload, format="json", HTTP_IDEMPOTENCY_KEY="synthetic-session-grant")
    assert denied.status_code == 403
    assert counts(scope) == [0, 0, 0, 0]
    token = _get_new_csrf_string()
    api.cookies[settings.CSRF_COOKIE_NAME] = token
    accepted = api.post(
        endpoint(scope), payload, format="json", HTTP_IDEMPOTENCY_KEY="synthetic-session-grant", HTTP_X_CSRFTOKEN=token
    )
    assert accepted.status_code == 201, accepted.data
    replay = api.post(
        endpoint(scope), payload, format="json", HTTP_IDEMPOTENCY_KEY="synthetic-session-grant", HTTP_X_CSRFTOKEN=token
    )
    assert replay.status_code == 201, replay.data
    assert replay["Idempotent-Replay"] == "true"
    assert replay.data == accepted.data
    assert counts(scope) == [1, 1, 1, 1]
    grant_id = accepted.data["resource_ref"]["resource_id"]
    revoked = api.delete(
        endpoint(scope, grant_id),
        {},
        format="json",
        HTTP_IF_MATCH=accepted["ETag"],
        HTTP_IDEMPOTENCY_KEY="synthetic-session-revoke",
        HTTP_X_CSRFTOKEN=token,
    )
    assert revoked.status_code == 200, revoked.data
    api.logout()
    assert api.get(endpoint(scope, grant_id)).status_code == 401


def test_session_read_rechecks_membership(scope, settings):
    from plane.db.models import WorkspaceMember

    settings.CURVE_FEATURE_EDITOR_COMMANDS_ENABLED = True
    api = APIClient(enforce_csrf_checks=True)
    api.force_login(scope.owner)
    assert api.get(endpoint(scope)).status_code == 200
    WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.owner).update(is_active=False)
    assert api.get(endpoint(scope)).status_code == 404
