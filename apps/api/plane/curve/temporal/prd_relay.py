# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Bounded delivery of metadata-only PRD Operation events to a versioned workflow."""

import asyncio
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction, close_old_connections
from django.utils import timezone
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from plane.db.models import Workspace
from plane.curve.models import DomainEvent, Operation, PrdAcceptedCommand
from plane.curve.config import is_curve_enabled_for_workspace
from plane.curve.observability.propagation import event_contract
from plane.curve.prd_completion import _worker_grant, _transition, complete_prd_operation
from plane.curve.services import claim_due_outbox, acknowledge_outbox, retry_outbox, dead_letter_outbox
from .contracts import OperationActivityInputV1
from .constants import TASK_QUEUE
from .prd_contracts import PRD_DESTINATION, PRD_WORKFLOW_TYPE, prd_workflow_id
from .relay import OUTBOX_LEASE, RETRY_DELAY


class PrdDispatchUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("PRD_DISPATCH_UNAVAILABLE")


def prd_delivery_enabled():
    return (
        getattr(settings, "CURVE_PRD_DELIVERY_ENABLED", False) is True
        and getattr(settings, "CURVE_PRD_COMMANDS_ENABLED", False) is True
        and getattr(settings, "CURVE_PRD_COMPLETION_RUNTIME", None) is not None
    )


def _prepare(outbox):
    if not prd_delivery_enabled():
        raise PrdDispatchUnavailable
    with transaction.atomic():
        workspace = Workspace.objects.select_for_update().get(id=outbox.workspace_id)
        if not is_curve_enabled_for_workspace(workspace.slug):
            raise PrdDispatchUnavailable
        event = DomainEvent.objects.get(
            workspace_id=workspace.id,
            id=outbox.event_id,
            event_type="curve.operation.state_changed",
            aggregate_type="OPERATION",
        )
        event_contract(event.payload_schema, event.payload)
        if (
            event.payload["workspace_id"] != str(workspace.id)
            or event.payload["operation_id"] != str(event.aggregate_id)
            or event.payload["operation_version"] != event.aggregate_version
        ):
            raise PrdDispatchUnavailable
        runtime = settings.CURVE_PRD_COMPLETION_RUNTIME
        _worker_grant(runtime, workspace.id, event.aggregate_id)
        record = PrdAcceptedCommand.objects.find_by_id(workspace_id=workspace.id, record_id=event.aggregate_id)
        operation = Operation.objects.select_for_update().get(workspace_id=workspace.id, id=event.aggregate_id)
        if (
            record is None
            or operation.command_type != "PRD_" + record.action.removeprefix("CURVE.PRD.")
            or operation.operation_type != "WORKFLOW_COMMAND"
            or operation.target
            != {
                "resource_type": "INITIATIVE",
                "resource_id": str(record.initiative_id),
                "resource_version": record.expected_version,
            }
        ):
            raise PrdDispatchUnavailable
        workflow_id = prd_workflow_id(workspace_id=str(workspace.id), operation_id=str(operation.id))
        if operation.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return "ACK", workflow_id, None
        if operation.status == "CANCEL_REQUESTED":
            return "SETTLE", workflow_id, (workspace.id, operation.id)
        if event.payload["status"] == "PENDING":
            if operation.status == "PENDING":
                operation = _transition(runtime, operation, "QUEUED", workflow_id=workflow_id)
            if operation.workflow_id != workflow_id:
                raise PrdDispatchUnavailable
            return (
                "START",
                workflow_id,
                OperationActivityInputV1(
                    schema_version="1.0",
                    workspace_id=str(workspace.id),
                    operation_id=str(operation.id),
                    operation_version=operation.aggregate_version,
                    correlation_id=operation.correlation_id,
                    command_id=f"prd-operation:{operation.id}",
                ),
            )
        if event.payload["status"] not in {"QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"}:
            raise PrdDispatchUnavailable
        return "ACK", workflow_id, None


async def relay_prd_workspace_once(*, client, workspace_id: uuid.UUID, worker_id: str):
    if not prd_delivery_enabled():
        return 0
    claimed = await asyncio.to_thread(
        claim_due_outbox,
        workspace_id=workspace_id,
        worker_id=worker_id,
        limit=10,
        lease_duration=OUTBOX_LEASE,
        destination=PRD_DESTINATION,
    )
    delivered = 0
    for outbox in claimed:
        try:
            action, workflow_id, value = await asyncio.to_thread(_prepare, outbox)
            if action == "START":
                try:
                    await client.start_workflow(
                        PRD_WORKFLOW_TYPE,
                        value,
                        id=workflow_id,
                        task_queue=TASK_QUEUE,
                        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                        rpc_timeout=timedelta(seconds=10),
                    )
                except WorkflowAlreadyStartedError:
                    description = await client.get_workflow_handle(workflow_id).describe(
                        rpc_timeout=timedelta(seconds=10)
                    )
                    if description.workflow_type != PRD_WORKFLOW_TYPE:
                        raise PrdDispatchUnavailable from None
            elif action == "SETTLE":
                await asyncio.to_thread(
                    complete_prd_operation, workspace_id=value[0], operation_id=value[1], execution_guard=lambda: False
                )
            await asyncio.to_thread(
                acknowledge_outbox, workspace_id=workspace_id, outbox_id=outbox.id, worker_id=worker_id
            )
            delivered += 1
        except Exception:
            try:
                arguments = dict(
                    workspace_id=workspace_id,
                    outbox_id=outbox.id,
                    worker_id=worker_id,
                    error={"code": "PRD_DISPATCH_UNAVAILABLE", "retryable": True},
                )
                if outbox.attempt_count >= 3:
                    await asyncio.to_thread(dead_letter_outbox, **arguments)
                else:
                    await asyncio.to_thread(retry_outbox, **arguments, next_attempt_at=timezone.now() + RETRY_DELAY)
            except Exception:
                # Retain the lease for existing expiry recovery. Exception bodies
                # from transport/runtime adapters never enter ordinary logs.
                pass
    await asyncio.to_thread(close_old_connections)
    return delivered
