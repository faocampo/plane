# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import atexit
import os
from pathlib import Path
import threading
from dataclasses import dataclass

from plane.curve.observability.configuration import (
    TelemetryConfiguration,
    TelemetryMode,
    load_telemetry_configuration,
)
from plane.curve.observability.export import CurveExportFailureReporter, CurveSpanExporter, wrap_metric_exporter
from plane.curve.observability.manifest import telemetry_manifest
from plane.curve.observability.registry import CurveTelemetryRegistry
from plane.curve.observability.scope import workspace_scope
from plane.curve.observability.structured_logging import CurveStructuredLogger


@dataclass(slots=True)
class CurveTelemetryRuntime:
    configuration: TelemetryConfiguration
    registry: CurveTelemetryRegistry
    structured_logger: CurveStructuredLogger
    tracer_provider: object | None = None
    meter_provider: object | None = None
    span_exporter: object | None = None
    metric_reader: object | None = None
    failure_reporter: object | None = None
    _shutdown: bool = False

    @property
    def enabled(self) -> bool:
        return self.configuration.enabled and not self._shutdown

    def workspace_scope(self, workspace_id) -> str | None:
        key = self.configuration.workspace_scope_key
        if key is None:
            return None
        return workspace_scope(workspace_id=workspace_id, key=key)

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        timeout = telemetry_manifest()["export"]["shutdown_timeout_millis"]
        if self.tracer_provider is not None:
            try:
                self.tracer_provider.force_flush(timeout_millis=timeout)
            except Exception:
                pass
            try:
                self.tracer_provider.shutdown()
            except Exception:
                pass
        if self.meter_provider is not None:
            try:
                self.meter_provider.force_flush(timeout_millis=timeout)
            except Exception:
                pass
            try:
                self.meter_provider.shutdown(timeout_millis=timeout)
            except Exception:
                pass


def _disabled_runtime(configuration: TelemetryConfiguration) -> CurveTelemetryRuntime:
    return CurveTelemetryRuntime(
        configuration=configuration,
        registry=CurveTelemetryRegistry(),
        structured_logger=CurveStructuredLogger(
            component=configuration.component.value,
            scope_key=None,
            scope_key_id=None,
        ),
    )


def _resource(configuration):
    from opentelemetry.sdk.resources import Resource

    attributes = telemetry_manifest()["instrumentation"]["resource_attributes_by_component"][
        configuration.component.value
    ]
    return Resource(attributes=attributes)


def _trace_provider(configuration, *, exporter):
    from opentelemetry.sdk.trace import SpanLimits, TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased

    manifest = telemetry_manifest()
    limits = SpanLimits(**manifest["instrumentation"]["span_limits"])
    provider = TracerProvider(
        sampler=ParentBased(ALWAYS_ON),
        resource=_resource(configuration),
        shutdown_on_exit=False,
        span_limits=limits,
    )
    if configuration.mode is TelemetryMode.IN_MEMORY_TEST:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        batch = manifest["export"]["span_batch"]
        provider.add_span_processor(
            BatchSpanProcessor(
                exporter,
                max_queue_size=batch["max_queue_size"],
                schedule_delay_millis=batch["schedule_delay_millis"],
                max_export_batch_size=batch["max_export_batch_size"],
                export_timeout_millis=batch["export_timeout_millis"],
            )
        )
    return provider


def _metric_views(configuration):
    from opentelemetry.sdk.metrics.view import (
        DropAggregation,
        ExplicitBucketHistogramAggregation,
        View,
    )

    views = []
    manifest = telemetry_manifest()
    local_only = set(manifest["export"]["local_only_metrics"])
    for metric in manifest["metrics"]:
        if configuration.mode is TelemetryMode.OTLP and metric["name"] in local_only:
            continue
        aggregation = None
        if metric["instrument"] == "HISTOGRAM":
            aggregation = ExplicitBucketHistogramAggregation(boundaries=metric["boundaries"])
        views.append(
            View(
                instrument_name=metric["name"],
                attribute_keys=set(metric["allowed_attributes"]),
                aggregation=aggregation,
            )
        )
    views.append(View(instrument_name="*", aggregation=DropAggregation()))
    return views


def _meter_provider(configuration, *, reader):
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics._internal.exemplar import AlwaysOffExemplarFilter

    return MeterProvider(
        metric_readers=[reader],
        resource=_resource(configuration),
        views=_metric_views(configuration),
        exemplar_filter=AlwaysOffExemplarFilter(),
        shutdown_on_exit=False,
    )


def _otlp_exporters(configuration):
    from opentelemetry.sdk.metrics.export import AggregationTemporality
    from opentelemetry.sdk.metrics._internal.instrument import Counter, Histogram, ObservableGauge, UpDownCounter

    temporality = {
        Counter: AggregationTemporality.CUMULATIVE,
        UpDownCounter: AggregationTemporality.CUMULATIVE,
        Histogram: AggregationTemporality.CUMULATIVE,
        ObservableGauge: AggregationTemporality.CUMULATIVE,
    }
    headers = dict(configuration.headers)
    timeout = telemetry_manifest()["export"]["exporter_timeout_millis"] / 1000
    common = {"endpoint": configuration.endpoint, "headers": headers, "timeout": timeout}
    if configuration.protocol == "grpc":
        import grpc

        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        credentials = None
        if not configuration.insecure:
            root_certificates = Path(configuration.certificate).read_bytes() if configuration.certificate else None
            private_key = Path(configuration.client_key).read_bytes() if configuration.client_key else None
            certificate_chain = (
                Path(configuration.client_certificate).read_bytes() if configuration.client_certificate else None
            )
            credentials = grpc.ssl_channel_credentials(
                root_certificates=root_certificates,
                private_key=private_key,
                certificate_chain=certificate_chain,
            )
        arguments = {
            **common,
            "insecure": configuration.insecure,
            "credentials": credentials,
            "compression": None,
        }
        return OTLPSpanExporter(**arguments), OTLPMetricExporter(
            **arguments,
            preferred_temporality=temporality,
        )

    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    base = configuration.endpoint.rstrip("/")
    arguments = {
        "headers": headers,
        "timeout": timeout,
        "compression": None,
        "certificate_file": configuration.certificate,
        "client_certificate_file": configuration.client_certificate,
        "client_key_file": configuration.client_key,
    }
    return (
        OTLPSpanExporter(endpoint=f"{base}/v1/traces", **arguments),
        OTLPMetricExporter(
            endpoint=f"{base}/v1/metrics",
            preferred_temporality=temporality,
            **arguments,
        ),
    )


def build_telemetry_runtime(configuration: TelemetryConfiguration) -> CurveTelemetryRuntime:
    if not configuration.enabled:
        return _disabled_runtime(configuration)
    structured_logger = CurveStructuredLogger(
        component=configuration.component.value,
        scope_key=configuration.workspace_scope_key,
        scope_key_id=configuration.workspace_scope_key_id,
    )
    failure_reporter = CurveExportFailureReporter(
        component=configuration.component.value,
        mode=configuration.mode,
        structured_logger=structured_logger,
    )
    if configuration.mode is TelemetryMode.IN_MEMORY_TEST:
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        span_exporter = CurveSpanExporter(InMemorySpanExporter(), failure_reporter)
        metric_reader = InMemoryMetricReader()
    else:
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

        raw_span_exporter, raw_metric_exporter = _otlp_exporters(configuration)
        span_exporter = CurveSpanExporter(raw_span_exporter, failure_reporter)
        metric_exporter = wrap_metric_exporter(raw_metric_exporter, failure_reporter)
        reader_contract = telemetry_manifest()["export"]["metric_reader"]
        metric_reader = PeriodicExportingMetricReader(
            metric_exporter,
            export_interval_millis=reader_contract["export_interval_millis"],
            export_timeout_millis=reader_contract["export_timeout_millis"],
        )
    tracer_provider = _trace_provider(configuration, exporter=span_exporter)
    meter_provider = _meter_provider(configuration, reader=metric_reader)
    registry = CurveTelemetryRegistry(
        tracer=tracer_provider.get_tracer("plane.curve", "1.0"),
        meter=meter_provider.get_meter("plane.curve", "1.0"),
    )
    failure_reporter.bind_registry(registry)
    return CurveTelemetryRuntime(
        configuration=configuration,
        registry=registry,
        structured_logger=structured_logger,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        span_exporter=span_exporter,
        metric_reader=metric_reader,
        failure_reporter=failure_reporter,
    )


_runtime_lock = threading.Lock()
_runtimes: dict[tuple[int, str], CurveTelemetryRuntime] = {}
_shutdown_registered_pids: set[int] = set()


def _shutdown_process_runtimes(pid: int) -> None:
    with _runtime_lock:
        runtimes = [runtime for (runtime_pid, _), runtime in _runtimes.items() if runtime_pid == pid]
    for runtime in runtimes:
        runtime.shutdown()


def get_telemetry_runtime(*, component: str, environ=None) -> CurveTelemetryRuntime:
    pid = os.getpid()
    key = (pid, component)
    runtime = _runtimes.get(key)
    if runtime is not None:
        return runtime
    with _runtime_lock:
        runtime = _runtimes.get(key)
        if runtime is None:
            configuration = load_telemetry_configuration(component=component, environ=environ)
            runtime = build_telemetry_runtime(configuration)
            if configuration.error_code is not None:
                try:
                    runtime.structured_logger.emit(
                        event_code="CURVE_TELEMETRY_CONFIGURATION_INVALID",
                        level="ERROR",
                    )
                except Exception:
                    pass
            if runtime.enabled and pid not in _shutdown_registered_pids:
                atexit.register(_shutdown_process_runtimes, pid)
                _shutdown_registered_pids.add(pid)
            _runtimes[key] = runtime
        return runtime


def reset_telemetry_runtime_for_tests() -> None:
    with _runtime_lock:
        for runtime in _runtimes.values():
            runtime.shutdown()
        _runtimes.clear()
