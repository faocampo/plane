# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

WORKFLOW_TYPE = "CurveOperationWorkflowV1"
WORKFLOW_PATCH_ID = "curve-operation-workflow-v1-initial"
WORKFLOW_RESTART_WINDOW_PATCH_ID = "curve-operation-restart-window-v1"
PARENT_ORCHESTRATION_WORKFLOW_TYPE = "CurveInitiativeOrchestrationWorkflowV1"
CHILD_ATTEMPT_WORKFLOW_TYPE = "CurveSliceAttemptWorkflowV1"
PARENT_ORCHESTRATION_PATCH_ID = "curve-m0-s6a-parent-v1"
CHILD_ATTEMPT_PATCH_ID = "curve-m0-s6a-child-v1"
TASK_QUEUE = "curve-control-plane-v1"
NAMESPACE = "curve-local"
TEMPORAL_DESTINATION = "CURVE_TEMPORAL_OPERATION_V1"
APPLICATION_EVENT_DESTINATION = "CURVE_LOCAL"
CONSUMER_ID = "CURVE_TEMPORAL_ACTIVITY_V1"

MARK_RUNNING_ACTIVITY = "curve.mark_operation_running.v1"
MARK_SUCCEEDED_ACTIVITY = "curve.mark_operation_succeeded.v1"
MARK_CANCELLED_ACTIVITY = "curve.mark_operation_cancelled.v1"

CHILD_START_SIGNAL_TIMEOUT_SECONDS = 30
ATTEMPT_TERMINAL_TIMEOUT_SECONDS = 7200
QUESTION_ANSWER_TIMEOUT_SECONDS = 86400
PARENT_CANCEL_TIMEOUT_SECONDS = 120
CONTINUE_AS_NEW_WAVE_THRESHOLD = 10


def operation_workflow_id(*, workspace_id: str, operation_id: str) -> str:
    return f"curve:{workspace_id}:{operation_id}"


def initiative_workflow_id(*, workspace_id: str, initiative_id: str, plan_generation: int) -> str:
    return f"curve:{workspace_id}:initiative:{initiative_id}:plan:{plan_generation}"


def slice_attempt_workflow_id(
    *,
    workspace_id: str,
    initiative_id: str,
    plan_generation: int,
    slice_id: str,
    attempt_id: str,
) -> str:
    return (
        f"curve:{workspace_id}:initiative:{initiative_id}:plan:{plan_generation}:slice:{slice_id}:attempt:{attempt_id}"
    )
