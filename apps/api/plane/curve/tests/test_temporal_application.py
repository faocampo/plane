# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import asyncio
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from plane.curve.models import (
    DomainEvent,
    InboxMessage,
    InboxState,
    Operation,
    OperationStatus,
    OutboxEvent,
    OutboxState,
)
from plane.curve.policy_services import (
    start_foundation_probe,
    transition_operation_with_service_authorization,
)
from plane.curve.services import claim_due_outbox, receive_inbox_message
from plane.curve.temporal.application import (
    _activity_event_id,
    _service_actor,
    _service_authorization,
    execute_transition_activity,
)
from plane.curve.temporal.constants import (
    APPLICATION_EVENT_DESTINATION,
    CONSUMER_ID,
    TEMPORAL_DESTINATION,
    operation_workflow_id,
)
from plane.curve.temporal.control import _record_cancellation_request, request_cancellation
from plane.curve.temporal.contracts import OperationActivityInputV1
from plane.curve.temporal.relay import _prepare_dispatch, relay_workspace_once
from plane.db.models import User, Workspace, WorkspaceMember
from django.utils import timezone


pytestmark = [pytest.mark.unit, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def _curve_temporal_settings(settings):
    settings.CURVE_ENABLED = True
    settings.CURVE_ENABLED_WORKSPACE_SLUGS = frozenset({"curve-local-proof"})
    settings.CURVE_ENVIRONMENT = "LOCAL"
    settings.CURVE_POLICY_RECORDER_ACTOR_ID = "curve-worker-test"


def _workspace_request() -> tuple[Workspace, SimpleNamespace]:
    user = User.objects.create(
        email=f"curve-temporal-{uuid.uuid4()}@example.com",
        username=f"curve-temporal-{uuid.uuid4()}@example.com",
    )
    workspace = Workspace.objects.create(
        name="Curve local proof",
        slug="curve-local-proof",
        owner=user,
    )
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=20, is_active=True)
    return workspace, SimpleNamespace(user=user)


def _create_temporal_operation() -> tuple[Workspace, Operation]:
    workspace, request = _workspace_request()
    result = start_foundation_probe(
        request=request,
        workspace_slug=workspace.slug,
        raw_idempotency_key=f"curve-temporal-{uuid.uuid4()}",
        canonical_request=b'{"fixture":"synthetic"}',
        destination=TEMPORAL_DESTINATION,
    )
    return workspace, result.operation


def _transition(operation: Operation, status: str, *, workflow_id: str | None = None) -> Operation:
    return transition_operation_with_service_authorization(
        workspace_id=operation.workspace_id,
        operation_id=operation.id,
        expected_version=operation.aggregate_version,
        status=status,
        service_actor=_service_actor(),
        service_authorization=_service_authorization(operation.workspace_id),
        correlation_id=operation.correlation_id,
        destination=APPLICATION_EVENT_DESTINATION,
        workflow_id=workflow_id,
    )


def _activity_input(operation: Operation, logical_command: str) -> OperationActivityInputV1:
    return OperationActivityInputV1(
        schema_version="1.0",
        workspace_id=str(operation.workspace_id),
        operation_id=str(operation.id),
        operation_version=operation.aggregate_version,
        correlation_id=operation.correlation_id,
        command_id=f"{operation.id}:{logical_command}",
    )


def test_outbox_claim_filters_temporal_destination_and_binds_workflow_id():
    workspace, operation = _create_temporal_operation()
    workflow_id = operation_workflow_id(workspace_id=str(workspace.id), operation_id=str(operation.id))
    operation = _transition(operation, OperationStatus.QUEUED, workflow_id=workflow_id)

    claimed = claim_due_outbox(
        workspace_id=workspace.id,
        worker_id="curve-worker-test",
        limit=10,
        lease_duration=timedelta(seconds=30),
        destination=TEMPORAL_DESTINATION,
    )

    assert len(claimed) == 1
    assert operation.workflow_id == workflow_id
    assert OutboxEvent.objects.filter(workspace_id=workspace.id, destination=APPLICATION_EVENT_DESTINATION).count() == 1


def test_duplicate_activity_delivery_records_one_running_effect():
    _, operation = _create_temporal_operation()
    workflow_id = operation_workflow_id(
        workspace_id=str(operation.workspace_id),
        operation_id=str(operation.id),
    )
    operation = _transition(operation, OperationStatus.QUEUED, workflow_id=workflow_id)
    activity_input = _activity_input(operation, "mark-running-v1")

    first = execute_transition_activity(activity_input, desired_status=OperationStatus.RUNNING)
    duplicate = execute_transition_activity(activity_input, desired_status=OperationStatus.RUNNING)

    operation.refresh_from_db()
    assert first.effect_applied is True
    assert duplicate.effect_applied is False
    assert operation.status == OperationStatus.RUNNING
    assert operation.aggregate_version == 3
    assert InboxMessage.objects.filter(workspace_id=operation.workspace_id, state=InboxState.PROCESSED).count() == 1
    assert DomainEvent.objects.filter(workspace_id=operation.workspace_id, aggregate_id=operation.id).count() == 3


def test_retry_after_committed_effect_completes_inbox_without_duplicate_transition():
    _, operation = _create_temporal_operation()
    workflow_id = operation_workflow_id(
        workspace_id=str(operation.workspace_id),
        operation_id=str(operation.id),
    )
    operation = _transition(operation, OperationStatus.QUEUED, workflow_id=workflow_id)
    operation = _transition(operation, OperationStatus.RUNNING)
    activity_input = _activity_input(operation, "mark-succeeded-v1")
    event_id = _activity_event_id(activity_input.command_id)
    receive_inbox_message(
        workspace_id=operation.workspace_id,
        consumer_id=CONSUMER_ID,
        event_id=event_id,
    )
    operation = _transition(operation, OperationStatus.SUCCEEDED)
    event_count = DomainEvent.objects.filter(workspace_id=operation.workspace_id, aggregate_id=operation.id).count()

    reconciled = execute_transition_activity(activity_input, desired_status=OperationStatus.SUCCEEDED)

    operation.refresh_from_db()
    inbox = InboxMessage.objects.get(workspace_id=operation.workspace_id, event_id=event_id)
    assert reconciled.effect_applied is False
    assert operation.status == OperationStatus.SUCCEEDED
    assert operation.aggregate_version == 4
    assert inbox.state == InboxState.PROCESSED
    assert inbox.result_digest == reconciled.result_digest
    assert (
        DomainEvent.objects.filter(workspace_id=operation.workspace_id, aggregate_id=operation.id).count()
        == event_count
    )


def test_cancellation_activity_reaches_terminal_cancelled_without_orphan_state():
    _, operation = _create_temporal_operation()
    workflow_id = operation_workflow_id(
        workspace_id=str(operation.workspace_id),
        operation_id=str(operation.id),
    )
    operation = _transition(operation, OperationStatus.QUEUED, workflow_id=workflow_id)
    operation = _transition(operation, OperationStatus.RUNNING)
    activity_input = _activity_input(operation, "mark-cancelled-v1")

    result = execute_transition_activity(activity_input, desired_status=OperationStatus.CANCELLED)

    operation.refresh_from_db()
    assert result.operation_status == OperationStatus.CANCELLED
    assert operation.status == OperationStatus.CANCELLED
    assert operation.completed_at is not None
    assert operation.aggregate_version == 5
    assert InboxMessage.objects.filter(workspace_id=operation.workspace_id, state=InboxState.PROCESSED).count() == 1


def test_relay_recovers_expired_claim_before_idempotent_start():
    workspace, operation = _create_temporal_operation()
    claimed_at = timezone.now() - timedelta(minutes=1)
    claimed = claim_due_outbox(
        workspace_id=workspace.id,
        worker_id="crashed-worker",
        limit=1,
        lease_duration=timedelta(seconds=10),
        now=claimed_at,
        destination=TEMPORAL_DESTINATION,
    )
    assert len(claimed) == 1
    client = SimpleNamespace(start_workflow=AsyncMock())

    delivered = asyncio.run(
        relay_workspace_once(
            client=client,
            workspace_id=workspace.id,
            worker_id="replacement-worker",
        )
    )

    operation.refresh_from_db()
    claimed[0].refresh_from_db()
    assert delivered == 1
    assert operation.status == OperationStatus.QUEUED
    assert claimed[0].state == OutboxState.DELIVERED
    client.start_workflow.assert_awaited_once()


def test_cancel_request_commits_reconcilable_temporal_signal_event():
    _, operation = _create_temporal_operation()
    workflow_id = operation_workflow_id(
        workspace_id=str(operation.workspace_id),
        operation_id=str(operation.id),
    )
    operation = _transition(operation, OperationStatus.QUEUED, workflow_id=workflow_id)
    operation = _transition(operation, OperationStatus.RUNNING)

    recorded_workflow_id = _record_cancellation_request(
        workspace_id=operation.workspace_id,
        operation_id=operation.id,
        correlation_id=operation.correlation_id,
        command_id=f"cancel:{operation.id}",
    )
    event = DomainEvent.objects.get(
        workspace_id=operation.workspace_id,
        aggregate_id=operation.id,
        payload__status=OperationStatus.CANCEL_REQUESTED,
    )
    dispatch = _prepare_dispatch(workspace_id=operation.workspace_id, event_id=event.id)

    assert recorded_workflow_id == workflow_id
    assert dispatch.action == "CANCEL"
    assert dispatch.workflow_id == workflow_id
    assert dispatch.cancel_signal.reason_code == "STATE_RECONCILIATION"
    assert OutboxEvent.objects.filter(
        workspace_id=operation.workspace_id,
        event_id=event.id,
        destination=TEMPORAL_DESTINATION,
    ).exists()


def test_invalid_cancel_signal_is_rejected_before_state_mutation():
    _, operation = _create_temporal_operation()
    workflow_id = operation_workflow_id(
        workspace_id=str(operation.workspace_id),
        operation_id=str(operation.id),
    )
    operation = _transition(operation, OperationStatus.QUEUED, workflow_id=workflow_id)
    operation = _transition(operation, OperationStatus.RUNNING)
    client = SimpleNamespace(get_workflow_handle=AsyncMock())

    with pytest.raises(ValueError, match="invalid command_id"):
        asyncio.run(
            request_cancellation(
                client=client,
                workspace_id=operation.workspace_id,
                operation_id=operation.id,
                actor_ref="developer:federico",
                reason_code="USER_REQUESTED",
                command_id="contains spaces",
                correlation_id=operation.correlation_id,
            )
        )

    operation.refresh_from_db()
    assert operation.status == OperationStatus.RUNNING
