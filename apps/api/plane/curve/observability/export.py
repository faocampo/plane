# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import threading
import time


_LOG_INTERVAL_SECONDS = 60.0


class CurveExportFailureReporter:
    """Emit one bounded diagnostic per failed export without recursive export."""

    def __init__(self, *, component: str, mode, structured_logger) -> None:
        self._component = component
        self._mode = mode
        self._structured_logger = structured_logger
        self._registry = None
        self._guard = threading.local()
        self._log_lock = threading.Lock()
        self._last_log_at = 0.0

    def bind_registry(self, registry) -> None:
        self._registry = registry

    def report(self) -> None:
        if getattr(self._guard, "active", False):
            return
        self._guard.active = True
        try:
            now = time.monotonic()
            with self._log_lock:
                should_log = now - self._last_log_at >= _LOG_INTERVAL_SECONDS
                if should_log:
                    self._last_log_at = now
            if should_log:
                try:
                    self._structured_logger.emit(
                        event_code="CURVE_TELEMETRY_EXPORT_FAILED",
                        level="ERROR",
                        attributes={"curve.error.code": "CURVE_TELEMETRY_EXPORT_FAILED"},
                    )
                except Exception:
                    pass
            if self._mode.value != "IN_MEMORY_TEST" or self._registry is None:
                return
            try:
                self._registry.record(
                    "curve.telemetry.export.failure",
                    1,
                    attributes={
                        "curve.component": "TELEMETRY",
                        "curve.error.code": "CURVE_TELEMETRY_EXPORT_FAILED",
                    },
                )
            except Exception:
                pass
        finally:
            self._guard.active = False


class CurveSpanExporter:
    def __init__(self, delegate, reporter: CurveExportFailureReporter) -> None:
        self._delegate = delegate
        self._reporter = reporter

    def export(self, spans):
        from opentelemetry.sdk.trace.export import SpanExportResult

        try:
            result = self._delegate.export(spans)
        except Exception:
            self._reporter.report()
            return SpanExportResult.FAILURE
        if result is not SpanExportResult.SUCCESS:
            self._reporter.report()
        return result

    def force_flush(self, timeout_millis=30_000) -> bool:
        try:
            return self._delegate.force_flush(timeout_millis=timeout_millis)
        except Exception:
            self._reporter.report()
            return False

    def shutdown(self) -> None:
        try:
            self._delegate.shutdown()
        except Exception:
            self._reporter.report()

    def __getattr__(self, name):
        return getattr(self._delegate, name)


def wrap_metric_exporter(delegate, reporter: CurveExportFailureReporter):
    from opentelemetry.sdk.metrics.export import MetricExporter, MetricExportResult

    class CurveMetricExporter(MetricExporter):
        def __init__(self):
            super().__init__(
                preferred_temporality=delegate._preferred_temporality,
                preferred_aggregation=delegate._preferred_aggregation,
            )

        def export(self, metrics_data, timeout_millis=10_000, **kwargs):
            try:
                result = delegate.export(metrics_data, timeout_millis=timeout_millis, **kwargs)
            except Exception:
                reporter.report()
                return MetricExportResult.FAILURE
            if result is not MetricExportResult.SUCCESS:
                reporter.report()
            return result

        def force_flush(self, timeout_millis=10_000) -> bool:
            try:
                return delegate.force_flush(timeout_millis=timeout_millis)
            except Exception:
                reporter.report()
                return False

        def shutdown(self, timeout_millis=30_000, **kwargs) -> None:
            try:
                delegate.shutdown(timeout_millis=timeout_millis, **kwargs)
            except Exception:
                reporter.report()

        def __getattr__(self, name):
            return getattr(delegate, name)

    return CurveMetricExporter()
