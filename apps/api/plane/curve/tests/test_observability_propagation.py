# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import base64
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from plane.curve.models import DomainEvent, Operation, OutboxEvent, OutboxState
from plane.curve.observability.gauges import _outbox_snapshot
from plane.curve.observability.propagation import (
    OPERATION_EVENT_V1_SCHEMA,
    OPERATION_EVENT_V2_SCHEMA,
    TEMPORAL_TRACE_HEADER,
    event_contract,
)
from plane.curve.observability.runtime import (
    get_telemetry_runtime,
    reset_telemetry_runtime_for_tests,
)
from plane.curve.observability.temporal import (
    CurveWorkflowTraceInterceptor,
    _CurveActivityInboundInterceptor,
    _CurveClientOutboundInterceptor,
    _decode_traceparent,
    _encode_traceparent,
)
from plane.curve.policy_services import CurvePolicyDenied, start_foundation_probe
from plane.curve.temporal.relay import relay_workspace_once
from plane.curve.temporal.constants import MARK_RUNNING_ACTIVITY
import plane.curve.services as curve_services
from plane.db.models import User, Workspace, WorkspaceMember


pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


TRACEPARENT = "00-11111111111111111111111111111111-2222222222222222-01"
SCOPE_KEY = b"curve-observability-test-key-32b"


@pytest.fixture(autouse=True)
def _curve_observability_settings(settings, monkeypatch):
    settings.ROOT_URLCONF = "plane.curve.tests.urls"
    settings.DEBUG = True
    settings.CURVE_ENABLED = True
    settings.CURVE_ENABLED_WORKSPACE_SLUGS = frozenset({"observed"})
    settings.CURVE_ENVIRONMENT = "LOCAL"
    settings.CURVE_POLICY_RECORDER_ACTOR_ID = "curve-observability-test"
    settings.CURVE_FOUNDATION_PROBE_ENABLED = True
    settings.CURVE_SSE_REPLAY_LIMIT = 100
    settings.CURVE_SSE_POLL_INTERVAL_SECONDS = 0
    settings.CURVE_SSE_CONNECTION_SECONDS = 0
    monkeypatch.setenv("CURVE_ENVIRONMENT", "LOCAL")
    monkeypatch.setenv("CURVE_TELEMETRY_MODE", "IN_MEMORY_TEST")
    monkeypatch.setenv(
        "CURVE_TELEMETRY_SCOPE_HMAC_KEY",
        base64.urlsafe_b64encode(SCOPE_KEY).rstrip(b"=").decode("ascii"),
    )
    monkeypatch.setenv("CURVE_TELEMETRY_SCOPE_KEY_ID", "test-key-v1")
    reset_telemetry_runtime_for_tests()
    yield
    reset_telemetry_runtime_for_tests()


def _authorized_client():
    user = User.objects.create(
        email=f"curve-observability-{uuid.uuid4()}@example.com",
        username=f"curve-observability-{uuid.uuid4()}@example.com",
    )
    workspace = Workspace.objects.create(name="Observed", slug="observed", owner=user)
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=20, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return workspace, client


def _stream_text(response):
    return b"".join(response.streaming_content).decode("utf-8")


def test_http_event_and_sse_share_trace_without_exposing_traceparent():
    workspace, client = _authorized_client()
    response = client.post(
        "/api/v1/workspaces/observed/curve/foundation-probes/",
        {"requested_delay_ms": 10},
        format="json",
        HTTP_IDEMPOTENCY_KEY="observability-probe-key-0001",
        HTTP_TRACEPARENT=TRACEPARENT,
        HTTP_TRACESTATE="vendor=drop-this",
        HTTP_BAGGAGE="protected=drop-this",
    )

    assert response.status_code == 202
    event = DomainEvent.objects.get(
        workspace_id=workspace.id,
        aggregate_id=uuid.UUID(response.json()["id"]),
        sequence=1,
    )
    assert event.payload_schema == OPERATION_EVENT_V2_SCHEMA
    event_traceparent = event.payload["traceparent"]
    assert event_traceparent.split("-")[1] == TRACEPARENT.split("-")[1]
    assert "tracestate" not in event.payload
    assert "baggage" not in event.payload

    stream = client.get("/api/v1/workspaces/observed/curve/events/", HTTP_ACCEPT="text/event-stream")
    body = _stream_text(stream)

    assert event_traceparent not in body
    assert "traceparent" not in body
    assert "tracestate" not in body
    assert "baggage" not in body
    runtime = get_telemetry_runtime(component="API")
    spans = runtime.span_exporter.get_finished_spans()
    assert [span.name for span in spans] == ["curve.http.command", "curve.sse.publish"]
    assert len({span.context.trace_id for span in spans}) == 1
    assert f"{spans[0].context.trace_id:032x}" == TRACEPARENT.split("-")[1]
    assert str(workspace.id) not in str([span.attributes for span in spans])

    counts, oldest_age = _outbox_snapshot()
    assert counts["PENDING"] == 1
    assert oldest_age >= 0


def test_trace_carriers_dual_read_and_temporal_header_are_strict():
    payload = _encode_traceparent(TRACEPARENT)

    assert _decode_traceparent({TEMPORAL_TRACE_HEADER: payload}) == TRACEPARENT
    assert _decode_traceparent({TEMPORAL_TRACE_HEADER: _encode_traceparent(None)}) is None
    assert event_contract(OPERATION_EVENT_V1_SCHEMA, {"status": "PENDING"}) == ("v1", None)
    assert event_contract(OPERATION_EVENT_V2_SCHEMA, {"traceparent": TRACEPARENT}) == (
        "v2",
        TRACEPARENT,
    )
    with pytest.raises(ValueError, match="traceparent"):
        event_contract(OPERATION_EVENT_V2_SCHEMA, {"traceparent": "invalid-protected-value"})


def test_policy_denial_emits_bounded_workspace_scoped_log(caplog):
    workspace, _ = _authorized_client()

    with override_settings(CURVE_ENVIRONMENT="STAGING"):
        with pytest.raises(CurvePolicyDenied):
            start_foundation_probe(
                request=SimpleNamespace(user=workspace.owner, headers={}),
                workspace_slug=workspace.slug,
                raw_idempotency_key="observability-denial-key-0001",
                canonical_request=b'{"request_body":"CURVE_SENTINEL_DENIED_BODY"}',
            )

    messages = [record.message for record in caplog.records if "CURVE_COMMAND_DENIED" in record.message]
    assert len(messages) == 1
    assert str(workspace.id) not in messages[0]
    assert "CURVE_SENTINEL_DENIED_BODY" not in messages[0]
    assert "CURVE_POLICY_DENIED" in messages[0]


def test_audit_failure_rolls_back_before_command_success_telemetry(monkeypatch, caplog):
    workspace, client = _authorized_client()

    def fail_audit(**kwargs):
        raise RuntimeError("CURVE_SENTINEL_AUDIT_BODY")

    monkeypatch.setattr(curve_services, "_append_audit_event", fail_audit)
    response = client.post(
        "/api/v1/workspaces/observed/curve/foundation-probes/",
        {"requested_delay_ms": 10},
        format="json",
        HTTP_IDEMPOTENCY_KEY="observability-audit-failure-key-0001",
    )

    assert response.status_code == 500
    assert not Operation.objects.filter(workspace_id=workspace.id).exists()
    assert not DomainEvent.objects.filter(workspace_id=workspace.id).exists()
    assert not OutboxEvent.objects.filter(workspace_id=workspace.id).exists()
    runtime = get_telemetry_runtime(component="API")
    spans = runtime.span_exporter.get_finished_spans()
    assert [span.attributes["curve.result"] for span in spans] == ["FAILED"]
    data = runtime.metric_reader.get_metrics_data()
    metric_names = (
        {
            metric.name
            for resource in data.resource_metrics
            for scope in resource.scope_metrics
            for metric in scope.metrics
        }
        if data is not None
        else set()
    )
    assert "curve.operation.started" not in metric_names
    rendered_logs = "\n".join(record.message for record in caplog.records)
    assert "CURVE_COMMAND_ACCEPTED" not in rendered_logs
    assert "CURVE_SENTINEL_AUDIT_BODY" not in rendered_logs


def test_failed_temporal_delivery_is_retried_without_exception_leakage(caplog):
    workspace, client = _authorized_client()
    response = client.post(
        "/api/v1/workspaces/observed/curve/foundation-probes/",
        {"requested_delay_ms": 10},
        format="json",
        HTTP_IDEMPOTENCY_KEY="observability-retry-key-0001",
    )
    assert response.status_code == 202
    event = DomainEvent.objects.get(
        workspace_id=workspace.id,
        aggregate_id=uuid.UUID(response.json()["id"]),
        sequence=1,
    )
    runtime = get_telemetry_runtime(component="TEMPORAL_WORKER")
    temporal_client = SimpleNamespace(
        start_workflow=AsyncMock(side_effect=RuntimeError("CURVE_SENTINEL_TEMPORAL_RESPONSE"))
    )

    delivered = asyncio.run(
        relay_workspace_once(
            client=temporal_client,
            workspace_id=workspace.id,
            worker_id="curve-observability-retry-test",
            telemetry_runtime=runtime,
        )
    )

    assert delivered == 0
    outbox = OutboxEvent.objects.get(workspace_id=workspace.id, destination="CURVE_TEMPORAL_OPERATION_V1")
    assert outbox.state == OutboxState.RETRY_SCHEDULED
    data = runtime.metric_reader.get_metrics_data()
    results = [
        point.attributes["curve.result"]
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == "curve.outbox.delivery"
        for point in metric.data.data_points
    ]
    assert set(results) == {"FAILED", "RETRIED"}
    dispatch_spans = [
        span for span in runtime.span_exporter.get_finished_spans() if span.name == "curve.outbox.dispatch"
    ]
    assert len(dispatch_spans) == 1
    assert f"{dispatch_spans[0].context.trace_id:032x}" == event.payload["traceparent"].split("-")[1]
    rendered_logs = "\n".join(record.message for record in caplog.records)
    assert "CURVE_SENTINEL_TEMPORAL_RESPONSE" not in rendered_logs
    assert "CURVE_OUTBOX_RETRY_SCHEDULED" in rendered_logs


def test_activity_interceptor_extracts_only_traceparent_and_emits_child_span(monkeypatch):
    from plane.curve.observability import temporal as temporal_observability

    class ActivityNext:
        async def execute_activity(self, input):
            return SimpleNamespace(operation_status="RUNNING")

    workspace_id = uuid.uuid4()
    operation_id = uuid.uuid4()
    runtime = get_telemetry_runtime(component="TEMPORAL_WORKER")
    monkeypatch.setattr(
        temporal_observability.activity,
        "info",
        lambda: SimpleNamespace(activity_type=MARK_RUNNING_ACTIVITY, attempt=1),
    )
    interceptor = _CurveActivityInboundInterceptor(ActivityNext(), runtime)

    result = asyncio.run(
        interceptor.execute_activity(
            SimpleNamespace(
                args=[SimpleNamespace(workspace_id=str(workspace_id), operation_id=str(operation_id))],
                headers={
                    TEMPORAL_TRACE_HEADER: _encode_traceparent(TRACEPARENT),
                    "untrusted": _encode_traceparent("00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"),
                },
            )
        )
    )

    assert result.operation_status == "RUNNING"
    spans = runtime.span_exporter.get_finished_spans()
    assert [span.name for span in spans] == ["curve.activity.run"]
    assert f"{spans[0].context.trace_id:032x}" == TRACEPARENT.split("-")[1]
    assert str(workspace_id) not in str(spans[0].attributes)


def test_temporal_client_and_workflow_copy_only_the_curve_trace_header():
    class ClientNext:
        async def start_workflow(self, input):
            return input

    class WorkflowNext:
        def __init__(self):
            self.outbound = None

        def init(self, outbound):
            self.outbound = outbound

        async def execute_workflow(self, input):
            return "executed"

    class WorkflowOutboundNext:
        def start_activity(self, input):
            return input

    runtime = get_telemetry_runtime(component="API")
    with runtime.registry.span(
        "curve.http.command",
        attributes={
            "curve.command.type": "CREATE_FOUNDATION_PROBE",
            "curve.component": "API",
            "curve.error.code": "NONE",
            "curve.operation.id": str(uuid.uuid4()),
            "curve.operation.type": "FOUNDATION_PROBE",
            "curve.result": "SUCCEEDED",
            "curve.workspace.scope": runtime.workspace_scope(uuid.uuid4()),
        },
    ):
        client_input = SimpleNamespace(headers={"untrusted": _encode_traceparent(TRACEPARENT)})
        client_result = asyncio.run(_CurveClientOutboundInterceptor(ClientNext()).start_workflow(client_input))

    propagated = _decode_traceparent(client_result.headers)
    assert propagated is not None
    assert set(client_result.headers) == {"untrusted", TEMPORAL_TRACE_HEADER}

    workflow_next = WorkflowNext()
    workflow = CurveWorkflowTraceInterceptor(workflow_next)
    workflow.init(WorkflowOutboundNext())
    assert asyncio.run(workflow.execute_workflow(SimpleNamespace(headers=client_result.headers))) == "executed"
    activity_input = SimpleNamespace(headers={"other": _encode_traceparent(TRACEPARENT)})
    copied = workflow_next.outbound.start_activity(activity_input)

    assert _decode_traceparent(copied.headers) == propagated
    assert set(copied.headers) == {"other", TEMPORAL_TRACE_HEADER}
