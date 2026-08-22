# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.db import close_old_connections
from django.utils import timezone
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from plane.curve.models import DomainEvent, Operation, OperationStatus
from plane.curve.observability.instrumentation import observe_curve_span
from plane.curve.observability.gauges import mark_worker_heartbeat
from plane.curve.observability.propagation import event_contract
from plane.curve.policy_services import transition_operation_with_service_authorization
from plane.curve.services import (
    acknowledge_outbox,
    claim_due_outbox,
    recover_expired_outbox_claims,
    retry_outbox,
)
from plane.curve.temporal.application import _service_actor, _service_authorization
from plane.curve.temporal.constants import (
    APPLICATION_EVENT_DESTINATION,
    TASK_QUEUE,
    TEMPORAL_DESTINATION,
    WORKFLOW_TYPE,
    operation_workflow_id,
)
from plane.curve.temporal.contracts import (
    CancelSignalV1,
    CurveOperationWorkflowInputV1,
)


logger = logging.getLogger(__name__)
OUTBOX_LEASE = timedelta(seconds=30)
RETRY_DELAY = timedelta(seconds=5)


class TemporalDispatchStateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedDispatch:
    action: str
    workflow_id: str
    workspace_id: uuid.UUID
    operation_id: uuid.UUID
    event_id: uuid.UUID
    traceparent: str | None
    workflow_input: CurveOperationWorkflowInputV1 | None = None
    cancel_signal: CancelSignalV1 | None = None


def _observe_delivery_outcome(*, runtime, workspace_id, result: str, retry_attempt: int) -> None:
    if runtime is None or not runtime.enabled:
        return
    attributes = {
        "curve.component": "OUTBOX_RELAY",
        "curve.outbox.destination_kind": "TEMPORAL",
        "curve.result": result,
    }
    try:
        runtime.registry.record("curve.outbox.delivery", 1, attributes=attributes)
        if result == "RETRIED":
            runtime.structured_logger.emit(
                event_code="CURVE_OUTBOX_RETRY_SCHEDULED",
                level="WARNING",
                workspace_id=workspace_id,
                attributes={
                    **attributes,
                    "curve.retry.attempt": retry_attempt,
                },
            )
    except Exception:
        return


def _prepare_dispatch(*, workspace_id: uuid.UUID, event_id: uuid.UUID) -> PreparedDispatch:
    event = DomainEvent.objects.filter(
        workspace_id=workspace_id,
        id=event_id,
        event_type="curve.operation.state_changed",
        aggregate_type="OPERATION",
    ).first()
    if event is None:
        raise TemporalDispatchStateError("Curve Operation event is unavailable")
    try:
        _, traceparent = event_contract(event.payload_schema, event.payload)
    except ValueError as error:
        raise TemporalDispatchStateError("Curve Operation event contract is unsupported") from error
    operation = Operation.objects.filter(workspace_id=workspace_id, id=event.aggregate_id).first()
    if operation is None:
        raise TemporalDispatchStateError("Curve Operation is unavailable")
    event_status = event.payload.get("status")

    workflow_id = operation_workflow_id(
        workspace_id=str(workspace_id),
        operation_id=str(operation.id),
    )
    if event_status == OperationStatus.PENDING and operation.status == OperationStatus.PENDING:
        operation = transition_operation_with_service_authorization(
            workspace_id=workspace_id,
            operation_id=operation.id,
            expected_version=operation.aggregate_version,
            status=OperationStatus.QUEUED,
            service_actor=_service_actor(),
            service_authorization=_service_authorization(workspace_id),
            correlation_id=operation.correlation_id,
            causation_id=str(event.id),
            destination=APPLICATION_EVENT_DESTINATION,
            workflow_id=workflow_id,
            traceparent=traceparent,
        )
    elif event_status == OperationStatus.PENDING and operation.status not in {
        OperationStatus.QUEUED,
        OperationStatus.RUNNING,
        OperationStatus.CANCEL_REQUESTED,
        OperationStatus.SUCCEEDED,
        OperationStatus.CANCELLED,
    }:
        raise TemporalDispatchStateError("Curve Operation cannot be dispatched")

    if operation.workflow_id != workflow_id:
        raise TemporalDispatchStateError("Curve Operation workflow binding is unavailable")
    if event_status == OperationStatus.PENDING:
        return PreparedDispatch(
            action="START",
            workflow_id=workflow_id,
            workspace_id=workspace_id,
            operation_id=operation.id,
            event_id=event.id,
            traceparent=traceparent,
            workflow_input=CurveOperationWorkflowInputV1(
                schema_version="1.0",
                workspace_id=str(workspace_id),
                operation_id=str(operation.id),
                operation_version=operation.aggregate_version,
                operation_type=operation.operation_type,
                correlation_id=operation.correlation_id,
            ),
        )
    if event_status == OperationStatus.CANCEL_REQUESTED:
        if operation.status not in {OperationStatus.CANCEL_REQUESTED, OperationStatus.CANCELLED}:
            raise TemporalDispatchStateError("Curve cancellation event is stale")
        return PreparedDispatch(
            action="CANCEL",
            workflow_id=workflow_id,
            workspace_id=workspace_id,
            operation_id=operation.id,
            event_id=event.id,
            traceparent=traceparent,
            cancel_signal=CancelSignalV1(
                schema_version="1.0",
                actor_ref="service:curve-worker",
                reason_code="STATE_RECONCILIATION",
                command_id=event.causation_id or f"cancel-event:{event.id}",
            ),
        )
    raise TemporalDispatchStateError("Curve Temporal event status is unsupported")


async def _dispatch_claimed_event(*, client: Client, outbox, worker_id: str, telemetry_runtime=None) -> None:
    dispatch = await asyncio.to_thread(
        _prepare_dispatch,
        workspace_id=outbox.workspace_id,
        event_id=outbox.event_id,
    )
    attributes = {
        "curve.component": "OUTBOX_RELAY",
        "curve.event.id": str(dispatch.event_id),
        "curve.operation.id": str(dispatch.operation_id),
        "curve.outbox.destination_kind": "TEMPORAL",
        "curve.result": "SUCCEEDED",
        "curve.retry.attempt": outbox.attempt_count,
    }
    with observe_curve_span(
        component="TEMPORAL_WORKER",
        span_name="curve.outbox.dispatch",
        workspace_id=dispatch.workspace_id,
        parent_traceparent=dispatch.traceparent,
        attributes=attributes,
        runtime=telemetry_runtime,
    ) as observation:
        delivery_result = "SUCCEEDED"
        try:
            if dispatch.action == "START":
                try:
                    await client.start_workflow(
                        WORKFLOW_TYPE,
                        dispatch.workflow_input,
                        id=dispatch.workflow_id,
                        task_queue=TASK_QUEUE,
                        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                    )
                except WorkflowAlreadyStartedError:
                    delivery_result = "REPLAYED"
                    observation.set_attributes({"curve.result": delivery_result})
            elif dispatch.action == "CANCEL":
                await client.get_workflow_handle(dispatch.workflow_id).signal(
                    "request_cancel",
                    dispatch.cancel_signal,
                )
            else:
                raise TemporalDispatchStateError("Curve Temporal dispatch action is unsupported")
            await asyncio.to_thread(
                acknowledge_outbox,
                workspace_id=outbox.workspace_id,
                outbox_id=outbox.id,
                worker_id=worker_id,
            )
        except Exception:
            observation.set_attributes({"curve.result": "FAILED"})
            raise
        observation.record(
            "curve.outbox.delivery",
            1,
            attributes={
                "curve.component": "OUTBOX_RELAY",
                "curve.outbox.destination_kind": "TEMPORAL",
                "curve.result": delivery_result,
            },
        )
        observation.log(
            event_code="CURVE_OUTBOX_DELIVERED",
            level="INFO",
            workspace_id=dispatch.workspace_id,
            attributes={
                "curve.event.id": str(dispatch.event_id),
                "curve.operation.id": str(dispatch.operation_id),
                "curve.outbox.destination_kind": "TEMPORAL",
                "curve.result": delivery_result,
                "curve.retry.attempt": outbox.attempt_count,
            },
        )
        if dispatch.action == "START":
            observation.log(
                event_code="CURVE_WORKFLOW_STARTED",
                level="INFO",
                workspace_id=dispatch.workspace_id,
                attributes={
                    "curve.operation.id": str(dispatch.operation_id),
                    "curve.result": delivery_result,
                    "curve.workflow.type": "FOUNDATION_PROBE_V1",
                },
            )


async def relay_workspace_once(
    *, client: Client, workspace_id: uuid.UUID, worker_id: str, telemetry_runtime=None
) -> int:
    close_old_connections()
    await asyncio.to_thread(
        recover_expired_outbox_claims,
        workspace_id=workspace_id,
        actor=_service_actor(),
        correlation_id=f"curve-temporal-recovery:{workspace_id}",
    )
    claimed = await asyncio.to_thread(
        claim_due_outbox,
        workspace_id=workspace_id,
        worker_id=worker_id,
        limit=10,
        lease_duration=OUTBOX_LEASE,
        destination=TEMPORAL_DESTINATION,
    )
    delivered = 0
    for outbox in claimed:
        try:
            await _dispatch_claimed_event(
                client=client,
                outbox=outbox,
                worker_id=worker_id,
                telemetry_runtime=telemetry_runtime,
            )
            delivered += 1
        except Exception:
            _observe_delivery_outcome(
                runtime=telemetry_runtime,
                workspace_id=workspace_id,
                result="FAILED",
                retry_attempt=outbox.attempt_count,
            )
            logger.error(
                "Curve Temporal dispatch failed",
                extra={"curve_error_code": "CURVE_TEMPORAL_UNAVAILABLE"},
            )
            try:
                await asyncio.to_thread(
                    retry_outbox,
                    workspace_id=workspace_id,
                    outbox_id=outbox.id,
                    worker_id=worker_id,
                    next_attempt_at=timezone.now() + RETRY_DELAY,
                    error={"code": "TEMPORAL_DISPATCH_UNAVAILABLE", "retryable": True},
                )
                _observe_delivery_outcome(
                    runtime=telemetry_runtime,
                    workspace_id=workspace_id,
                    result="RETRIED",
                    retry_attempt=outbox.attempt_count,
                )
            except Exception:
                logger.error(
                    "Curve Temporal dispatch retry scheduling failed",
                    extra={"curve_error_code": "CURVE_TEMPORAL_UNAVAILABLE"},
                )
    close_old_connections()
    return delivered


def _enabled_workspace_ids() -> list[uuid.UUID]:
    from django.conf import settings
    from plane.db.models import Workspace

    if not settings.CURVE_ENABLED:
        return []
    slugs = tuple(sorted(settings.CURVE_ENABLED_WORKSPACE_SLUGS))
    if not slugs:
        return []
    return list(Workspace.objects.filter(slug__in=slugs).values_list("id", flat=True))


async def run_relay_loop(*, client: Client, worker_id: str, stop_event: asyncio.Event, telemetry_runtime=None) -> None:
    while not stop_event.is_set():
        mark_worker_heartbeat()
        workspace_ids = await asyncio.to_thread(_enabled_workspace_ids)
        for workspace_id in workspace_ids:
            await relay_workspace_once(
                client=client,
                workspace_id=workspace_id,
                worker_id=worker_id,
                telemetry_runtime=telemetry_runtime,
            )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=0.5)
        except TimeoutError:
            continue
