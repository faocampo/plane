# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from temporalio import activity
from temporalio.exceptions import ApplicationError

from plane.curve.models import OperationStatus
from plane.curve.temporal.application import TemporalApplicationStateError, execute_transition_activity
from plane.curve.temporal.constants import (
    MARK_CANCELLED_ACTIVITY,
    MARK_RUNNING_ACTIVITY,
    MARK_SUCCEEDED_ACTIVITY,
)
from plane.curve.temporal.contracts import OperationActivityInputV1, OperationActivityResultV1


def _execute(
    activity_input: OperationActivityInputV1,
    *,
    desired_status: str,
) -> OperationActivityResultV1:
    try:
        return execute_transition_activity(activity_input, desired_status=desired_status)
    except (TemporalApplicationStateError, ValueError) as error:
        raise ApplicationError(
            "Curve activity rejected authoritative state",
            type="CURVE_ACTIVITY_STATE_REJECTED",
            non_retryable=True,
        ) from error


@activity.defn(name=MARK_RUNNING_ACTIVITY)
def mark_operation_running(activity_input: OperationActivityInputV1) -> OperationActivityResultV1:
    return _execute(activity_input, desired_status=OperationStatus.RUNNING)


@activity.defn(name=MARK_SUCCEEDED_ACTIVITY)
def mark_operation_succeeded(activity_input: OperationActivityInputV1) -> OperationActivityResultV1:
    return _execute(activity_input, desired_status=OperationStatus.SUCCEEDED)


@activity.defn(name=MARK_CANCELLED_ACTIVITY)
def mark_operation_cancelled(activity_input: OperationActivityInputV1) -> OperationActivityResultV1:
    return _execute(activity_input, desired_status=OperationStatus.CANCELLED)
