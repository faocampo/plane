import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from plane.db.models import User, Workspace, WorkspaceMember


pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def _user(email):
    return User.objects.create(email=email, username=email)


def _workspace(name, slug, owner):
    workspace = Workspace.objects.create(name=name, slug=slug, owner=owner)
    WorkspaceMember.objects.create(
        workspace=workspace,
        member=owner,
        role=20,
        is_active=True,
    )
    return workspace


@override_settings(
    ROOT_URLCONF="plane.curve.tests.urls",
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha"}),
)
def test_authorized_member_can_open_empty_curve_shell():
    user = _user("alpha@example.com")
    workspace = _workspace("Alpha", "alpha", user)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/v1/workspaces/alpha/curve/")

    assert response.status_code == 200
    assert response.json() == {
        "workspace_id": str(workspace.id),
        "workspace_slug": "alpha",
        "state": "EMPTY",
    }


@override_settings(
    ROOT_URLCONF="plane.curve.tests.urls",
    CURVE_ENABLED=False,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha"}),
)
def test_disabled_curve_shell_is_inaccessible():
    user = _user("disabled@example.com")
    _workspace("Alpha", "alpha", user)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/v1/workspaces/alpha/curve/")

    assert response.status_code == 404


@override_settings(
    ROOT_URLCONF="plane.curve.tests.urls",
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha", "beta"}),
)
def test_cross_workspace_request_is_denied_before_curve_view(monkeypatch):
    alpha_user = _user("alpha@example.com")
    beta_user = _user("beta@example.com")
    _workspace("Alpha", "alpha", alpha_user)
    _workspace("Beta", "beta", beta_user)
    client = APIClient()
    client.force_authenticate(user=alpha_user)

    def fail_if_view_queries_workspace(*args, **kwargs):
        raise AssertionError("Curve view queried workspace state before authorization")

    monkeypatch.setattr(Workspace.objects, "only", fail_if_view_queries_workspace)

    response = client.get("/api/v1/workspaces/beta/curve/")

    assert response.status_code == 403
