# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from threading import Event

from django.conf import settings
from django.db import close_old_connections
from temporalio import activity
from temporalio.exceptions import ApplicationError

from plane.curve.prd_completion import complete_prd_operation
from plane.curve.models import Operation
from plane.curve.services import canonical_json_bytes, sha256_digest
from .contracts import OperationActivityInputV1, OperationActivityResultV1
from .prd_contracts import PRD_COMPLETE_ACTIVITY, PRD_SETTLE_ACTIVITY, PRD_WORKFLOW_TYPE, prd_workflow_id


def _invoke(request, guard):
    close_old_connections()
    try:
        if getattr(settings, "CURVE_PRD_DELIVERY_ENABLED", False) is not True:
            raise RuntimeError
        if not Operation.objects.filter(
            workspace_id=request.workspace_id,
            id=request.operation_id,
            workflow_id=prd_workflow_id(workspace_id=request.workspace_id, operation_id=request.operation_id),
        ).exists():
            raise RuntimeError
        result = complete_prd_operation(
            workspace_id=request.workspace_id, operation_id=request.operation_id, execution_guard=guard
        )
        if result["status"] not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            raise RuntimeError
        return OperationActivityResultV1(
            schema_version="1.0",
            operation_status=result["status"],
            operation_version=result["version"],
            effect_applied=result["effect_applied"],
            result_digest=sha256_digest(
                canonical_json_bytes({key: result[key] for key in ("operation_id", "status", "version")})
            ),
        )
    except Exception:
        raise ApplicationError("PRD activity is unavailable", type="PRD_ACTIVITY_UNAVAILABLE") from None
    finally:
        close_old_connections()


def _activity_scope(request):
    info = activity.info()
    if (
        type(request) is not OperationActivityInputV1
        or info.workflow_type != PRD_WORKFLOW_TYPE
        or info.workflow_id != prd_workflow_id(workspace_id=request.workspace_id, operation_id=request.operation_id)
    ):
        raise ApplicationError("PRD activity scope is invalid", type="PRD_ACTIVITY_SCOPE_INVALID", non_retryable=True)
    return info


@activity.defn(name=PRD_COMPLETE_ACTIVITY)
async def complete_prd_activity(request: OperationActivityInputV1) -> OperationActivityResultV1:
    info = _activity_scope(request)
    deadlines = []
    if info.start_to_close_timeout:
        deadlines.append(info.started_time + info.start_to_close_timeout)
    if info.schedule_to_close_timeout:
        deadlines.append(info.scheduled_time + info.schedule_to_close_timeout)
    if not deadlines:
        raise ApplicationError(
            "PRD activity deadline is missing", type="PRD_ACTIVITY_SCOPE_INVALID", non_retryable=True
        )
    deadline = min(deadlines)
    stopped = Event()

    def guard():
        return not stopped.is_set() and not activity.is_cancelled() and datetime.now(timezone.utc) < deadline

    async def heartbeat():
        try:
            while True:
                activity.heartbeat()
                await asyncio.sleep(5)
        except Exception:
            stopped.set()

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        # to_thread carries the activity ContextVars into the guarded DB/provider
        # application service. Task cancellation cannot bypass the final fence.
        return await asyncio.to_thread(_invoke, request, guard)
    finally:
        stopped.set()
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task


@activity.defn(name=PRD_SETTLE_ACTIVITY)
async def settle_prd_activity(request: OperationActivityInputV1) -> OperationActivityResultV1:
    _activity_scope(request)
    return await asyncio.to_thread(_invoke, request, lambda: False)
