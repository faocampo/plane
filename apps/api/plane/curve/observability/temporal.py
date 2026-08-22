# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from temporalio import activity
from temporalio.client import Interceptor as ClientInterceptor
from temporalio.client import OutboundInterceptor as ClientOutboundInterceptor
from temporalio.converter import PayloadConverter
from temporalio.worker import ActivityInboundInterceptor
from temporalio.worker import Interceptor as WorkerInterceptor
from temporalio.worker import WorkflowInboundInterceptor, WorkflowOutboundInterceptor

from plane.curve.observability.instrumentation import observe_curve_span
from plane.curve.observability.propagation import (
    TEMPORAL_TRACE_HEADER,
    current_traceparent,
    valid_traceparent,
)
from plane.curve.temporal.constants import (
    MARK_CANCELLED_ACTIVITY,
    MARK_RUNNING_ACTIVITY,
    MARK_SUCCEEDED_ACTIVITY,
)


_ACTIVITY_TYPES = {
    MARK_CANCELLED_ACTIVITY: "MARK_OPERATION_CANCELLED",
    MARK_RUNNING_ACTIVITY: "MARK_OPERATION_RUNNING",
    MARK_SUCCEEDED_ACTIVITY: "MARK_OPERATION_SUCCEEDED",
}


def _encode_traceparent(traceparent: str | None):
    if not valid_traceparent(traceparent):
        return None
    return PayloadConverter.default.to_payloads([traceparent])[0]


def _decode_traceparent(headers) -> str | None:
    payload = headers.get(TEMPORAL_TRACE_HEADER)
    if payload is None:
        return None
    try:
        value = PayloadConverter.default.from_payloads([payload])[0]
    except Exception:
        return None
    return value if valid_traceparent(value) else None


def _inject_current_traceparent(input) -> None:
    payload = _encode_traceparent(current_traceparent())
    if payload is not None:
        input.headers = {**input.headers, TEMPORAL_TRACE_HEADER: payload}


class _CurveClientOutboundInterceptor(ClientOutboundInterceptor):
    async def start_workflow(self, input):
        _inject_current_traceparent(input)
        return await super().start_workflow(input)

    async def signal_workflow(self, input):
        _inject_current_traceparent(input)
        return await super().signal_workflow(input)


class _CurveWorkflowOutboundInterceptor(WorkflowOutboundInterceptor):
    def __init__(self, next, root) -> None:
        super().__init__(next)
        self._root = root

    def start_activity(self, input):
        if self._root.trace_payload is not None:
            input.headers = {
                **input.headers,
                TEMPORAL_TRACE_HEADER: self._root.trace_payload,
            }
        return super().start_activity(input)

    def start_local_activity(self, input):
        if self._root.trace_payload is not None:
            input.headers = {
                **input.headers,
                TEMPORAL_TRACE_HEADER: self._root.trace_payload,
            }
        return super().start_local_activity(input)


class CurveWorkflowTraceInterceptor(WorkflowInboundInterceptor):
    """Deterministically copy the opaque Curve trace header to activities."""

    def __init__(self, next) -> None:
        super().__init__(next)
        self.trace_payload = None

    def init(self, outbound) -> None:
        super().init(_CurveWorkflowOutboundInterceptor(outbound, self))

    async def execute_workflow(self, input):
        self.trace_payload = input.headers.get(TEMPORAL_TRACE_HEADER)
        return await super().execute_workflow(input)

    async def handle_signal(self, input) -> None:
        payload = input.headers.get(TEMPORAL_TRACE_HEADER)
        if payload is not None:
            self.trace_payload = payload
        await super().handle_signal(input)


class _CurveActivityInboundInterceptor(ActivityInboundInterceptor):
    def __init__(self, next, runtime) -> None:
        super().__init__(next)
        self._runtime = runtime

    async def execute_activity(self, input):
        info = activity.info()
        activity_type = _ACTIVITY_TYPES.get(info.activity_type)
        activity_input = input.args[0] if input.args else None
        workspace_id = getattr(activity_input, "workspace_id", None)
        operation_id = getattr(activity_input, "operation_id", None)
        attempt = max(0, info.attempt - 1)
        attributes = {
            "curve.activity.type": activity_type,
            "curve.component": "TEMPORAL_WORKER",
            "curve.error.code": "NONE",
            "curve.operation.id": operation_id,
            "curve.result": "SUCCEEDED",
            "curve.retry.attempt": attempt,
        }
        with observe_curve_span(
            component="TEMPORAL_WORKER",
            span_name="curve.activity.run",
            workspace_id=workspace_id,
            parent_traceparent=_decode_traceparent(input.headers),
            attributes=attributes,
            runtime=self._runtime,
        ) as observation:
            try:
                result = await super().execute_activity(input)
            except Exception:
                observation.set_attributes(
                    {
                        "curve.error.code": "CURVE_INVALID_OPERATION_TRANSITION",
                        "curve.result": "FAILED",
                    }
                )
                observation.record(
                    "curve.activity.execution",
                    1,
                    attributes={
                        "curve.activity.type": activity_type,
                        "curve.component": "TEMPORAL_WORKER",
                        "curve.result": "FAILED",
                    },
                )
                observation.log(
                    event_code="CURVE_ACTIVITY_FAILED",
                    level="ERROR",
                    workspace_id=workspace_id,
                    attributes={
                        "curve.activity.type": activity_type,
                        "curve.error.code": "CURVE_INVALID_OPERATION_TRANSITION",
                    },
                )
                raise
            observation.record(
                "curve.activity.execution",
                1,
                attributes={
                    "curve.activity.type": activity_type,
                    "curve.component": "TEMPORAL_WORKER",
                    "curve.result": "SUCCEEDED",
                },
            )
            operation_status = getattr(result, "operation_status", "")
            if operation_status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                workflow_result = (
                    "CANCELLED"
                    if operation_status == "CANCELLED"
                    else ("SUCCEEDED" if operation_status == "SUCCEEDED" else "FAILED")
                )
                observation.record(
                    "curve.workflow.completed",
                    1,
                    attributes={
                        "curve.component": "TEMPORAL_WORKER",
                        "curve.workflow.type": "FOUNDATION_PROBE_V1",
                        "curve.result": workflow_result,
                    },
                )
                observation.log(
                    event_code="CURVE_WORKFLOW_COMPLETED",
                    level="INFO" if workflow_result != "FAILED" else "ERROR",
                    workspace_id=workspace_id,
                    attributes={
                        "curve.operation.id": operation_id,
                        "curve.result": workflow_result,
                        "curve.workflow.type": "FOUNDATION_PROBE_V1",
                    },
                )
            if attempt:
                observation.record(
                    "curve.activity.retry",
                    1,
                    attributes={
                        "curve.activity.type": activity_type,
                        "curve.component": "TEMPORAL_WORKER",
                    },
                )
            observation.log(
                event_code="CURVE_ACTIVITY_COMPLETED",
                level="INFO",
                workspace_id=workspace_id,
                attributes={"curve.activity.type": activity_type},
            )
            return result


class CurveTemporalInterceptor(ClientInterceptor, WorkerInterceptor):
    """Curve-owned traceparent-only Temporal client and worker interceptor."""

    def __init__(self, runtime) -> None:
        self._runtime = runtime

    def intercept_client(self, next):
        return _CurveClientOutboundInterceptor(next)

    def intercept_activity(self, next):
        return _CurveActivityInboundInterceptor(next, self._runtime)

    def workflow_interceptor_class(self, input):
        return CurveWorkflowTraceInterceptor
