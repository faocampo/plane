# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Real PostgreSQL transport state with a deterministic fake Temporal client.

ActivityEnvironment runs the local activity callable without a Temporal server.
These tests do not qualify a provider, execute server workflow-history replay,
activate the runtime, or alter the existing v1 activity input contract.
"""

import asyncio
from dataclasses import asdict, fields, replace
from datetime import timedelta
from types import SimpleNamespace
import uuid

import pytest
from django.db import close_old_connections
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.testing import ActivityEnvironment

from plane.curve.models import AuditEvent, DocumentCheckpoint, DomainEvent, Operation, OutboxEvent, PrdReviewDecision
from plane.curve.scoped_prd_completion import complete_scoped_prd_operation
from plane.curve.scoped_prd_contracts import SCHEMA_VERSION
from plane.curve.scoped_prd_models import ScopedPrdAcceptedCommand, ScopedPrdDecision, ScopedPrdSubject
from plane.curve.temporal.contracts import OperationActivityInputV1, OperationActivityResultV1
from plane.curve.temporal.scoped_prd_activities import complete_scoped_prd_activity, settle_scoped_prd_activity
from plane.curve.temporal.scoped_prd_contracts import (
    PRD_COMPLETE_ACTIVITY,
    PRD_DESTINATION,
    PRD_SETTLE_ACTIVITY,
    PRD_WORKFLOW_TYPE,
    prd_workflow_id,
)
from plane.curve.temporal.scoped_prd_relay import relay_scoped_prd_workspace_once
from plane.curve.temporal.scoped_prd_workflows import CurveScopedPrdOperationWorkflowV1
from plane.curve.views import operation_etag
from plane.curve.tests.test_prd_completion import SyntheticCompletionRuntime
from plane.curve.tests.test_prd_temporal import FakeClient as LegacyFakeClient
from plane.curve.tests.test_scoped_prd_bridge import (  # noqa: F401
    bridge as bridge_fixture,
    context,
    configuration,
    submission,
    accept,
    complete,
    submit,
    review_command,
)

bridge = bridge_fixture

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def delivery(settings):
    settings.CURVE_SCOPED_PRD_DELIVERY_ENABLED = True


class FakeClient(LegacyFakeClient):
    async def describe(self, **kwargs):
        return SimpleNamespace(workflow_type=PRD_WORKFLOW_TYPE)


def outboxes(bridge):
    return OutboxEvent.objects.filter(workspace_id=bridge.workspace.id, destination=PRD_DESTINATION)


def drain(bridge, client):
    return asyncio.run(
        relay_scoped_prd_workspace_once(
            client=client, workspace_id=bridge.workspace.id, worker_id="synthetic-scoped-prd-relay"
        )
    )


def make_due(bridge):
    outboxes(bridge).update(next_attempt_at=timezone.now())


def cancel(bridge, operation):
    operation.refresh_from_db()
    client = APIClient()
    client.force_authenticate(user=bridge.user)
    response = client.post(
        reverse("curve-operation-cancel", kwargs={"slug": bridge.workspace.slug, "resource_id": operation.id}),
        data={},
        format="json",
        HTTP_IDEMPOTENCY_KEY="synthetic-scoped-cancel-" + str(operation.id),
        HTTP_IF_MATCH=operation_etag(operation_id=str(operation.id), version=operation.aggregate_version),
    )
    assert response.status_code == 202, response.data


def activity_input(bridge, operation):
    operation.refresh_from_db()
    return OperationActivityInputV1(
        schema_version="1.0",
        workspace_id=str(bridge.workspace.id),
        operation_id=str(operation.id),
        operation_version=operation.aggregate_version,
        correlation_id=operation.correlation_id,
        command_id=f"prd-operation:{operation.id}",
    )


def environment(request, **changes):
    result = ActivityEnvironment()
    result.info = replace(
        result.info,
        workflow_id=prd_workflow_id(workspace_id=request.workspace_id, operation_id=request.operation_id),
        workflow_type=PRD_WORKFLOW_TYPE,
        started_time=timezone.now(),
        scheduled_time=timezone.now(),
        start_to_close_timeout=timedelta(minutes=2),
        schedule_to_close_timeout=timedelta(minutes=5),
    )
    result.info = replace(result.info, **changes)
    return result


@pytest.mark.parametrize(
    "flag,value",
    [
        ("CURVE_SCOPED_PRD_DELIVERY_ENABLED", False),
        ("CURVE_SCOPED_PRD_DELIVERY_ENABLED", "true"),
        ("CURVE_PRD_COMMANDS_ENABLED", False),
        ("CURVE_SCOPED_PRD_COMMANDS_ENABLED", False),
        ("CURVE_ENVIRONMENT", "STAGING"),
        ("CURVE_ENVIRONMENT", "PRODUCTION"),
        ("CURVE_PRD_COMPLETION_RUNTIME", None),
    ],
)
def test_disabled_scoped_delivery_does_not_claim_or_prepare(bridge, settings, flag, value):
    operation = accept(bridge, submission(bridge)).operation
    setattr(settings, flag, value)
    before = list(outboxes(bridge).values())
    client = FakeClient()
    assert drain(bridge, client) == 0 and client.calls == []
    assert list(outboxes(bridge).values()) == before
    operation.refresh_from_db()
    assert operation.status == "PENDING" and bridge.runtime.preparations == 0


def test_scoped_transport_uses_explicit_edition_and_unchanged_scalar_input(bridge):
    operation = accept(bridge, submission(bridge)).operation
    accepted = ScopedPrdAcceptedCommand.objects.get(operation_id=operation.id)
    assert accepted.edition == SCHEMA_VERSION
    assert operation.command_type == "SCOPED_PRD_V1_SUBMIT"
    other_destinations = list(OutboxEvent.objects.exclude(destination=PRD_DESTINATION).values())
    client = FakeClient()
    assert drain(bridge, client) == 1
    assert len(client.calls) == 1
    kind, request, options = client.calls[0]
    assert kind == PRD_WORKFLOW_TYPE == "CurveScopedPrdOperationWorkflowV1"
    assert type(request) is OperationActivityInputV1
    assert {field.name for field in fields(request)} == {
        "schema_version",
        "workspace_id",
        "operation_id",
        "operation_version",
        "correlation_id",
        "command_id",
    }
    assert request.schema_version == "1.0"
    assert request.workspace_id == str(bridge.workspace.id) and request.operation_id == str(operation.id)
    assert options["id"] == f"curve-scoped-prd-v1:{bridge.workspace.id}:{operation.id}"
    assert "sentinel" not in repr(asdict(request)) and "rationale" not in repr(asdict(request))
    assert list(OutboxEvent.objects.exclude(destination=PRD_DESTINATION).values()) == other_destinations
    operation.refresh_from_db()
    assert operation.status == "QUEUED" and operation.workflow_id == options["id"]
    assert bridge.runtime.preparations == 0


def test_ambiguous_start_retries_same_id_and_acknowledges_existing_scoped_workflow(bridge, caplog):
    operation = accept(bridge, submission(bridge)).operation
    client = FakeClient("ambiguous")
    assert drain(bridge, client) == 0
    operation.refresh_from_db()
    assert operation.status == "QUEUED"
    make_due(bridge)
    assert drain(bridge, client) >= 1
    assert len(client.calls) == 2 and client.calls[0][2]["id"] == client.calls[1][2]["id"]
    assert operation.workflow_id == prd_workflow_id(
        workspace_id=str(bridge.workspace.id), operation_id=str(operation.id)
    )
    assert not outboxes(bridge).exclude(state="DELIVERED").exists()
    assert "sentinel" not in caplog.text


def test_wrong_existing_workflow_type_is_never_acknowledged(bridge):
    accept(bridge, submission(bridge))
    # The legacy fake deliberately reports the old PRD workflow type.
    client = LegacyFakeClient("ambiguous")
    drain(bridge, client)
    make_due(bridge)
    drain(bridge, client)
    assert outboxes(bridge).filter(state="RETRY_SCHEDULED", attempt_count=2).exists()


def test_cancel_before_dispatch_has_no_workflow_or_provider_effect(bridge):
    operation = accept(bridge, submission(bridge)).operation
    assert operation.workflow_id is None
    cancel(bridge, operation)
    cancellation = DomainEvent.objects.filter(aggregate_id=operation.id, payload__status="CANCEL_REQUESTED").get()
    assert OutboxEvent.objects.get(event_id=cancellation.id).destination == PRD_DESTINATION
    client = FakeClient()
    assert drain(bridge, client) >= 1
    operation.refresh_from_db()
    assert operation.status == "CANCELLED" and operation.result_ref is None
    assert client.calls == [] and bridge.runtime.preparations == 0
    assert not DocumentCheckpoint.objects.exists() and not ScopedPrdSubject.objects.exists()


def test_transport_failure_dead_letters_bounded_attempts_then_can_cancel(bridge, caplog):
    operation = accept(bridge, submission(bridge)).operation
    client = FakeClient("always")
    for _ in range(3):
        make_due(bridge)
        drain(bridge, client)
    dead = outboxes(bridge).get(state="DEAD_LETTER")
    assert dead.attempt_count == 3
    assert "sentinel" not in repr(dead.last_error) and "sentinel" not in caplog.text
    cancel(bridge, operation)
    assert drain(bridge, client) >= 1
    operation.refresh_from_db()
    assert operation.status == "CANCELLED" and operation.result_ref is None
    assert bridge.runtime.preparations == 0 and not DocumentCheckpoint.objects.exists()


@pytest.mark.parametrize("which", ["started", "scheduled"])
def test_expired_activity_guard_fails_safely_before_provider(bridge, which):
    operation = accept(bridge, submission(bridge)).operation
    drain(bridge, FakeClient())
    request = activity_input(bridge, operation)
    env = environment(request, **{which + "_time": timezone.now() - timedelta(minutes=10)})
    result = asyncio.run(env.run(complete_scoped_prd_activity, request))
    assert result.operation_status == "FAILED" and result.effect_applied is False
    assert bridge.runtime.preparations == 0 and not DocumentCheckpoint.objects.exists()


@pytest.mark.parametrize(
    "change", ["workflow_id", "workflow_type", "workspace", "operation", "input_type", "deadlines"]
)
def test_activity_identity_and_deadlines_cannot_be_substituted(bridge, change):
    operation = accept(bridge, submission(bridge)).operation
    drain(bridge, FakeClient())
    request = activity_input(bridge, operation)
    env = environment(request)
    if change == "workflow_id":
        env.info = replace(env.info, workflow_id="synthetic-wrong-workflow")
    elif change == "workflow_type":
        env.info = replace(env.info, workflow_type="CurvePrdOperationWorkflowV1")
    elif change == "workspace":
        request = replace(request, workspace_id=str(uuid.uuid4()))
    elif change == "operation":
        request = replace(request, operation_id=str(uuid.uuid4()))
    elif change == "input_type":
        request = asdict(request)
    else:
        env.info = replace(env.info, start_to_close_timeout=None, schedule_to_close_timeout=None)
    with pytest.raises(ApplicationError) as error:
        asyncio.run(env.run(complete_scoped_prd_activity, request))
    assert error.value.type == "PRD_ACTIVITY_SCOPE_INVALID" and error.value.non_retryable is True
    operation.refresh_from_db()
    assert operation.status == "QUEUED" and bridge.runtime.preparations == 0
    assert not DocumentCheckpoint.objects.exists()


def test_guard_expiring_after_provider_prepare_cannot_apply_checkpoint(bridge):
    operation = accept(bridge, submission(bridge)).operation
    active = [True]
    bridge.runtime.hook = lambda *_: active.__setitem__(0, False)
    result = complete_scoped_prd_operation(
        workspace_id=bridge.workspace.id, operation_id=operation.id, execution_guard=lambda: active[0]
    )
    assert result["status"] == "FAILED" and result["effect_applied"] is False
    assert bridge.runtime.preparations == 1
    assert not DocumentCheckpoint.objects.exists() and not ScopedPrdSubject.objects.exists()


def test_settlement_activity_without_cancellation_cannot_apply_scope_effect(bridge):
    operation = accept(bridge, submission(bridge)).operation
    drain(bridge, FakeClient())
    request = activity_input(bridge, operation)
    result = asyncio.run(environment(request).run(settle_scoped_prd_activity, request))
    assert result.operation_status == "FAILED" and result.effect_applied is False
    assert bridge.runtime.preparations == 0 and not DocumentCheckpoint.objects.exists()


def test_restart_and_duplicate_activity_complete_review_once_without_protected_retrieval(bridge, settings):
    subject, _, _ = submit(bridge)
    operation = accept(bridge, review_command(bridge, subject)).operation
    client = FakeClient()
    drain(bridge, client)
    assert client.calls and all("sentinel" not in repr(asdict(call[1])) for call in client.calls)
    request = activity_input(bridge, operation)
    # New adapter and freshly loaded ORM records model process restart. The fake
    # protected store retains its test bytes, never through the activity payload.
    checkpoint = DocumentCheckpoint.objects.get(id=subject.checkpoint_id)
    bridge.initiative.refresh_from_db()
    runtime = SyntheticCompletionRuntime(
        (bridge.binding, bridge.initiative, checkpoint, bridge.gates[0], bridge.user, bridge.workspace)
    )
    runtime.body = bridge.runtime.body
    settings.CURVE_PRD_ACCEPTANCE_RUNTIME = settings.CURVE_PRD_COMPLETION_RUNTIME = runtime
    close_old_connections()
    result = asyncio.run(environment(request).run(complete_scoped_prd_activity, request))
    assert result.operation_status == "SUCCEEDED" and result.effect_applied is True
    event_count = DomainEvent.objects.count()
    version = Operation.objects.get(id=operation.id).aggregate_version
    duplicate = asyncio.run(environment(request).run(complete_scoped_prd_activity, request))
    assert duplicate.operation_status == "SUCCEEDED" and duplicate.effect_applied is False
    assert duplicate.operation_version == result.operation_version == version
    assert runtime.preparations == 1 and runtime.retained == [operation.id]
    assert PrdReviewDecision.objects.count() == ScopedPrdDecision.objects.count() == 1
    assert DomainEvent.objects.count() == event_count
    bridge.initiative.refresh_from_db()
    assert bridge.initiative.state == "PLANNING"
    assert "sentinel" not in repr(list(DomainEvent.objects.values()))
    assert "sentinel" not in repr(list(AuditEvent.objects.values()))


@pytest.mark.parametrize("fail", [False, True])
def test_workflow_routes_only_to_scoped_activities_with_bounded_retries(monkeypatch, fail):
    # Pure deterministic invocation of workflow code, not a server/history replay.
    from plane.curve.temporal import scoped_prd_workflows

    request = OperationActivityInputV1(
        "1.0", str(uuid.uuid4()), str(uuid.uuid4()), 1, "synthetic-correlation", "synthetic-command"
    )
    outcome = OperationActivityResultV1("1.0", "FAILED" if fail else "SUCCEEDED", 2, not fail, "sha256:" + "a" * 64)
    calls = []

    async def execute(name, value, **kwargs):
        calls.append((name, value, kwargs))
        if name == PRD_COMPLETE_ACTIVITY and fail:
            raise ActivityError(
                "Synthetic activity failed",
                scheduled_event_id=1,
                started_event_id=2,
                identity="synthetic",
                activity_type=name,
                activity_id="synthetic-activity",
                retry_state=None,
            )
        return outcome

    monkeypatch.setattr(scoped_prd_workflows.workflow, "execute_activity", execute)
    assert asyncio.run(CurveScopedPrdOperationWorkflowV1().run(request)) is outcome
    assert [call[0] for call in calls] == (
        [PRD_COMPLETE_ACTIVITY, PRD_SETTLE_ACTIVITY] if fail else [PRD_COMPLETE_ACTIVITY]
    )
    assert all(call[1] is request and call[2]["retry_policy"].maximum_attempts == 3 for call in calls)
    assert calls[0][2]["schedule_to_close_timeout"] == timedelta(minutes=5)
    assert calls[0][2]["heartbeat_timeout"] == timedelta(seconds=20)


def test_combined_registration_keeps_legacy_and_adds_scoped_workflow():
    from plane.curve.temporal import registry
    from plane.curve.temporal.prd_workflows import CurvePrdOperationWorkflowV1

    assert CurvePrdOperationWorkflowV1 in registry.CURVE_WORKFLOWS_V1
    assert CurveScopedPrdOperationWorkflowV1 not in registry.CURVE_WORKFLOWS_V1
    assert set(registry.CURVE_WORKFLOWS_V1).issubset(registry.CURVE_WORKFLOWS_ALL)
    assert CurveScopedPrdOperationWorkflowV1 in registry.CURVE_WORKFLOWS_ALL
    names = [workflow.__temporal_workflow_definition.name for workflow in registry.CURVE_WORKFLOWS_ALL]
    assert len(names) == len(set(names))
    assert "CurvePrdOperationWorkflowV1" in names and PRD_WORKFLOW_TYPE in names


@pytest.mark.parametrize("change", ["workspace", "operation", "legacy_prefix", "destination"])
def test_scoped_transition_rejects_identity_or_destination_substitution(bridge, change):
    from plane.curve.policy_services import transition_operation_with_service_authorization
    from plane.curve.services import InvalidCommand

    operation = accept(bridge, submission(bridge)).operation
    grant = bridge.runtime.worker_authorization(workspace_id=bridge.workspace.id, operation_id=operation.id)
    workspace_id = str(uuid.uuid4()) if change == "workspace" else str(bridge.workspace.id)
    operation_id = str(uuid.uuid4()) if change == "operation" else str(operation.id)
    workflow_id = prd_workflow_id(workspace_id=workspace_id, operation_id=operation_id)
    if change == "legacy_prefix":
        workflow_id = f"curve:{workspace_id}:{operation_id}"
    with pytest.raises(InvalidCommand, match="invalid (workflow_id|destination)"):
        transition_operation_with_service_authorization(
            workspace_id=bridge.workspace.id,
            operation_id=operation.id,
            expected_version=operation.aggregate_version,
            status="QUEUED",
            service_actor=grant["actor"],
            service_authorization=grant["authorization"],
            correlation_id=operation.correlation_id,
            causation_id=str(operation.id),
            destination="CURVE_PRD_CANDIDATE_V1" if change == "destination" else PRD_DESTINATION,
            workflow_id=workflow_id,
        )
    operation.refresh_from_db()
    assert operation.status == "PENDING" and operation.workflow_id is None
    assert bridge.runtime.preparations == 0 and not DocumentCheckpoint.objects.exists()
