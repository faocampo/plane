# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import asyncio
import os
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.urls import reverse
from django.utils import timezone
from temporalio.exceptions import WorkflowAlreadyStartedError, ApplicationError
from temporalio.testing import WorkflowEnvironment, ActivityEnvironment
from temporalio.worker import Worker, Replayer

from plane.curve.models import Operation, OutboxEvent, PrdReviewDecision
from plane.curve.prd_completion import complete_prd_operation
from plane.curve.temporal.prd_relay import relay_prd_workspace_once
from plane.curve.temporal.prd_workflows import CurvePrdOperationWorkflowV1
from plane.curve.temporal.prd_activities import complete_prd_activity, settle_prd_activity
from plane.curve.temporal.prd_contracts import PRD_DESTINATION, PRD_WORKFLOW_TYPE, prd_workflow_id
from plane.curve.temporal.contracts import OperationActivityInputV1
from plane.curve.temporal.constants import TASK_QUEUE
from plane.curve.views import operation_etag
from plane.curve.tests.test_prd_accepted_commands import fixture  # noqa: F401
from plane.curve.tests.test_prd_completion import real_digest, setup as completion_setup, accepted  # noqa: F401

setup = completion_setup

pytestmark = [pytest.mark.unit, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def delivery(settings):
    settings.CURVE_PRD_DELIVERY_ENABLED = True


class FakeClient:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure
        self.created = False

    async def start_workflow(self, kind, value, **kwargs):
        self.calls.append((kind, value, kwargs))
        if self.failure == "always":
            raise RuntimeError("Synthetic private transport sentinel")
        if self.failure == "ambiguous":
            if self.created:
                raise WorkflowAlreadyStartedError(kwargs["id"], kind)
            self.created = True
            raise RuntimeError("Synthetic private transport sentinel")
        self.created = True

    def get_workflow_handle(self, _):
        return self

    async def describe(self, **kwargs):
        return SimpleNamespace(workflow_type=PRD_WORKFLOW_TYPE)


def drain(setup, client):
    return asyncio.run(
        relay_prd_workspace_once(client=client, workspace_id=setup[0][5].id, worker_id="synthetic-prd-relay")
    )


def make_due(setup):
    OutboxEvent.objects.filter(workspace_id=setup[0][5].id, destination=PRD_DESTINATION).update(
        next_attempt_at=timezone.now()
    )


def cancel(setup, operation_id):
    operation = Operation.objects.get(id=operation_id)
    response = setup[2].post(
        reverse("curve-operation-cancel", kwargs={"slug": setup[0][5].slug, "resource_id": operation_id}),
        data={},
        format="json",
        HTTP_IDEMPOTENCY_KEY="synthetic-cancel",
        HTTP_IF_MATCH=operation_etag(operation_id=str(operation_id), version=operation.aggregate_version),
    )
    assert response.status_code == 202, response.data


def test_disabled_delivery_does_not_claim_work(setup, settings):
    accepted(setup)
    settings.CURVE_PRD_DELIVERY_ENABLED = False
    client = FakeClient()
    assert drain(setup, client) == 0 and client.calls == []
    assert OutboxEvent.objects.get().state == "PENDING"


def test_ambiguous_start_retries_same_workflow_and_acknowledges_existing_execution(setup, caplog):
    operation_id = accepted(setup)
    client = FakeClient("ambiguous")
    assert drain(setup, client) == 0
    operation = Operation.objects.get(id=operation_id)
    assert operation.status == "QUEUED"
    make_due(setup)
    assert drain(setup, client) >= 1
    assert len(client.calls) == 2 and client.calls[0][2]["id"] == client.calls[1][2]["id"]
    assert operation.workflow_id == prd_workflow_id(workspace_id=str(setup[0][5].id), operation_id=str(operation_id))
    assert not OutboxEvent.objects.exclude(state="DELIVERED").exists()
    assert "sentinel" not in caplog.text


def test_transport_failure_dead_letters_after_bounded_attempts_and_can_still_cancel(setup):
    operation_id = accepted(setup)
    client = FakeClient("always")
    for _ in range(3):
        make_due(setup)
        drain(setup, client)
    dead = OutboxEvent.objects.get(state="DEAD_LETTER")
    assert dead.attempt_count == 3 and "sentinel" not in repr(dead.last_error)
    cancel(setup, operation_id)
    assert drain(setup, client) >= 1
    assert Operation.objects.get(id=operation_id).status == "CANCELLED"
    assert setup[1].preparations == 0


def test_cancel_before_dispatch_routes_to_prd_and_settles_without_workflow_or_provider(setup):
    operation_id = accepted(setup)
    cancel(setup, operation_id)
    assert not OutboxEvent.objects.exclude(destination=PRD_DESTINATION).exists()
    client = FakeClient()
    assert drain(setup, client) == 2
    assert Operation.objects.get(id=operation_id).status == "CANCELLED"
    assert client.calls == [] and setup[1].preparations == 0


def test_execution_guard_expiring_after_preparation_prevents_commit(setup):
    operation_id = accepted(setup)
    active = [True]
    setup[1].hook = lambda *_: active.__setitem__(0, False)
    result = complete_prd_operation(
        workspace_id=setup[0][5].id, operation_id=operation_id, execution_guard=lambda: active[0]
    )
    assert result["status"] == "FAILED" and PrdReviewDecision.objects.count() == 0


def test_execution_guard_after_success_write_rolls_back_domain_and_result(setup, monkeypatch):
    from plane.curve import prd_completion

    operation_id = accepted(setup)
    active = [True]
    original = prd_completion._transition

    def transition(runtime, operation, status, *args, **kwargs):
        result = original(runtime, operation, status, *args, **kwargs)
        if status == "SUCCEEDED":
            active[0] = False
        return result

    monkeypatch.setattr(prd_completion, "_transition", transition)
    result = complete_prd_operation(
        workspace_id=setup[0][5].id, operation_id=operation_id, execution_guard=lambda: active[0]
    )
    assert result["status"] == "FAILED"
    operation = Operation.objects.get(id=operation_id)
    assert operation.result_ref is None and PrdReviewDecision.objects.count() == 0
    setup[0][1].refresh_from_db()
    assert setup[0][1].state == "PRD_REVIEW"


def test_existing_workflow_of_wrong_type_is_not_acknowledged(setup):
    accepted(setup)

    class WrongTypeClient(FakeClient):
        async def describe(self, **kwargs):
            return SimpleNamespace(workflow_type="CurveOperationWorkflowV1")

    client = WrongTypeClient("ambiguous")
    drain(setup, client)
    make_due(setup)
    drain(setup, client)
    assert OutboxEvent.objects.filter(state="RETRY_SCHEDULED", attempt_count=2).exists()


def _input(setup, operation_id):
    return OperationActivityInputV1(
        schema_version="1.0",
        workspace_id=str(setup[0][5].id),
        operation_id=str(operation_id),
        operation_version=1,
        correlation_id="synthetic-correlation",
        command_id=f"prd-operation:{operation_id}",
    )


def test_expired_activity_is_fenced_and_wrong_workflow_scope_is_rejected(setup):
    operation_id = accepted(setup)
    drain(setup, FakeClient())
    request = _input(setup, operation_id)
    environment = ActivityEnvironment()
    environment.info = replace(
        environment.info,
        workflow_id=prd_workflow_id(workspace_id=request.workspace_id, operation_id=request.operation_id),
        workflow_type=PRD_WORKFLOW_TYPE,
        started_time=timezone.now() - timedelta(minutes=3),
        start_to_close_timeout=timedelta(minutes=2),
    )
    result = asyncio.run(environment.run(complete_prd_activity, request))
    assert result.operation_status == "FAILED" and setup[1].preparations == 0
    environment.info = replace(environment.info, workflow_id="synthetic-wrong-workflow")
    with pytest.raises(ApplicationError, match="scope is invalid"):
        asyncio.run(environment.run(complete_prd_activity, request))


@pytest.mark.parametrize("provider_failure", [False, True])
def test_real_temporal_delivery_completion_safe_failure_and_history_replay(setup, monkeypatch, provider_failure):
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "plane.settings.curve_worker")
    operation_id = accepted(setup)
    if provider_failure:
        from plane.curve.temporal import prd_activities

        original = prd_activities.complete_prd_operation

        def fail(**kwargs):
            if kwargs["execution_guard"]():
                raise RuntimeError("Synthetic private transport sentinel")
            return original(**kwargs)

        monkeypatch.setattr(prd_activities, "complete_prd_operation", fail)

    async def scenario():
        path = os.environ.get("TEMPORAL_TEST_SERVER_PATH")
        if not path:
            pytest.skip("A verified local Temporal test server is required")
        async with await WorkflowEnvironment.start_time_skipping(test_server_existing_path=path) as environment:
            async with Worker(
                environment.client,
                task_queue=TASK_QUEUE,
                workflows=[CurvePrdOperationWorkflowV1],
                activities=[complete_prd_activity, settle_prd_activity],
            ):
                assert (
                    await relay_prd_workspace_once(
                        client=environment.client, workspace_id=setup[0][5].id, worker_id="synthetic-prd-relay"
                    )
                    == 1
                )
                handle = environment.client.get_workflow_handle(
                    prd_workflow_id(workspace_id=str(setup[0][5].id), operation_id=str(operation_id))
                )
                result = await asyncio.wait_for(handle.result(), timeout=45)
                history = await handle.fetch_history()
                assert "sentinel" not in history.to_json()
                await Replayer(workflows=[CurvePrdOperationWorkflowV1]).replay_workflow(history)
                return result

    result = asyncio.run(scenario())
    operation = Operation.objects.get(id=operation_id)
    assert operation.status == result["operation_status"] == ("FAILED" if provider_failure else "SUCCEEDED")
    assert PrdReviewDecision.objects.count() == int(not provider_failure)
    if not provider_failure:
        setup[0][1].refresh_from_db()
        assert setup[0][1].state == "PLANNING"
