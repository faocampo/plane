# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import json
import logging
import os
import uuid


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings.curve_worker")

import django  # noqa: E402


django.setup()

from plane.curve.observability.runtime import get_telemetry_runtime  # noqa: E402
from plane.curve.observability.scope import workspace_scope  # noqa: E402


_WORKSPACES = (
    uuid.UUID("11111111-1111-4111-8111-111111111111"),
    uuid.UUID("22222222-2222-4222-8222-222222222222"),
)
_ROTATION_KEY = hashlib.sha256(b"curve-local-rotation-proof-v1").digest()


def _record_fixture(runtime) -> None:
    records = (
        ("curve.operation.started", 10, {"curve.component": "API", "curve.operation.type": "FOUNDATION_PROBE"}),
        (
            "curve.operation.completed",
            8,
            {
                "curve.component": "API",
                "curve.operation.type": "FOUNDATION_PROBE",
                "curve.result": "SUCCEEDED",
            },
        ),
        (
            "curve.operation.completed",
            1,
            {
                "curve.component": "API",
                "curve.operation.type": "FOUNDATION_PROBE",
                "curve.result": "FAILED",
            },
        ),
        (
            "curve.operation.completed",
            1,
            {
                "curve.component": "API",
                "curve.operation.type": "FOUNDATION_PROBE",
                "curve.result": "CANCELLED",
            },
        ),
        (
            "curve.operation.duration",
            1.25,
            {
                "curve.component": "API",
                "curve.operation.type": "FOUNDATION_PROBE",
                "curve.result": "SUCCEEDED",
            },
        ),
        (
            "curve.outbox.delivery",
            8,
            {
                "curve.component": "OUTBOX_RELAY",
                "curve.outbox.destination_kind": "TEMPORAL",
                "curve.result": "SUCCEEDED",
            },
        ),
        (
            "curve.outbox.delivery",
            1,
            {
                "curve.component": "OUTBOX_RELAY",
                "curve.outbox.destination_kind": "TEMPORAL",
                "curve.result": "RETRIED",
            },
        ),
        (
            "curve.workflow.completed",
            8,
            {
                "curve.component": "TEMPORAL_WORKER",
                "curve.workflow.type": "FOUNDATION_PROBE_V1",
                "curve.result": "SUCCEEDED",
            },
        ),
        (
            "curve.activity.execution",
            8,
            {
                "curve.activity.type": "MARK_OPERATION_SUCCEEDED",
                "curve.component": "TEMPORAL_WORKER",
                "curve.result": "SUCCEEDED",
            },
        ),
        (
            "curve.activity.retry",
            1,
            {
                "curve.activity.type": "MARK_OPERATION_RUNNING",
                "curve.component": "TEMPORAL_WORKER",
            },
        ),
        ("curve.sse.connections", 1, {"curve.component": "SSE"}),
        ("curve.sse.resume", 1, {"curve.component": "SSE", "curve.result": "REPLAYED"}),
        ("curve.audit.append", 1, {"curve.component": "AUDIT", "curve.result": "FAILED"}),
    )
    for name, value, attributes in records:
        if not runtime.registry.record(name, value, attributes=attributes):
            raise RuntimeError(f"Curve local proof could not record {name}")


def _scope_evidence(runtime) -> dict:
    current = [runtime.workspace_scope(workspace_id) for workspace_id in _WORKSPACES]
    rotated = [workspace_scope(workspace_id=workspace_id, key=_ROTATION_KEY) for workspace_id in _WORKSPACES]
    if any(scope is None for scope in current) or len(set(current)) != 2 or len(set(rotated)) != 2:
        raise RuntimeError("Curve local proof workspace scopes are unavailable")
    if set(current) & set(rotated):
        raise RuntimeError("Curve local proof key rotation did not change workspace scopes")

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for workspace_id in _WORKSPACES:
        runtime.structured_logger.emit(
            event_code="CURVE_COMMAND_DENIED",
            level="WARNING",
            workspace_id=workspace_id,
            attributes={
                "curve.command.type": "CREATE_FOUNDATION_PROBE",
                "curve.error.code": "CURVE_POLICY_DENIED",
                "curve.result": "DENIED",
            },
        )
        with runtime.registry.span(
            "curve.http.command",
            attributes={
                "curve.command.type": "CREATE_FOUNDATION_PROBE",
                "curve.component": "API",
                "curve.error.code": "CURVE_POLICY_DENIED",
                "curve.operation.type": "FOUNDATION_PROBE",
                "curve.result": "DENIED",
                "curve.workspace.scope": runtime.workspace_scope(workspace_id),
            },
        ):
            pass

    return {
        "workspace_count": len(current),
        "current_scopes_distinct": True,
        "rotated_scopes_distinct": True,
        "rotation_changed_scopes": True,
        "active_key_id": runtime.configuration.workspace_scope_key_id,
        "rotated_key_id": "local-dev-v2-proof",
        "raw_workspace_ids_exported": False,
    }


def run_proof() -> dict:
    runtime = get_telemetry_runtime(component="API")
    if not runtime.enabled or runtime.configuration.mode.value != "OTLP":
        raise RuntimeError("Curve local OTLP telemetry is unavailable")
    _record_fixture(runtime)
    scope_evidence = _scope_evidence(runtime)
    if runtime.tracer_provider is not None and not runtime.tracer_provider.force_flush(timeout_millis=10_000):
        raise RuntimeError("Curve local proof trace flush failed")
    if runtime.meter_provider is not None and not runtime.meter_provider.force_flush(timeout_millis=10_000):
        raise RuntimeError("Curve local proof metric flush failed")
    runtime.shutdown()
    return {
        "schema_version": "curve-local-observability-proof/v1",
        "telemetry_mode": "OTLP",
        "endpoint": "http://otel-collector:4317",
        "synthetic_fixture_exported": True,
        "scope_evidence": scope_evidence,
    }


def main() -> None:
    print(json.dumps(run_proof(), separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
