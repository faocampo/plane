# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import re


OPERATION_EVENT_V1_SCHEMA = "https://curve.x3m.internal/contracts/schemas/operation-event-v1.schema.json"
OPERATION_EVENT_V2_SCHEMA = "https://curve.x3m.internal/contracts/schemas/operation-event-v2.schema.json"
TEMPORAL_TRACE_HEADER = "_curve_traceparent_v1"
TRACEPARENT_PATTERN = re.compile(r"^00-(?!0{32})[0-9a-f]{32}-(?!0{16})[0-9a-f]{16}-[0-9a-f]{2}$")


def valid_traceparent(value) -> bool:
    return isinstance(value, str) and TRACEPARENT_PATTERN.fullmatch(value) is not None


def extract_trace_context(traceparent: str | None):
    from opentelemetry.propagators.textmap import DefaultGetter
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    carrier = {"traceparent": traceparent} if valid_traceparent(traceparent) else {}
    return TraceContextTextMapPropagator().extract(carrier=carrier, getter=DefaultGetter())


def current_traceparent() -> str | None:
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    carrier = {}
    TraceContextTextMapPropagator().inject(carrier)
    value = carrier.get("traceparent")
    return value if valid_traceparent(value) else None


def event_contract(payload_schema: str, payload: dict) -> tuple[str, str | None]:
    """Return the supported event version and an optional validated trace context."""

    if payload_schema == OPERATION_EVENT_V1_SCHEMA:
        return "v1", None
    if payload_schema == OPERATION_EVENT_V2_SCHEMA:
        value = payload.get("traceparent")
        if value is not None and not valid_traceparent(value):
            raise ValueError("invalid Curve operation-event traceparent")
        return "v2", value
    raise ValueError("unsupported Curve operation-event schema")
