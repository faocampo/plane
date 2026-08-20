# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

WORKFLOW_TYPE = "CurveOperationWorkflowV1"
WORKFLOW_PATCH_ID = "curve-operation-workflow-v1-initial"
WORKFLOW_RESTART_WINDOW_PATCH_ID = "curve-operation-restart-window-v1"
TASK_QUEUE = "curve-control-plane-v1"
NAMESPACE = "curve-local"
TEMPORAL_DESTINATION = "CURVE_TEMPORAL_OPERATION_V1"
APPLICATION_EVENT_DESTINATION = "CURVE_LOCAL"
CONSUMER_ID = "CURVE_TEMPORAL_ACTIVITY_V1"

MARK_RUNNING_ACTIVITY = "curve.mark_operation_running.v1"
MARK_SUCCEEDED_ACTIVITY = "curve.mark_operation_succeeded.v1"
MARK_CANCELLED_ACTIVITY = "curve.mark_operation_cancelled.v1"


def operation_workflow_id(*, workspace_id: str, operation_id: str) -> str:
    return f"curve:{workspace_id}:{operation_id}"
