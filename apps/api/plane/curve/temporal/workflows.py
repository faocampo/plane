# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from plane.curve.temporal.constants import (
    MARK_CANCELLED_ACTIVITY,
    MARK_RUNNING_ACTIVITY,
    MARK_SUCCEEDED_ACTIVITY,
    WORKFLOW_PATCH_ID,
    WORKFLOW_RESTART_WINDOW_PATCH_ID,
)
from plane.curve.temporal.contracts import (
    CancelSignalV1,
    CurveOperationWorkflowInputV1,
    OperationActivityInputV1,
    OperationActivityResultV1,
    RefreshOperationSignalV1,
    WorkflowResultV1,
    WorkflowStateV1,
)


ACTIVITY_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=5),
    maximum_attempts=3,
)


@workflow.defn(name="CurveOperationWorkflowV1")
class CurveOperationWorkflowV1:
    def __init__(self) -> None:
        self._phase = "INITIALIZING"
        self._last_observed_operation_version = 1
        self._cancellation_requested = False
        self._cancel_command_ids: set[str] = set()

    def _activity_input(
        self,
        workflow_input: CurveOperationWorkflowInputV1,
        *,
        activity_name: str,
        logical_command: str,
    ) -> OperationActivityInputV1:
        workflow_info = workflow.info()
        return OperationActivityInputV1(
            schema_version="1.0",
            workspace_id=workflow_input.workspace_id,
            operation_id=workflow_input.operation_id,
            operation_version=self._last_observed_operation_version,
            correlation_id=workflow_input.correlation_id,
            command_id=(
                f"{workflow_info.workflow_id}:{workflow_info.run_id}:"
                f"{activity_name}:{logical_command}"
            ),
        )

    async def _execute(
        self,
        activity_name: str,
        activity_input: OperationActivityInputV1,
    ) -> OperationActivityResultV1:
        result = await workflow.execute_activity(
            activity_name,
            activity_input,
            result_type=OperationActivityResultV1,
            start_to_close_timeout=timedelta(seconds=30),
            schedule_to_close_timeout=timedelta(minutes=2),
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
        self._last_observed_operation_version = max(
            self._last_observed_operation_version,
            result.operation_version,
        )
        self._phase = result.operation_status
        return result

    @workflow.run
    async def run(self, workflow_input: CurveOperationWorkflowInputV1) -> WorkflowResultV1:
        if not workflow.patched(WORKFLOW_PATCH_ID):
            raise RuntimeError("CurveOperationWorkflowV1 initial patch is inactive")
        self._phase = "QUEUED"
        self._last_observed_operation_version = workflow_input.operation_version

        if not self._cancellation_requested:
            running = await self._execute(
                MARK_RUNNING_ACTIVITY,
                self._activity_input(
                    workflow_input,
                    activity_name=MARK_RUNNING_ACTIVITY,
                    logical_command="mark-running-v1",
                ),
            )
            if running.operation_status in {
                "CANCEL_REQUESTED",
                "CANCELLED",
            }:
                self._cancellation_requested = True

        # New executions use a bounded local-proof window long enough to
        # exercise worker restart and cancellation. Histories created before
        # this patch retain the original one-second timer during replay.
        restart_window = 5 if workflow.patched(WORKFLOW_RESTART_WINDOW_PATCH_ID) else 1
        await workflow.sleep(timedelta(seconds=restart_window))

        if self._cancellation_requested:
            terminal = await self._execute(
                MARK_CANCELLED_ACTIVITY,
                self._activity_input(
                    workflow_input,
                    activity_name=MARK_CANCELLED_ACTIVITY,
                    logical_command="mark-cancelled-v1",
                ),
            )
        else:
            terminal = await self._execute(
                MARK_SUCCEEDED_ACTIVITY,
                self._activity_input(
                    workflow_input,
                    activity_name=MARK_SUCCEEDED_ACTIVITY,
                    logical_command="mark-succeeded-v1",
                ),
            )
            if terminal.operation_status == "CANCEL_REQUESTED":
                self._cancellation_requested = True
                terminal = await self._execute(
                    MARK_CANCELLED_ACTIVITY,
                    self._activity_input(
                        workflow_input,
                        activity_name=MARK_CANCELLED_ACTIVITY,
                        logical_command="mark-cancelled-v1",
                    ),
                )

        return WorkflowResultV1(
            schema_version="1.0",
            operation_status=terminal.operation_status,
            operation_version=terminal.operation_version,
            result_digest=terminal.result_digest,
        )

    @workflow.signal(name="request_cancel")
    def request_cancel(self, command: CancelSignalV1) -> None:
        if command.command_id in self._cancel_command_ids:
            return
        self._cancel_command_ids.add(command.command_id)
        self._cancellation_requested = True

    @workflow.signal(name="refresh_operation")
    def refresh_operation(self, command: RefreshOperationSignalV1) -> None:
        self._last_observed_operation_version = max(
            self._last_observed_operation_version,
            command.operation_version,
        )

    @workflow.query(name="state")
    def state(self) -> WorkflowStateV1:
        return WorkflowStateV1(
            schema_version="1.0",
            phase=self._phase,
            last_observed_operation_version=self._last_observed_operation_version,
            cancellation_requested=self._cancellation_requested,
        )
