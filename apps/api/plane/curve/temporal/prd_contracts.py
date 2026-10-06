# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Additive PRD transport identity; existing v1 workflow contracts stay intact."""

PRD_WORKFLOW_TYPE = "CurvePrdOperationWorkflowV1"
PRD_COMPLETE_ACTIVITY = "curve.prd.complete.v1"
PRD_SETTLE_ACTIVITY = "curve.prd.settle.v1"
PRD_DESTINATION = "CURVE_PRD_CANDIDATE_V1"


def prd_workflow_id(*, workspace_id, operation_id):
    return f"curve:{workspace_id}:{operation_id}"
