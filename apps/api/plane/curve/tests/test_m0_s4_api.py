import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.middleware.csrf import _get_new_csrf_string
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from plane.curve.models import DomainEvent, IdempotencyRecord, Operation, OperationStatus, OperationType
from plane.curve.policy_services import (
    start_foundation_probe,
    transition_operation_with_service_authorization,
)
from plane.curve.temporal.constants import TEMPORAL_DESTINATION, operation_workflow_id
from plane.db.models import User, Workspace, WorkspaceMember


pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def _curve_settings(settings):
    settings.DEBUG = True
    settings.CURVE_ENABLED = True
    settings.CURVE_ENABLED_WORKSPACE_SLUGS = frozenset({"alpha", "beta"})
    settings.CURVE_ENVIRONMENT = "LOCAL"
    settings.CURVE_POLICY_RECORDER_ACTOR_ID = "curve-api-test"
    settings.CURVE_FOUNDATION_PROBE_ENABLED = True
    settings.CURVE_SSE_REPLAY_LIMIT = 100
    settings.CURVE_SSE_POLL_INTERVAL_SECONDS = 0
    settings.CURVE_SSE_CONNECTION_SECONDS = 0


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


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _create_probe(client, *, slug="alpha", key="foundation-probe-key-0001"):
    return client.post(
        f"/api/v1/workspaces/{slug}/curve/foundation-probes/",
        {"requested_delay_ms": 10},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )


def _service_authorization(workspace_id):
    now = timezone.now()
    service = {"actor_type": "SERVICE", "actor_id": "curve-worker-test"}
    return service, {
        "authorization_id": "curve-worker-test-authorization",
        "authorization_version": 1,
        "workspace_id": str(workspace_id),
        "service": service,
        "active": True,
        "allowed_actions": ["CURVE.OPERATION.TRANSITION"],
        "issued_at": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
    }


def _transition(operation, status, *, workflow_id=None, error=None):
    service, authorization = _service_authorization(operation.workspace_id)
    return transition_operation_with_service_authorization(
        workspace_id=operation.workspace_id,
        operation_id=operation.id,
        expected_version=operation.aggregate_version,
        status=status,
        service_actor=service,
        service_authorization=authorization,
        correlation_id=operation.correlation_id,
        causation_id=f"test:{status.lower()}",
        error=error,
        destination=TEMPORAL_DESTINATION,
        workflow_id=workflow_id,
    )


def _running(operation):
    workflow_id = operation_workflow_id(
        workspace_id=str(operation.workspace_id),
        operation_id=str(operation.id),
    )
    operation = _transition(operation, OperationStatus.QUEUED, workflow_id=workflow_id)
    return _transition(operation, OperationStatus.RUNNING)


def _stream_text(response):
    return b"".join(response.streaming_content).decode("utf-8")


def _stream_event_ids(body):
    return [line.removeprefix("id: ") for line in body.splitlines() if line.startswith("id: ")]


def test_foundation_probe_create_and_replay_return_only_safe_summary():
    user = _user("probe-owner@example.com")
    workspace = _workspace("Alpha", "alpha", user)
    client = _client(user)

    first = _create_probe(client)
    replay = _create_probe(client)

    assert first.status_code == replay.status_code == 202
    assert first.json() == replay.json()
    assert set(first.json()) == {
        "schema_version",
        "id",
        "workspace_id",
        "operation_type",
        "status",
        "version",
    }
    assert first.json()["workspace_id"] == str(workspace.id)
    assert first.json()["operation_type"] == "FOUNDATION_PROBE"
    assert first["Location"].endswith(first.json()["id"])
    assert first["ETag"] == f'"curve-operation:{first.json()["id"]}:v1"'
    assert Operation.objects.filter(workspace_id=workspace.id).count() == 1
    assert IdempotencyRecord.objects.filter(workspace_id=workspace.id).count() == 1


@override_settings(CURVE_FOUNDATION_PROBE_ENABLED=False)
def test_foundation_probe_flag_fails_closed_with_problem_details():
    user = _user("disabled-probe@example.com")
    _workspace("Alpha", "alpha", user)

    response = _create_probe(_client(user))

    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")
    assert response.json()["type"].endswith("curve-resource-not-found")
    assert "correlation_id" in response.json()


def test_operation_list_and_detail_are_owner_scoped_safe_projections():
    owner = _user("operation-owner@example.com")
    other = _user("other-member@example.com")
    workspace = _workspace("Alpha", "alpha", owner)
    WorkspaceMember.objects.create(workspace=workspace, member=other, role=15, is_active=True)
    owner_client = _client(owner)
    owner_operation_id = _create_probe(owner_client).json()["id"]
    start_foundation_probe(
        request=SimpleNamespace(user=other),
        workspace_slug="alpha",
        raw_idempotency_key="other-member-probe-key",
        canonical_request=b'{"command_type":"CREATE_FOUNDATION_PROBE"}',
        destination=TEMPORAL_DESTINATION,
    )

    listing = owner_client.get("/api/v1/workspaces/alpha/curve/operations/?page_size=1")
    detail = owner_client.get(f"/api/v1/workspaces/alpha/curve/operations/{owner_operation_id}/")

    assert listing.status_code == detail.status_code == 200
    assert [operation["id"] for operation in listing.json()["results"]] == [owner_operation_id]
    assert set(detail.json()) == {
        "schema_version",
        "id",
        "workspace_id",
        "operation_type",
        "status",
        "version",
    }
    assert detail["ETag"] == f'"curve-operation:{owner_operation_id}:v1"'
    serialized = json.dumps(detail.json())
    for protected_name in ("idempotency", "created_by", "correlation", "workflow_id", "policy_version_ref"):
        assert protected_name not in serialized


def test_operation_list_filters_foundation_probes_before_pagination():
    owner = _user("filtered-operation-owner@example.com")
    workspace = _workspace("Alpha", "alpha", owner)
    client = _client(owner)
    foundation_operation_id = _create_probe(client).json()["id"]
    actor = {"actor_type": "HUMAN", "actor_id": str(owner.id)}
    Operation.objects.create(
        workspace_id=workspace.id,
        operation_type=OperationType.WORKFLOW_COMMAND,
        command_type="RUN_WORKFLOW_COMMAND",
        target={"resource_type": "WORKSPACE", "resource_id": str(workspace.id)},
        idempotency_key_digest=f"sha256:{'a' * 64}",
        created_by=actor,
        updated_by=actor,
        correlation_id="newer-non-foundation-operation",
    )

    response = client.get("/api/v1/workspaces/alpha/curve/operations/?page_size=1&operation_type=FOUNDATION_PROBE")

    assert response.status_code == 200
    assert [operation["id"] for operation in response.json()["results"]] == [foundation_operation_id]
    assert response.json()["results"][0]["operation_type"] == OperationType.FOUNDATION_PROBE


def test_operation_list_rejects_unknown_operation_type_filter():
    owner = _user("invalid-operation-filter@example.com")
    _workspace("Alpha", "alpha", owner)

    response = _client(owner).get("/api/v1/workspaces/alpha/curve/operations/?operation_type=UNSUPPORTED_OPERATION")

    assert response.status_code == 422
    assert response.json()["errors"] == [
        {
            "code": "CURVE_OPERATION_TYPE_INVALID",
            "field": "operation_type",
            "message": "operation_type is not supported",
        }
    ]


def test_cross_workspace_operation_read_is_denied_without_disclosure():
    alpha_user = _user("alpha-reader@example.com")
    beta_user = _user("beta-owner@example.com")
    _workspace("Alpha", "alpha", alpha_user)
    _workspace("Beta", "beta", beta_user)
    beta_operation_id = _create_probe(_client(beta_user), slug="beta", key="beta-probe-key-00001").json()["id"]

    response = _client(alpha_user).get(f"/api/v1/workspaces/beta/curve/operations/{beta_operation_id}/")

    assert response.status_code == 403
    assert response["Content-Type"].startswith("application/problem+json")
    assert beta_operation_id not in json.dumps(response.json())


def test_cancellation_requires_version_and_replays_without_duplicate_effect():
    user = _user("cancel-owner@example.com")
    _workspace("Alpha", "alpha", user)
    client = _client(user)
    operation_id = _create_probe(client).json()["id"]
    operation = _running(Operation.objects.get(id=operation_id))
    cancel_url = f"/api/v1/workspaces/alpha/curve/operations/{operation_id}/cancel/"
    key = "cancel-operation-key-0001"

    missing = client.post(cancel_url, {}, format="json", HTTP_IDEMPOTENCY_KEY=key)
    stale = client.post(
        cancel_url,
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
        HTTP_IF_MATCH=f'"curve-operation:{operation_id}:v1"',
    )
    accepted = client.post(
        cancel_url,
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
        HTTP_IF_MATCH=f'"curve-operation:{operation_id}:v{operation.aggregate_version}"',
    )
    replay = client.post(
        cancel_url,
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
        HTTP_IF_MATCH=f'"curve-operation:{operation_id}:v{operation.aggregate_version}"',
    )

    assert missing.status_code == 428
    assert stale.status_code == 412
    assert accepted.status_code == replay.status_code == 202
    assert accepted.json() == replay.json()
    assert accepted.json()["status"] == "CANCEL_REQUESTED"
    assert accepted.json()["version"] == operation.aggregate_version + 1
    assert DomainEvent.objects.filter(aggregate_id=operation.id, payload__status="CANCEL_REQUESTED").count() == 1
    assert IdempotencyRecord.objects.filter(command_scope=f"CANCEL_OPERATION:{operation.id}").count() == 1


def test_sse_is_ordered_resumable_and_redacts_internal_event_fields():
    user = _user("stream-owner@example.com")
    _workspace("Alpha", "alpha", user)
    operation_id = _create_probe(_client(user)).json()["id"]
    operation = _running(Operation.objects.get(id=operation_id))
    _transition(
        operation,
        OperationStatus.FAILED,
        error={"code": "SYNTHETIC_INTERNAL_FAILURE", "retryable": False},
    )
    ordered_ids = [
        str(event_id)
        for event_id in DomainEvent.objects.filter(aggregate_id=operation_id)
        .order_by("recorded_at", "id")
        .values_list("id", flat=True)
    ]
    client = _client(user)

    initial = client.get(
        "/api/v1/workspaces/alpha/curve/events/",
        HTTP_ACCEPT="text/event-stream",
    )
    initial_body = _stream_text(initial)
    resumed = client.get(
        "/api/v1/workspaces/alpha/curve/events/",
        HTTP_ACCEPT="text/event-stream",
        HTTP_LAST_EVENT_ID=ordered_ids[1],
    )
    resumed_body = _stream_text(resumed)

    assert initial.status_code == resumed.status_code == 200
    assert initial["Content-Encoding"] == resumed["Content-Encoding"] == "identity"
    assert _stream_event_ids(initial_body) == ordered_ids
    assert _stream_event_ids(resumed_body) == ordered_ids[2:]
    assert "SYNTHETIC_INTERNAL_FAILURE" not in initial_body
    assert "correlation_id" not in initial_body
    assert "idempotency_key_digest" not in initial_body
    assert initial_body.count(f"id: {ordered_ids[-1]}") == 1


@override_settings(CURVE_SSE_REPLAY_LIMIT=1)
def test_sse_stale_cursor_returns_recoverable_410():
    user = _user("stale-stream-owner@example.com")
    _workspace("Alpha", "alpha", user)
    operation_id = _create_probe(_client(user)).json()["id"]
    _running(Operation.objects.get(id=operation_id))
    first_event_id = str(
        DomainEvent.objects.filter(aggregate_id=operation_id)
        .order_by("recorded_at", "id")
        .values_list("id", flat=True)
        .first()
    )

    response = _client(user).get(
        "/api/v1/workspaces/alpha/curve/events/",
        HTTP_ACCEPT="text/event-stream",
        HTTP_LAST_EVENT_ID=first_event_id,
    )

    assert response.status_code == 410
    assert response.json()["resync"] == {"action": "FETCH_CURRENT_OPERATIONS", "cursor": None}
    assert response["Content-Type"].startswith("application/problem+json")


def test_curve_browser_contract_headers_are_cross_origin_compatible():
    allowed = {header.lower() for header in settings.CORS_ALLOW_HEADERS}
    exposed = {header.lower() for header in settings.CORS_EXPOSE_HEADERS}

    assert {"idempotency-key", "if-match", "last-event-id", "x-csrftoken"}.issubset(allowed)
    assert {"etag", "location"}.issubset(exposed)


def test_session_foundation_probe_requires_and_accepts_csrf():
    user = _user("session-probe@example.com")
    _workspace("Alpha", "alpha", user)
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)
    url = "/api/v1/workspaces/alpha/curve/foundation-probes/"

    rejected = client.post(
        url,
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="session-probe-key-rejected",
    )

    csrf_token = _get_new_csrf_string()
    client.cookies[settings.CSRF_COOKIE_NAME] = csrf_token
    accepted = client.post(
        url,
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="session-probe-key-accepted",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert rejected.status_code == 403
    assert accepted.status_code == 202
