# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import asyncio
import os
import uuid

import pytest
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from plane.curve.temporal.orchestration_contracts import (
    ChildAnswerSignalV1,
    ChildCompleteSignalV1,
    ChildPhase,
    ChildQuestionSignalV1,
    ChildSignalV1,
    ChildWorkflowInputV1,
    FailureCode,
    SignalErrorCode,
)
from plane.curve.temporal.orchestration_workflows import CurveSliceAttemptWorkflowV1


pytestmark = pytest.mark.unit

WORKSPACE_ID = "00000000-0000-4000-8000-000000000001"
INITIATIVE_ID = "00000000-0000-4000-8000-000000000002"
SLICE_ID = "00000000-0000-4000-8000-000000000101"
ATTEMPT_ID = "00000000-0000-4000-8000-000000000201"
DIGEST_A = f"sha256:{'1' * 64}"
DIGEST_B = f"sha256:{'2' * 64}"


def _child_input() -> ChildWorkflowInputV1:
    return ChildWorkflowInputV1(
        schema_version="1.0",
        workspace_id=WORKSPACE_ID,
        initiative_id=INITIATIVE_ID,
        plan_generation=1,
        slice_id=SLICE_ID,
        dependency_slice_ids=(),
        attempt_id=ATTEMPT_ID,
        attempt_version=1,
        attempt_digest=DIGEST_A,
    )


def _signal(*, command_id: str, expected_state_version: int, **extra):
    values = {
        "schema_version": "1.0",
        "workspace_id": WORKSPACE_ID,
        "initiative_id": INITIATIVE_ID,
        "plan_generation": 1,
        "slice_id": SLICE_ID,
        "attempt_id": ATTEMPT_ID,
        "attempt_version": 1,
        "command_id": command_id,
        "expected_state_version": expected_state_version,
    }
    values.update(extra)
    return values


async def _run_with_child(test_case):
    previous_settings_module = os.environ.get("DJANGO_SETTINGS_MODULE")
    os.environ["DJANGO_SETTINGS_MODULE"] = "plane.settings.curve_worker"
    external_address = os.environ.get("TEMPORAL_TEST_ADDRESS")
    try:
        if external_address:
            client = await Client.connect(
                external_address,
                namespace=os.environ.get("TEMPORAL_TEST_NAMESPACE", "curve-local"),
            )
            task_queue = f"curve-m0-s6a-child-{uuid.uuid4()}"
            async with Worker(
                client,
                task_queue=task_queue,
                workflows=[CurveSliceAttemptWorkflowV1],
            ):
                await test_case(client, task_queue, False)
            return

        async with await WorkflowEnvironment.start_time_skipping() as environment:
            task_queue = f"curve-m0-s6a-child-{uuid.uuid4()}"
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[CurveSliceAttemptWorkflowV1],
            ):
                await test_case(environment.client, task_queue, True)
    finally:
        if previous_settings_module is None:
            os.environ.pop("DJANGO_SETTINGS_MODULE", None)
        else:
            os.environ["DJANGO_SETTINGS_MODULE"] = previous_settings_module


def test_m0_s6a_at_04_and_05_child_question_answer_idempotency_and_completion():
    async def scenario(client, task_queue, _time_skipping):
        handle = await client.start_workflow(
            CurveSliceAttemptWorkflowV1.run,
            _child_input(),
            id=f"child-question-{uuid.uuid4()}",
            task_queue=task_queue,
        )
        started = ChildSignalV1(**_signal(command_id="command:start:1", expected_state_version=1))
        await handle.signal(CurveSliceAttemptWorkflowV1.report_started, started)

        question = ChildQuestionSignalV1(
            **_signal(
                command_id="command:question:1",
                expected_state_version=2,
                question_ref="object:question:1",
                question_digest=DIGEST_A,
            )
        )
        await handle.signal(CurveSliceAttemptWorkflowV1.ask_question, question)
        await handle.signal(CurveSliceAttemptWorkflowV1.ask_question, question)
        waiting = await handle.query(CurveSliceAttemptWorkflowV1.state)
        assert waiting.phase == ChildPhase.WAITING_FOR_HUMAN
        assert waiting.state_version == 3
        assert waiting.active_question_ref == "object:question:1"

        answer = ChildAnswerSignalV1(
            **_signal(
                command_id="command:answer:1",
                expected_state_version=3,
                question_ref="object:question:1",
                answer_ref="object:answer:1",
                answer_digest=DIGEST_B,
            )
        )
        await handle.signal(CurveSliceAttemptWorkflowV1.answer_question, answer)
        resumed = await handle.query(CurveSliceAttemptWorkflowV1.state)
        assert resumed.phase == ChildPhase.RUNNING
        assert resumed.state_version == 4
        assert resumed.answer_ref == "object:answer:1"

        complete = ChildCompleteSignalV1(
            **_signal(
                command_id="command:complete:1",
                expected_state_version=4,
                outcome=ChildPhase.SUCCEEDED,
                failure_code=None,
            )
        )
        await handle.signal(CurveSliceAttemptWorkflowV1.complete_attempt, complete)
        result = await handle.result()
        assert result.phase == ChildPhase.SUCCEEDED
        assert result.state_version == 5
        assert result.failure_code is None

    asyncio.run(_run_with_child(scenario))


def test_m0_s6a_at_04_first_rejection_is_durable_and_duplicate_is_noop():
    async def scenario(client, task_queue, _time_skipping):
        handle = await client.start_workflow(
            CurveSliceAttemptWorkflowV1.run,
            _child_input(),
            id=f"child-rejection-{uuid.uuid4()}",
            task_queue=task_queue,
        )
        stale = ChildSignalV1(**_signal(command_id="command:start:stale", expected_state_version=9))
        await handle.signal(CurveSliceAttemptWorkflowV1.report_started, stale)
        await handle.signal(CurveSliceAttemptWorkflowV1.report_started, stale)

        rejected = await handle.query(CurveSliceAttemptWorkflowV1.state)
        assert rejected.phase == ChildPhase.QUEUED
        assert rejected.state_version == 2
        assert rejected.last_rejected_command_id == "command:start:stale"
        assert rejected.last_command_rejection_code == SignalErrorCode.STALE_STATE_VERSION

        started = ChildSignalV1(**_signal(command_id="command:start:valid", expected_state_version=2))
        await handle.signal(CurveSliceAttemptWorkflowV1.report_started, started)
        running = await handle.query(CurveSliceAttemptWorkflowV1.state)
        assert running.phase == ChildPhase.RUNNING
        assert running.state_version == 3
        assert running.last_rejected_command_id is None

        complete = ChildCompleteSignalV1(
            **_signal(
                command_id="command:complete:valid",
                expected_state_version=3,
                outcome=ChildPhase.SUCCEEDED,
                failure_code=None,
            )
        )
        await handle.signal(CurveSliceAttemptWorkflowV1.complete_attempt, complete)
        assert (await handle.result()).phase == ChildPhase.SUCCEEDED

    asyncio.run(_run_with_child(scenario))


@pytest.mark.parametrize(
    ("start_attempt", "expected_failure"),
    [
        (False, FailureCode.START_TIMEOUT),
        (True, FailureCode.ATTEMPT_TIMEOUT),
    ],
)
def test_m0_s6a_child_bounded_timeouts(start_attempt, expected_failure):
    async def scenario(client, task_queue, time_skipping):
        if not time_skipping:
            pytest.skip("bounded timeout proof requires the Temporal time-skipping server")
        handle = await client.start_workflow(
            CurveSliceAttemptWorkflowV1.run,
            _child_input(),
            id=f"child-timeout-{uuid.uuid4()}",
            task_queue=task_queue,
        )
        if start_attempt:
            await handle.signal(
                CurveSliceAttemptWorkflowV1.report_started,
                ChildSignalV1(**_signal(command_id="command:start:1", expected_state_version=1)),
            )
        result = await handle.result()
        assert result.phase == ChildPhase.FAILED_TERMINAL
        assert result.failure_code == expected_failure

    asyncio.run(_run_with_child(scenario))


def test_m0_s6a_child_question_timeout_is_terminal():
    async def scenario(client, task_queue, time_skipping):
        if not time_skipping:
            pytest.skip("question timeout proof requires the Temporal time-skipping server")
        handle = await client.start_workflow(
            CurveSliceAttemptWorkflowV1.run,
            _child_input(),
            id=f"child-question-timeout-{uuid.uuid4()}",
            task_queue=task_queue,
        )
        await handle.signal(
            CurveSliceAttemptWorkflowV1.report_started,
            ChildSignalV1(**_signal(command_id="command:start:1", expected_state_version=1)),
        )
        await handle.signal(
            CurveSliceAttemptWorkflowV1.ask_question,
            ChildQuestionSignalV1(
                **_signal(
                    command_id="command:question:1",
                    expected_state_version=2,
                    question_ref="object:question:1",
                    question_digest=DIGEST_A,
                )
            ),
        )
        result = await handle.result()
        assert result.phase == ChildPhase.FAILED_TERMINAL
        assert result.failure_code == FailureCode.QUESTION_TIMEOUT

    asyncio.run(_run_with_child(scenario))


def test_m0_s6a_child_temporal_cancellation_returns_safe_terminal_result():
    async def scenario(client, task_queue, _time_skipping):
        handle = await client.start_workflow(
            CurveSliceAttemptWorkflowV1.run,
            _child_input(),
            id=f"child-cancel-{uuid.uuid4()}",
            task_queue=task_queue,
        )
        await handle.signal(
            CurveSliceAttemptWorkflowV1.report_started,
            ChildSignalV1(**_signal(command_id="command:start:1", expected_state_version=1)),
        )
        await handle.cancel()
        result = await handle.result()
        assert result.phase == ChildPhase.CANCELLED
        assert result.failure_code is None

    asyncio.run(_run_with_child(scenario))
