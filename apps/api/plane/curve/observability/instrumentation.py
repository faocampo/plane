# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
import os

from plane.curve.observability.propagation import current_traceparent, extract_trace_context
from plane.curve.observability.runtime import get_telemetry_runtime


@dataclass(slots=True)
class CurveObservation:
    runtime: object | None
    span_name: str
    span: object | None

    @property
    def enabled(self) -> bool:
        return bool(self.runtime is not None and self.runtime.enabled)

    def traceparent(self) -> str | None:
        return current_traceparent() if self.enabled else None

    def set_attributes(self, attributes: dict) -> None:
        if not self.enabled:
            return
        try:
            self.runtime.registry.set_span_attributes(self.span_name, self.span, attributes)
        except Exception:
            return

    def record(self, name: str, value: int | float, *, attributes: dict) -> bool:
        if not self.enabled:
            return False
        try:
            return self.runtime.registry.record(name, value, attributes=attributes)
        except Exception:
            return False

    def log(self, *, event_code: str, level: str, workspace_id=None, attributes=None) -> bool:
        if not self.enabled:
            return False
        try:
            self.runtime.structured_logger.emit(
                event_code=event_code,
                level=level,
                workspace_id=workspace_id,
                attributes=attributes,
            )
            return True
        except Exception:
            return False


def curve_attributes(*, runtime, workspace_id=None, attributes=None) -> dict:
    safe = dict(attributes or {})
    if workspace_id is not None:
        try:
            scope = runtime.workspace_scope(workspace_id)
        except Exception:
            scope = None
        if scope is not None:
            safe["curve.workspace.scope"] = scope
    return safe


def _runtime(component: str):
    try:
        runtime = get_telemetry_runtime(component=component)
        return runtime if runtime.enabled else None
    except Exception:
        return None


def _process_component() -> str:
    settings_module = os.environ.get("DJANGO_SETTINGS_MODULE", "")
    return "TEMPORAL_WORKER" if settings_module.endswith(".curve_worker") else "API"


def observe_operation_started(*, component: str, operation, replayed: bool) -> None:
    runtime = _runtime(component)
    if runtime is None or replayed:
        return
    try:
        runtime.registry.record(
            "curve.operation.started",
            1,
            attributes={
                "curve.component": component,
                "curve.operation.type": operation.operation_type,
            },
        )
    except Exception:
        return


def observe_operation_terminal(*, component: str, operation) -> None:
    if operation.completed_at is None:
        return
    runtime = _runtime(component)
    if runtime is None:
        return
    result = (
        operation.status
        if operation.status == "CANCELLED"
        else ("SUCCEEDED" if operation.status == "SUCCEEDED" else "FAILED")
    )
    attributes = {
        "curve.component": component,
        "curve.operation.type": operation.operation_type,
        "curve.result": result,
    }
    try:
        runtime.registry.record("curve.operation.completed", 1, attributes=attributes)
        duration = max(0.0, (operation.completed_at - operation.created_at).total_seconds())
        runtime.registry.record("curve.operation.duration", duration, attributes=attributes)
        runtime.structured_logger.emit(
            event_code="CURVE_OPERATION_TERMINAL",
            level="INFO" if result != "FAILED" else "ERROR",
            workspace_id=operation.workspace_id,
            attributes={
                "curve.operation.id": str(operation.id),
                "curve.operation.status": operation.status,
                "curve.operation.type": operation.operation_type,
                "curve.result": result,
            },
        )
    except Exception:
        return


def observe_audit_append(*, result: str) -> None:
    runtime = _runtime(_process_component())
    if runtime is None:
        return
    try:
        runtime.registry.record(
            "curve.audit.append",
            1,
            attributes={"curve.component": "AUDIT", "curve.result": result},
        )
    except Exception:
        return


def observe_command_denied(*, workspace_id, command_type: str) -> None:
    runtime = _runtime(_process_component())
    if runtime is None:
        return
    try:
        runtime.structured_logger.emit(
            event_code="CURVE_COMMAND_DENIED",
            level="WARNING",
            workspace_id=workspace_id,
            attributes={
                "curve.command.type": command_type,
                "curve.error.code": "CURVE_POLICY_DENIED",
                "curve.result": "DENIED",
            },
        )
    except Exception:
        return


@contextmanager
def observe_curve_span(
    *,
    component: str,
    span_name: str,
    workspace_id=None,
    parent_traceparent: str | None = None,
    attributes=None,
    runtime=None,
):
    """Open a private Curve span without making telemetry an application dependency."""

    try:
        selected_runtime = runtime or get_telemetry_runtime(component=component)
        enabled = selected_runtime.enabled
        safe_attributes = curve_attributes(
            runtime=selected_runtime,
            workspace_id=workspace_id,
            attributes=attributes,
        )
        manager = (
            selected_runtime.registry.span(
                span_name,
                attributes=safe_attributes,
                context=extract_trace_context(parent_traceparent),
            )
            if enabled
            else nullcontext(None)
        )
    except Exception:
        selected_runtime = None
        manager = nullcontext(None)

    with manager as span:
        yield CurveObservation(
            runtime=selected_runtime,
            span_name=span_name,
            span=span,
        )
