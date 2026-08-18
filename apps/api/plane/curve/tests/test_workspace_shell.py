import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from plane.curve.models import AuditEvent, AuditOutcome, PolicyDecision, PolicyEffect
from plane.curve.views import CurveWorkspaceShellEndpoint
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
    CURVE_ENVIRONMENT="LOCAL",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api-test",
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
    decision = PolicyDecision.objects.get(workspace_id=workspace.id)
    audit = AuditEvent.objects.get(workspace_id=workspace.id)
    assert decision.effect == PolicyEffect.ALLOW
    assert decision.reason_codes == ["POLICY_ALLOWED"]
    assert decision.permitted_projection == [
        "WORKSPACE_ID",
        "WORKSPACE_SLUG",
        "SHELL_STATE",
    ]
    assert audit.outcome == AuditOutcome.ALLOWED
    assert audit.policy_decision_ref["resource_id"] == str(decision.id)


@override_settings(
    ROOT_URLCONF="plane.curve.tests.urls",
    CURVE_ENABLED=False,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha"}),
    CURVE_ENVIRONMENT="LOCAL",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api-test",
)
def test_disabled_curve_shell_is_inaccessible():
    user = _user("disabled@example.com")
    workspace = _workspace("Alpha", "alpha", user)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/v1/workspaces/alpha/curve/")

    assert response.status_code == 404
    decision = PolicyDecision.objects.get(workspace_id=workspace.id)
    audit = AuditEvent.objects.get(workspace_id=workspace.id)
    assert decision.effect == PolicyEffect.DENY
    assert decision.reason_codes == ["FEATURE_DISABLED"]
    assert audit.outcome == AuditOutcome.DENIED


@override_settings(
    ROOT_URLCONF="plane.curve.tests.urls",
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha", "beta"}),
    CURVE_ENVIRONMENT="LOCAL",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api-test",
)
def test_cross_workspace_request_is_denied_before_curve_view(monkeypatch):
    alpha_user = _user("alpha@example.com")
    beta_user = _user("beta@example.com")
    _workspace("Alpha", "alpha", alpha_user)
    beta = _workspace("Beta", "beta", beta_user)
    client = APIClient()
    client.force_authenticate(user=alpha_user)

    def fail_if_view_runs(*args, **kwargs):
        raise AssertionError("Curve view ran before authorization")

    monkeypatch.setattr(CurveWorkspaceShellEndpoint, "get", fail_if_view_runs)

    response = client.get("/api/v1/workspaces/beta/curve/")

    assert response.status_code == 403
    decision = PolicyDecision.objects.get(workspace_id=beta.id)
    audit = AuditEvent.objects.get(workspace_id=beta.id)
    assert decision.effect == PolicyEffect.DENY
    assert decision.reason_codes == ["INACTIVE_MEMBERSHIP", "ROLE_NOT_ALLOWED"]
    assert audit.outcome == AuditOutcome.DENIED


@override_settings(
    ROOT_URLCONF="plane.curve.tests.urls",
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha"}),
    CURVE_ENVIRONMENT="",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api-test",
)
def test_invalid_environment_denies_and_records_context_failure():
    user = _user("invalid-environment@example.com")
    workspace = _workspace("Alpha", "alpha", user)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/v1/workspaces/alpha/curve/")

    assert response.status_code == 403
    decision = PolicyDecision.objects.get(workspace_id=workspace.id)
    assert decision.effect == PolicyEffect.DENY
    assert decision.reason_codes == ["POLICY_CONTEXT_INVALID"]


@override_settings(
    ROOT_URLCONF="plane.curve.tests.urls",
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha"}),
    CURVE_ENVIRONMENT="LOCAL",
    CURVE_POLICY_RECORDER_ACTOR_ID="",
)
def test_missing_recorder_fails_closed_without_partial_evidence():
    user = _user("missing-recorder@example.com")
    workspace = _workspace("Alpha", "alpha", user)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/v1/workspaces/alpha/curve/")

    assert response.status_code == 403
    assert PolicyDecision.objects.filter(workspace_id=workspace.id).count() == 0
    assert AuditEvent.objects.filter(workspace_id=workspace.id).count() == 0
