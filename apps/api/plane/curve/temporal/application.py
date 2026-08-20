# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from plane.curve.models import InboxState, Operation, OperationStatus
from plane.curve.policy_services import transition_operation_with_service_authorization
from plane.curve.services import (
    IdempotencyConflict,
    InvalidOperationTransition,
    OptimisticConcurrencyError,
    canonical_json_bytes,
    complete_inbox_message,
    receive_inbox_message,
    sha256_digest,
)
from plane.curve.temporal.constants import APPLICATION_EVENT_DESTINATION, CONSUMER_ID
from plane.curve.temporal.contracts import OperationActivityInputV1, OperationActivityResultV1


class TemporalApplicationStateError(RuntimeError):
    pass


def _service_actor() -> dict[str, str]:
    actor_id = getattr(settings, "CURVE_POLICY_RECORDER_ACTOR_ID", "")
    if not actor_id:
        raise TemporalApplicationStateError("Curve worker identity is not configured")
    return {"actor_type": "SERVICE", "actor_id": actor_id}


def _service_authorization(workspace_id: uuid.UUID) -> dict:
    now = timezone.now()
    actor = _service_actor()
    return {
        "authorization_id": f"curve-local-temporal:{workspace_id}",
        "authorization_version": 1,
        "workspace_id": str(workspace_id),
        "service": actor,
        "active": True,
        "allowed_actions": ["CURVE.OPERATION.TRANSITION"],
        "issued_at": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
    }


def _activity_event_id(command_id: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"curve-temporal:{command_id}")


def _result(operation: Operation, *, effect_applied: bool) -> OperationActivityResultV1:
    result_digest = sha256_digest(
        canonical_json_bytes(
            {
                "operation_id": str(operation.id),
                "operation_status": operation.status,
                "operation_version": operation.aggregate_version,
            }
        )
    )
    return OperationActivityResultV1(
        schema_version="1.0",
        operation_status=operation.status,
        operation_version=operation.aggregate_version,
        effect_applied=effect_applied,
        result_digest=result_digest,
    )


def _load_operation(activity_input: OperationActivityInputV1) -> Operation:
    operation = Operation.objects.filter(
        workspace_id=uuid.UUID(activity_input.workspace_id),
        id=uuid.UUID(activity_input.operation_id),
    ).first()
    if operation is None:
        raise TemporalApplicationStateError("Curve Operation is unavailable")
    return operation


def _transition(
    *,
    activity_input: OperationActivityInputV1,
    operation: Operation,
    desired_status: str,
) -> Operation:
    workspace_id = uuid.UUID(activity_input.workspace_id)
    try:
        return transition_operation_with_service_authorization(
            workspace_id=workspace_id,
            operation_id=operation.id,
            expected_version=operation.aggregate_version,
            status=desired_status,
            service_actor=_service_actor(),
            service_authorization=_service_authorization(workspace_id),
            correlation_id=activity_input.correlation_id,
            causation_id=activity_input.command_id,
            progress_percent=100 if desired_status == OperationStatus.SUCCEEDED else None,
            destination=APPLICATION_EVENT_DESTINATION,
        )
    except (OptimisticConcurrencyError, InvalidOperationTransition):
        refreshed = _load_operation(activity_input)
        if refreshed.status == desired_status or refreshed.status in {
            OperationStatus.CANCEL_REQUESTED,
            OperationStatus.CANCELLED,
            OperationStatus.SUCCEEDED,
        }:
            return refreshed
        raise


def execute_transition_activity(
    activity_input: OperationActivityInputV1,
    *,
    desired_status: str,
) -> OperationActivityResultV1:
    workspace_id = uuid.UUID(activity_input.workspace_id)
    event_id = _activity_event_id(activity_input.command_id)
    inbox, created = receive_inbox_message(
        workspace_id=workspace_id,
        consumer_id=CONSUMER_ID,
        event_id=event_id,
    )
    operation = _load_operation(activity_input)
    if not created and inbox.state == InboxState.PROCESSED:
        result = _result(operation, effect_applied=False)
        if result.result_digest != inbox.result_digest:
            raise IdempotencyConflict
        return result

    effect_applied = False
    if desired_status == OperationStatus.RUNNING:
        if operation.status == OperationStatus.QUEUED:
            operation = _transition(
                activity_input=activity_input,
                operation=operation,
                desired_status=OperationStatus.RUNNING,
            )
            effect_applied = True
        elif operation.status not in {
            OperationStatus.RUNNING,
            OperationStatus.CANCEL_REQUESTED,
            OperationStatus.CANCELLED,
            OperationStatus.SUCCEEDED,
        }:
            raise TemporalApplicationStateError("Operation cannot enter RUNNING")
    elif desired_status == OperationStatus.SUCCEEDED:
        if operation.status == OperationStatus.RUNNING:
            operation = _transition(
                activity_input=activity_input,
                operation=operation,
                desired_status=OperationStatus.SUCCEEDED,
            )
            effect_applied = True
        elif operation.status not in {
            OperationStatus.SUCCEEDED,
            OperationStatus.CANCEL_REQUESTED,
            OperationStatus.CANCELLED,
        }:
            raise TemporalApplicationStateError("Operation cannot enter SUCCEEDED")
    elif desired_status == OperationStatus.CANCELLED:
        if operation.status in {OperationStatus.PENDING, OperationStatus.QUEUED, OperationStatus.RUNNING}:
            operation = _transition(
                activity_input=activity_input,
                operation=operation,
                desired_status=OperationStatus.CANCEL_REQUESTED,
            )
            effect_applied = True
        if operation.status == OperationStatus.CANCEL_REQUESTED:
            operation = _transition(
                activity_input=activity_input,
                operation=operation,
                desired_status=OperationStatus.CANCELLED,
            )
            effect_applied = True
        elif operation.status != OperationStatus.CANCELLED:
            raise TemporalApplicationStateError("Operation cannot enter CANCELLED")
    else:
        raise TemporalApplicationStateError("unsupported activity transition")

    result = _result(operation, effect_applied=effect_applied)
    complete_inbox_message(
        workspace_id=workspace_id,
        consumer_id=CONSUMER_ID,
        event_id=event_id,
        result_digest=result.result_digest,
    )
    return result
