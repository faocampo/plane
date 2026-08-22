# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import base64
import concurrent.futures
import uuid

import pytest
from opentelemetry import metrics, trace
from opentelemetry.sdk.trace.export import SpanExportResult

from plane.curve.observability.export import CurveSpanExporter
from plane.curve.observability.configuration import load_telemetry_configuration
from plane.curve.observability.runtime import get_telemetry_runtime, reset_telemetry_runtime_for_tests
from plane.curve.observability.gauges import register_worker_gauges
from plane.curve.observability.scope import workspace_scope


pytestmark = pytest.mark.unit


SCOPE_KEY = b"curve-observability-test-key-32b"


@pytest.fixture(autouse=True)
def _reset_runtime():
    reset_telemetry_runtime_for_tests()
    yield
    reset_telemetry_runtime_for_tests()


def _environment(**overrides):
    return {
        "CURVE_ENVIRONMENT": "LOCAL",
        "CURVE_TELEMETRY_MODE": "IN_MEMORY_TEST",
        "CURVE_TELEMETRY_SCOPE_HMAC_KEY": base64.urlsafe_b64encode(SCOPE_KEY).rstrip(b"=").decode(),
        "CURVE_TELEMETRY_SCOPE_KEY_ID": "test-key-v1",
        **overrides,
    }


def test_in_memory_runtime_uses_private_providers_and_closed_signals():
    global_tracer = trace.get_tracer_provider()
    global_meter = metrics.get_meter_provider()
    runtime = get_telemetry_runtime(component="API", environ=_environment())
    workspace_id = uuid.uuid4()
    operation_id = str(uuid.uuid4())
    scope = workspace_scope(workspace_id=workspace_id, key=SCOPE_KEY)

    with runtime.registry.span(
        "curve.http.command",
        attributes={
            "curve.command.type": "CREATE_FOUNDATION_PROBE",
            "curve.component": "API",
            "curve.error.code": "NONE",
            "curve.operation.id": operation_id,
            "curve.operation.type": "FOUNDATION_PROBE",
            "curve.result": "SUCCEEDED",
            "curve.workspace.scope": scope,
            "request_body": "CURVE_SENTINEL_BODY",
        },
    ):
        assert runtime.registry.record(
            "curve.operation.started",
            1,
            attributes={"curve.component": "API", "curve.operation.type": "FOUNDATION_PROBE"},
        )

    spans = runtime.span_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "curve.http.command"
    assert spans[0].attributes["curve.workspace.scope"] == scope
    assert "request_body" not in spans[0].attributes
    assert trace.get_tracer_provider() is global_tracer
    assert metrics.get_meter_provider() is global_meter
    assert runtime.tracer_provider is not global_tracer
    assert runtime.meter_provider is not global_meter


def test_runtime_singleton_is_process_local_and_thread_safe():
    environment = _environment()

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        runtimes = list(executor.map(lambda _: get_telemetry_runtime(component="API", environ=environment), range(32)))

    assert len({id(runtime) for runtime in runtimes}) == 1


def test_only_enabled_process_registers_one_owned_shutdown_hook(monkeypatch):
    from plane.curve.observability import runtime as runtime_module

    registrations = []
    runtime_module._shutdown_registered_pids.clear()
    monkeypatch.setattr(runtime_module.atexit, "register", lambda *args: registrations.append(args))

    get_telemetry_runtime(
        component="API",
        environ={"CURVE_ENVIRONMENT": "LOCAL", "CURVE_TELEMETRY_MODE": "DISABLED"},
    )
    assert registrations == []

    reset_telemetry_runtime_for_tests()
    get_telemetry_runtime(component="API", environ=_environment())
    get_telemetry_runtime(component="TEMPORAL_WORKER", environ=_environment())

    assert len(registrations) == 1


def test_invalid_configuration_creates_no_provider_or_background_reader():
    runtime = get_telemetry_runtime(
        component="API",
        environ={"CURVE_ENVIRONMENT": "LOCAL", "CURVE_TELEMETRY_MODE": "OTLP"},
    )

    assert not runtime.enabled
    assert runtime.configuration.error_code == "CURVE_TELEMETRY_CONFIGURATION_INVALID"
    assert runtime.tracer_provider is None
    assert runtime.meter_provider is None
    assert runtime.span_exporter is None
    assert runtime.metric_reader is None


def test_invalid_configuration_emits_one_common_field_only_diagnostic(caplog):
    get_telemetry_runtime(
        component="API",
        environ={
            "CURVE_ENVIRONMENT": "LOCAL",
            "CURVE_TELEMETRY_MODE": "OTLP",
            "CURVE_OTEL_EXPORTER_OTLP_HEADERS": "authorization=CURVE_SENTINEL_SECRET",
        },
    )

    messages = [
        record.message for record in caplog.records if "CURVE_TELEMETRY_CONFIGURATION_INVALID" in record.message
    ]
    assert len(messages) == 1
    assert "CURVE_SENTINEL_SECRET" not in messages[0]
    assert "curve.workspace.scope" not in messages[0]


def test_shutdown_is_idempotent_and_disables_further_runtime_use():
    runtime = get_telemetry_runtime(component="API", environ=_environment())

    runtime.shutdown()
    runtime.shutdown()

    assert not runtime.enabled


def test_worker_gauges_use_closed_bounded_observations(monkeypatch):
    from plane.curve.observability import gauges

    monkeypatch.setattr(
        gauges,
        "_outbox_snapshot",
        lambda: (
            {
                "CLAIMED": 1,
                "DEAD_LETTER": 0,
                "DELIVERED": 2,
                "PENDING": 3,
                "RETRY_SCHEDULED": 4,
            },
            2.5,
        ),
    )
    runtime = get_telemetry_runtime(component="TEMPORAL_WORKER", environ=_environment())
    register_worker_gauges(runtime)

    data = runtime.metric_reader.get_metrics_data()
    metrics_by_name = {
        metric.name: metric
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }

    assert set(metrics_by_name) >= {
        "curve.outbox.backlog",
        "curve.outbox.oldest_age",
        "curve.worker.heartbeat.age",
    }
    backlog_points = metrics_by_name["curve.outbox.backlog"].data.data_points
    assert {point.attributes["curve.outbox.state"]: point.value for point in backlog_points} == {
        "CLAIMED": 1,
        "DEAD_LETTER": 0,
        "DELIVERED": 2,
        "PENDING": 3,
        "RETRY_SCHEDULED": 4,
    }


def test_export_failure_is_swallowed_logged_and_counted_locally(caplog):
    class FailingExporter:
        def export(self, spans):
            raise TimeoutError("CURVE_SENTINEL_EXPORT_BODY")

        def force_flush(self, timeout_millis=30_000):
            raise TimeoutError("CURVE_SENTINEL_EXPORT_BODY")

        def shutdown(self):
            raise TimeoutError("CURVE_SENTINEL_EXPORT_BODY")

    runtime = get_telemetry_runtime(component="API", environ=_environment())
    exporter = CurveSpanExporter(FailingExporter(), runtime.failure_reporter)

    assert exporter.export([]) is SpanExportResult.FAILURE
    assert exporter.force_flush() is False
    exporter.shutdown()

    data = runtime.metric_reader.get_metrics_data()
    failures = [
        point.value
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == "curve.telemetry.export.failure"
        for point in metric.data.data_points
    ]
    assert sum(failures) == 3
    messages = [record.message for record in caplog.records if "CURVE_TELEMETRY_EXPORT_FAILED" in record.message]
    assert len(messages) == 1
    assert all("CURVE_SENTINEL_EXPORT_BODY" not in message for message in messages)


def test_otlp_exporters_build_from_explicit_http_and_grpc_configuration():
    from plane.curve.observability.runtime import _otlp_exporters

    http = load_telemetry_configuration(
        component="API",
        environ=_environment(
            CURVE_TELEMETRY_MODE="OTLP",
            CURVE_OTEL_EXPORTER_OTLP_ENDPOINT="http://collector:4318/otel",
            CURVE_OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf",
            CURVE_OTEL_EXPORTER_OTLP_INSECURE="true",
        ),
    )
    span_exporter, metric_exporter = _otlp_exporters(http)
    span_exporter.shutdown()
    metric_exporter.shutdown()

    grpc = load_telemetry_configuration(
        component="TEMPORAL_WORKER",
        environ=_environment(
            CURVE_TELEMETRY_MODE="OTLP",
            CURVE_OTEL_EXPORTER_OTLP_ENDPOINT="https://collector:4317",
            CURVE_OTEL_EXPORTER_OTLP_PROTOCOL="grpc",
            CURVE_OTEL_EXPORTER_OTLP_INSECURE="false",
        ),
    )
    assert grpc.enabled
    span_exporter, metric_exporter = _otlp_exporters(grpc)
    span_exporter.shutdown()
    metric_exporter.shutdown()


def test_blocked_gauge_query_is_omitted_without_breaking_collection(monkeypatch):
    from plane.curve.observability import gauges

    monkeypatch.setattr(gauges, "_snapshot_cached_value", None)
    monkeypatch.setattr(gauges, "_snapshot_cached_at", 0.0)
    monkeypatch.setattr(gauges, "_outbox_snapshot", lambda: (_ for _ in ()).throw(TimeoutError()))
    runtime = get_telemetry_runtime(component="TEMPORAL_WORKER", environ=_environment())
    register_worker_gauges(runtime)

    data = runtime.metric_reader.get_metrics_data()
    names = {
        metric.name
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }

    assert "curve.outbox.backlog" not in names
    assert "curve.outbox.oldest_age" not in names
    assert "curve.worker.heartbeat.age" in names
