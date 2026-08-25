# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from plane.curve.temporal.orchestration_workflows import (
    CurveInitiativeOrchestrationWorkflowV1,
    CurveSliceAttemptWorkflowV1,
)
from plane.curve.temporal.workflows import CurveOperationWorkflowV1


CURVE_WORKFLOWS_V1 = (
    CurveOperationWorkflowV1,
    CurveInitiativeOrchestrationWorkflowV1,
    CurveSliceAttemptWorkflowV1,
)

CURVE_WORKFLOW_TYPE_NAMES_V1 = tuple(
    workflow_type.__temporal_workflow_definition.name for workflow_type in CURVE_WORKFLOWS_V1
)
