# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from contextlib import nullcontext

from plane.curve.observability.manifest import telemetry_manifest
from plane.curve.observability.redaction import sanitize_attributes


class UnknownTelemetrySignal(ValueError):
    pass


class CurveTelemetryRegistry:
    def __init__(self, *, tracer=None, meter=None):
        manifest = telemetry_manifest()
        self._tracer = tracer
        self._meter = meter
        self._metric_contracts = {item["name"]: item for item in manifest["metrics"]}
        self._span_contracts = {item["name"]: item for item in manifest["spans"]}
        self._instruments = {}
        if meter is not None:
            self._create_instruments()

    def _create_instruments(self):
        for name, contract in self._metric_contracts.items():
            if contract["instrument"] == "GAUGE":
                continue
            method = {
                "COUNTER": self._meter.create_counter,
                "UP_DOWN_COUNTER": self._meter.create_up_down_counter,
                "HISTOGRAM": self._meter.create_histogram,
            }[contract["instrument"]]
            self._instruments[name] = method(
                name,
                unit=contract["unit"],
                description=contract["description"],
            )

    def span(self, name: str, *, attributes: dict | None = None, context=None):
        contract = self._span_contracts.get(name)
        if contract is None:
            raise UnknownTelemetrySignal(name)
        if self._tracer is None:
            return nullcontext(None)
        from opentelemetry.trace import SpanKind

        kind = getattr(SpanKind, contract["kind"])
        safe = sanitize_attributes(
            signal="trace",
            allowed_names=frozenset(contract["allowed_attributes"]),
            attributes=attributes or {},
        )
        return self._tracer.start_as_current_span(
            name,
            kind=kind,
            attributes=safe,
            context=context,
            record_exception=False,
            set_status_on_exception=False,
        )

    def set_span_attributes(self, name: str, span, attributes: dict) -> None:
        contract = self._span_contracts.get(name)
        if contract is None:
            raise UnknownTelemetrySignal(name)
        if span is None:
            return
        safe = sanitize_attributes(
            signal="trace",
            allowed_names=frozenset(contract["allowed_attributes"]),
            attributes=attributes,
        )
        for key, value in safe.items():
            span.set_attribute(key, value)

    def record(self, name: str, value: int | float, *, attributes: dict):
        contract = self._metric_contracts.get(name)
        if contract is None or contract["instrument"] == "GAUGE":
            raise UnknownTelemetrySignal(name)
        safe = sanitize_attributes(
            signal="metric",
            allowed_names=frozenset(contract["allowed_attributes"]),
            attributes=attributes,
        )
        if set(safe) != set(contract["allowed_attributes"]):
            return False
        instrument = self._instruments.get(name)
        if instrument is None:
            return False
        if contract["instrument"] == "HISTOGRAM":
            instrument.record(value, safe)
        else:
            instrument.add(value, safe)
        return True

    def register_gauge(self, name: str, callback) -> bool:
        contract = self._metric_contracts.get(name)
        if contract is None or contract["instrument"] != "GAUGE":
            raise UnknownTelemetrySignal(name)
        if self._meter is None or name in self._instruments:
            return False

        from opentelemetry.metrics import Observation

        def closed_callback(options):
            try:
                values = callback(options)
            except Exception:
                return []
            observations = []
            for value, attributes in values:
                safe = sanitize_attributes(
                    signal="metric",
                    allowed_names=frozenset(contract["allowed_attributes"]),
                    attributes=attributes,
                )
                if set(safe) == set(contract["allowed_attributes"]):
                    observations.append(Observation(value, attributes=safe))
            return observations

        self._instruments[name] = self._meter.create_observable_gauge(
            name,
            callbacks=[closed_callback],
            unit=contract["unit"],
            description=contract["description"],
        )
        return True

    @property
    def metric_names(self) -> frozenset[str]:
        return frozenset(self._metric_contracts)

    @property
    def span_names(self) -> frozenset[str]:
        return frozenset(self._span_contracts)
