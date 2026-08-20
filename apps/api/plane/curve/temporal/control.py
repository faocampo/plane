# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import asyncio
import uuid

from temporalio.client import Client

from plane.curve.models import Operation, OperationStatus
from plane.curve.policy_services import transition_operation_with_service_authorization
from plane.curve.temporal.application import _service_actor, _service_authorization
from plane.curve.temporal.constants import TEMPORAL_DESTINATION, operation_workflow_id
from plane.curve.temporal.contracts import CancelSignalV1


class TemporalCancellationStateError(RuntimeError):
    pass


def _record_cancellation_request(
    *,
    workspace_id: uuid.UUID,
    operation_id: uuid.UUID,
    correlation_id: str,
    command_id: str,
) -> str:
    operation = Operation.objects.filter(workspace_id=workspace_id, id=operation_id).first()
    if operation is None:
        raise TemporalCancellationStateError("Curve Operation is unavailable")
    expected_workflow_id = operation_workflow_id(
        workspace_id=str(workspace_id),
        operation_id=str(operation_id),
    )
    if operation.workflow_id != expected_workflow_id:
        raise TemporalCancellationStateError("Curve workflow is not bound")
    if operation.status in {OperationStatus.CANCEL_REQUESTED, OperationStatus.CANCELLED}:
        return expected_workflow_id
    if operation.status not in {OperationStatus.QUEUED, OperationStatus.RUNNING}:
        raise TemporalCancellationStateError("Curve Operation cannot be cancelled")
    transition_operation_with_service_authorization(
        workspace_id=workspace_id,
        operation_id=operation_id,
        expected_version=operation.aggregate_version,
        status=OperationStatus.CANCEL_REQUESTED,
        service_actor=_service_actor(),
        service_authorization=_service_authorization(workspace_id),
        correlation_id=correlation_id,
        causation_id=command_id,
        destination=TEMPORAL_DESTINATION,
    )
    return expected_workflow_id


async def request_cancellation(
    *,
    client: Client,
    workspace_id: uuid.UUID,
    operation_id: uuid.UUID,
    actor_ref: str,
    reason_code: str,
    command_id: str,
    correlation_id: str,
) -> None:
    signal = CancelSignalV1(
        schema_version="1.0",
        actor_ref=actor_ref,
        reason_code=reason_code,
        command_id=command_id,
    )
    workflow_id = await asyncio.to_thread(
        _record_cancellation_request,
        workspace_id=workspace_id,
        operation_id=operation_id,
        correlation_id=correlation_id,
        command_id=command_id,
    )
    await client.get_workflow_handle(workflow_id).signal(
        "request_cancel",
        signal,
    )
