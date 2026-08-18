from types import SimpleNamespace

import pytest
from django.test import override_settings

from plane.curve.models import (
    AuditEvent,
    AuditOutcome,
    DomainEvent,
    IdempotencyRecord,
    Operation,
    OutboxEvent,
    PolicyDecision,
)
from plane.curve.policy_services import (
    CurvePolicyDenied,
    assert_active_mutation_receipt,
    authorize_query,
    start_foundation_probe,
)
from plane.db.models import User, Workspace, WorkspaceMember
import plane.curve.policy_services as policy_services
import plane.curve.services as curve_services


pytestmark = [pytest.mark.unit, pytest.mark.django_db]


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


def _request(user):
    return SimpleNamespace(user=user)


@override_settings(
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha"}),
    CURVE_ENVIRONMENT="LOCAL",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api-test",
)
def test_request_local_cache_reuses_exact_query_decision():
    user = _user("cache@example.com")
    workspace = _workspace("Alpha", "alpha", user)
    request = _request(user)

    first = authorize_query(
        request=request,
        action="CURVE.SHELL.VIEW",
        workspace_slug="alpha",
        resource_type="WORKSPACE",
    )
    second = authorize_query(
        request=request,
        action="CURVE.SHELL.VIEW",
        workspace_slug="alpha",
        resource_type="WORKSPACE",
    )

    assert second is first
    assert PolicyDecision.objects.filter(workspace_id=workspace.id).count() == 1
    assert AuditEvent.objects.filter(workspace_id=workspace.id).count() == 1


@override_settings(
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha"}),
    CURVE_ENVIRONMENT="LOCAL",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api-test",
)
def test_query_projection_loads_only_after_decision_is_recorded(monkeypatch):
    user = _user("projection-order@example.com")
    _workspace("Alpha", "alpha", user)
    state = {"recorded": False}
    original_record = policy_services._record_query_evidence
    original_projection = policy_services._load_permitted_projection

    def record_evidence(**kwargs):
        decision = original_record(**kwargs)
        state["recorded"] = True
        return decision

    def load_projection(**kwargs):
        assert state["recorded"] is True
        return original_projection(**kwargs)

    monkeypatch.setattr(policy_services, "_record_query_evidence", record_evidence)
    monkeypatch.setattr(policy_services, "_load_permitted_projection", load_projection)

    authorize_query(
        request=_request(user),
        action="CURVE.SHELL.VIEW",
        workspace_slug="alpha",
        resource_type="WORKSPACE",
    )


@override_settings(
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha"}),
    CURVE_ENVIRONMENT="LOCAL",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api-test",
)
def test_inactive_member_denies_before_operation_metadata_lookup(monkeypatch):
    owner = _user("metadata-owner@example.com")
    _workspace("Alpha", "alpha", owner)
    outsider = _user("metadata-outsider@example.com")

    def fail_operation_lookup(**kwargs):
        raise AssertionError("Operation metadata must not load before membership authorization")

    monkeypatch.setattr(policy_services, "_operation_resource", fail_operation_lookup)

    with pytest.raises(CurvePolicyDenied) as denial:
        authorize_query(
            request=_request(outsider),
            action="CURVE.OPERATION.READ",
            workspace_slug="alpha",
            resource_type="OPERATION",
            resource_id="22222222-2222-4222-8222-222222222222",
        )

    assert denial.value.reason_codes[0] == "INACTIVE_MEMBERSHIP"


@override_settings(
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha"}),
    CURVE_ENVIRONMENT="LOCAL",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api-test",
)
def test_separate_requests_allocate_monotonic_policy_and_audit_sequences():
    user = _user("sequence@example.com")
    workspace = _workspace("Alpha", "alpha", user)

    for _ in range(2):
        authorize_query(
            request=_request(user),
            action="CURVE.SHELL.VIEW",
            workspace_slug="alpha",
            resource_type="WORKSPACE",
        )

    assert list(
        PolicyDecision.objects.filter(workspace_id=workspace.id).order_by("sequence").values_list("sequence", flat=True)
    ) == [1, 2]
    assert list(
        AuditEvent.objects.filter(workspace_id=workspace.id).order_by("sequence").values_list("sequence", flat=True)
    ) == [1, 2]


@override_settings(
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha"}),
    CURVE_ENVIRONMENT="LOCAL",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api-test",
)
def test_decision_rolls_back_when_linked_audit_cannot_be_recorded(monkeypatch):
    user = _user("rollback@example.com")
    workspace = _workspace("Alpha", "alpha", user)

    def fail_audit(**kwargs):
        raise RuntimeError("synthetic policy audit failure")

    monkeypatch.setattr(curve_services, "_append_audit_event", fail_audit)

    with pytest.raises(RuntimeError, match="synthetic policy audit failure"):
        authorize_query(
            request=_request(user),
            action="CURVE.SHELL.VIEW",
            workspace_slug="alpha",
            resource_type="WORKSPACE",
        )

    assert PolicyDecision.objects.filter(workspace_id=workspace.id).count() == 0
    assert AuditEvent.objects.filter(workspace_id=workspace.id).count() == 0


@override_settings(
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha"}),
    CURVE_ENVIRONMENT="LOCAL",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api-test",
)
def test_recorder_identity_is_trusted_configuration_only():
    user = _user("recorder@example.com")
    workspace = _workspace("Alpha", "alpha", user)
    request = _request(user)
    request.recorded_by = {"actor_type": "HUMAN", "actor_id": "attacker"}

    authorize_query(
        request=request,
        action="CURVE.SHELL.VIEW",
        workspace_slug="alpha",
        resource_type="WORKSPACE",
    )

    assert PolicyDecision.objects.get(workspace_id=workspace.id).recorded_by == {
        "actor_type": "SERVICE",
        "actor_id": "curve-api-test",
    }


@override_settings(
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha"}),
    CURVE_ENVIRONMENT="STAGING",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api-test",
)
def test_denied_foundation_probe_commits_only_decision_and_denied_audit():
    user = _user("staging-denial@example.com")
    workspace = _workspace("Alpha", "alpha", user)

    with pytest.raises(CurvePolicyDenied) as denial:
        start_foundation_probe(
            request=_request(user),
            workspace_slug="alpha",
            raw_idempotency_key="staging-denial",
            canonical_request=b'{"command":"CREATE_FOUNDATION_PROBE"}',
        )

    assert denial.value.reason_codes == ("ENVIRONMENT_NOT_ALLOWED",)
    decision = PolicyDecision.objects.get(workspace_id=workspace.id)
    audit = AuditEvent.objects.get(workspace_id=workspace.id)
    assert audit.outcome == AuditOutcome.DENIED
    assert audit.policy_decision_ref["resource_id"] == str(decision.id)
    assert Operation.objects.filter(workspace_id=workspace.id).count() == 0
    assert DomainEvent.objects.filter(workspace_id=workspace.id).count() == 0
    assert OutboxEvent.objects.filter(workspace_id=workspace.id).count() == 0
    assert IdempotencyRecord.objects.filter(workspace_id=workspace.id).count() == 0


@override_settings(
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha"}),
    CURVE_ENVIRONMENT="LOCAL",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api-test",
)
def test_genuine_mutation_receipt_expires_after_callback(monkeypatch):
    user = _user("receipt-expiry@example.com")
    workspace = _workspace("Alpha", "alpha", user)
    captured = {}
    original = curve_services._create_operation_authorized

    def capture_receipt(**kwargs):
        captured["receipt"] = kwargs["authorization_receipt"]
        return original(**kwargs)

    monkeypatch.setattr(
        curve_services,
        "_create_operation_authorized",
        capture_receipt,
    )
    start_foundation_probe(
        request=_request(user),
        workspace_slug="alpha",
        raw_idempotency_key="receipt-expiry",
        canonical_request=b'{"command":"CREATE_FOUNDATION_PROBE"}',
    )

    with pytest.raises(PermissionError, match="active Curve mutation"):
        assert_active_mutation_receipt(
            captured["receipt"],
            action="CURVE.FOUNDATION_PROBE.START",
            workspace_id=workspace.id,
            resource_ref={
                "resource_type": "WORKSPACE",
                "resource_id": str(workspace.id),
                "resource_version": 1,
            },
        )
