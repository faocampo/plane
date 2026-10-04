# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Request-level tests with real DRF/session authentication and synthetic runtime.

ORM selectors are mocked here. PostgreSQL membership, tenant constraints and
concurrent persistence behavior require the separate isolated integration suite.
"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock
import uuid

import pytest
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse
from rest_framework.test import APIRequestFactory

from plane.curve import prd_read_views
from plane.curve.prd_read_context import PrdReadUnavailable
from plane.curve.tests.test_prd_read_context import context, uid, NOW  # noqa: F401

pytestmark = pytest.mark.unit


@pytest.fixture
def api(context, settings, monkeypatch):  # noqa: F811
    settings.CURVE_ENABLED = True
    settings.CURVE_ENABLED_WORKSPACE_SLUGS = frozenset({"synthetic-workspace"})
    settings.CURVE_PRD_READ_ENABLED = True
    settings.CURVE_PRD_READ_RUNTIME = context.runtime
    monkeypatch.setattr(prd_read_views, "resolve_prd_read_scope", lambda **kwargs: deepcopy(context.scope))
    monkeypatch.setattr(
        prd_read_views.timezone,
        "now",
        lambda: prd_read_views.timezone.datetime.fromisoformat(NOW.replace("Z", "+00:00")),
    )
    user = SimpleNamespace(id=uuid.UUID(uid(3)), is_authenticated=True, is_active=True, is_bot=False)
    return context, user


def get(api, *, user=None, method="get", params=None):
    _, default_user = api
    request = getattr(APIRequestFactory(), method)(
        "/api/v1/workspaces/synthetic-workspace/curve/initiatives/" + uid(2) + "/prd/review-context/", data=params or {}
    )
    request.user = default_user if user is None else user
    response = prd_read_views.CurvePrdReviewContextEndpoint.as_view()(
        request,
        slug="synthetic-workspace",
        initiative_id=uuid.UUID(uid(2)),
    )
    response.render()
    return response


def assert_hidden(response):
    assert response.status_code == 404
    assert response.data == {
        "type": "urn:curve:problem:prd-context-unavailable",
        "title": "PRD context unavailable",
        "status": 404,
        "code": "PRD_CONTEXT_UNAVAILABLE",
    }
    assert response["Cache-Control"] == "no-store"


def test_authenticated_get_exposes_only_closed_metadata(api):
    response = get(api)
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert response.data["schema_version"] == "curve.prd-review-context/v1-candidate"
    assert response.data["command_preconditions"]["commandETag"] == '"7"'
    assert all(not value["available"] for value in response.data["capabilities"].values())
    assert api[0].runtime.calls == ["authorize", "read", "authorize", "fence"]


def test_anonymous_and_inactive_session_user_are_hidden(api):
    for user in [AnonymousUser(), SimpleNamespace(is_authenticated=True, is_active=False)]:
        assert_hidden(get(api, user=user))
    assert api[0].runtime.calls == []


@pytest.mark.parametrize("flag", ["CURVE_ENABLED", "CURVE_PRD_READ_ENABLED"])
def test_disabled_feature_does_not_read_records(api, settings, flag):
    setattr(settings, flag, False)
    assert_hidden(get(api))
    assert api[0].runtime.calls == []


def test_wrong_workspace_enablement_is_hidden(api, settings):
    settings.CURVE_ENABLED_WORKSPACE_SLUGS = frozenset({"different-workspace"})
    assert_hidden(get(api))
    assert api[0].runtime.calls == []


def test_missing_trusted_runtime_is_explicitly_unavailable(api, settings):
    settings.CURVE_PRD_READ_RUNTIME = None
    response = get(api, params={"role": "ADMIN", "readiness": "READY", "allow": "true"})
    assert_hidden(response)
    assert "checkpoint" not in response.data
    assert api[0].runtime.calls == []


def test_mutation_enablement_does_not_enable_read(api, settings):
    settings.CURVE_PRD_COMMANDS_ENABLED = True
    settings.CURVE_PRD_READ_ENABLED = False
    assert_hidden(get(api))


def test_read_enablement_does_not_need_or_activate_commands(api, settings):
    settings.CURVE_PRD_COMMANDS_ENABLED = False
    response = get(api)
    assert response.status_code == 200
    assert settings.CURVE_PRD_COMMANDS_ENABLED is False
    assert all(not item["available"] for item in response.data["capabilities"].values())


def test_provider_diagnostics_never_leave_error_boundary(api):
    def fail(**kwargs):
        raise ValueError("Synthetic protected provider diagnostic sentinel")

    api[0].runtime.observe = fail
    response = get(api)
    assert_hidden(response)
    assert b"sentinel" not in response.content


def test_post_is_not_a_command_or_capture(api):
    assert_hidden(get(api, method="post", params={"rationale": "Synthetic secret sentinel"}))
    assert api[0].runtime.calls == []


def test_scope_denial_and_absent_object_are_indistinguishable(api, monkeypatch):
    def missing(**kwargs):
        raise PrdReadUnavailable

    monkeypatch.setattr(prd_read_views, "resolve_prd_read_scope", missing)
    assert_hidden(get(api))
    assert api[0].runtime.calls == []


def test_route_uses_existing_versioned_mount(settings):
    settings.ROOT_URLCONF = "plane.curve.tests.urls"
    path = reverse("curve-prd-review-context", kwargs={"slug": "synthetic-workspace", "initiative_id": uid(2)})
    assert path.endswith(f"/workspaces/synthetic-workspace/curve/initiatives/{uid(2)}/prd/review-context/")


def test_actual_scope_selector_uses_active_human_membership_and_exact_tenant(monkeypatch):
    from plane.db.models import Workspace, WorkspaceMember
    from plane.curve.models import Initiative

    workspaces, members, initiatives = MagicMock(), MagicMock(), MagicMock()
    workspaces.filter.return_value.values.return_value.first.return_value = {"id": uuid.UUID(uid(1))}
    members.filter.return_value.exists.return_value = True
    initiatives.filter.return_value.values.return_value.first.return_value = {
        "version": 7,
        "pending_scope_reopening_id": None,
    }
    monkeypatch.setattr(Workspace, "objects", workspaces)
    monkeypatch.setattr(WorkspaceMember, "objects", members)
    monkeypatch.setattr(Initiative, "objects", initiatives)
    user = SimpleNamespace(id=uuid.UUID(uid(3)), is_authenticated=True, is_active=True, is_bot=False)
    result = prd_read_views.resolve_prd_read_scope(
        request=SimpleNamespace(user=user),
        workspace_slug="synthetic-workspace",
        initiative_id=uid(2),
    )
    assert result == {"workspace_id": uid(1), "initiative_id": uid(2), "actor_id": uid(3), "initiative_version": 7}
    members.filter.assert_called_once_with(
        workspace_id=uuid.UUID(uid(1)),
        member_id=user.id,
        is_active=True,
        member__is_active=True,
        member__is_bot=False,
    )
    initiatives.filter.assert_called_once_with(workspace_id=uuid.UUID(uid(1)), id=uid(2))
    initiatives.filter.return_value.values.assert_called_once_with("version", "pending_scope_reopening_id")
    members.filter.return_value.exists.return_value = False
    initiatives.reset_mock()
    with pytest.raises(PrdReadUnavailable):
        prd_read_views.resolve_prd_read_scope(
            request=SimpleNamespace(user=user), workspace_slug="synthetic-workspace", initiative_id=uid(2)
        )
    initiatives.filter.assert_not_called()
    user.is_bot = True
    workspaces.reset_mock()
    with pytest.raises(PrdReadUnavailable):
        prd_read_views.resolve_prd_read_scope(
            request=SimpleNamespace(user=user), workspace_slug="synthetic-workspace", initiative_id=uid(2)
        )
    workspaces.filter.assert_not_called()
