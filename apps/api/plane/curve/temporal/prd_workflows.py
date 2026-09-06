# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from .contracts import OperationActivityInputV1, OperationActivityResultV1, CancelSignalV1
from .prd_contracts import PRD_WORKFLOW_TYPE, PRD_COMPLETE_ACTIVITY, PRD_SETTLE_ACTIVITY


@workflow.defn(name=PRD_WORKFLOW_TYPE)
class CurvePrdOperationWorkflowV1:
    @workflow.run
    async def run(self, request: OperationActivityInputV1) -> OperationActivityResultV1:
        try:
            return await workflow.execute_activity(
                PRD_COMPLETE_ACTIVITY,
                request,
                result_type=OperationActivityResultV1,
                start_to_close_timeout=timedelta(minutes=2),
                schedule_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=timedelta(seconds=20),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), maximum_attempts=3),
            )
        except ActivityError:
            # A lost/timed-out completion must settle under fresh worker authority.
            # This activity cannot apply a PRD effect or retrieve protected bodies.
            return await workflow.execute_activity(
                PRD_SETTLE_ACTIVITY,
                request,
                result_type=OperationActivityResultV1,
                start_to_close_timeout=timedelta(seconds=30),
                schedule_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), maximum_attempts=3),
            )

    @workflow.signal(name="request_cancel")
    def request_cancel(self, command: CancelSignalV1):
        # Notification only: the authorized API has already persisted cancellation.
        # Neither this signal nor its caller-supplied fields grants cancellation.
        # The running activity rechecks the authoritative Operation before commit.
        pass
