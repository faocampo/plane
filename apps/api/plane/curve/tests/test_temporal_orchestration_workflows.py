# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import asyncio
import os
import uuid

import pytest
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
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
    ParentCancelSignalV1,
    ParentPhase,
    ParentSignalV1,
    ParentWorkflowInputV1,
    SignalErrorCode,
    SliceDescriptorV1,
)
from plane.curve.temporal.constants import initiative_workflow_id, slice_attempt_workflow_id
from plane.curve.temporal.orchestration_workflows import (
    CurveInitiativeOrchestrationWorkflowV1,
    CurveSliceAttemptWorkflowV1,
)


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
                workflows=[CurveInitiativeOrchestrationWorkflowV1, CurveSliceAttemptWorkflowV1],
            ):
                await test_case(client, task_queue, False)
            return

        try:
            environment = await WorkflowEnvironment.start_time_skipping()
        except RuntimeError as exc:
            if "Failed starting test server" not in str(exc):
                raise
            pytest.skip(
                "Temporal time-skipping test server is unavailable on this platform; "
                "set TEMPORAL_TEST_ADDRESS to run against a local Temporal server"
            )

        async with environment:
            task_queue = f"curve-m0-s6a-child-{uuid.uuid4()}"
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[CurveInitiativeOrchestrationWorkflowV1, CurveSliceAttemptWorkflowV1],
            ):
                await test_case(environment.client, task_queue, True)
    finally:
        if previous_settings_module is None:
            os.environ.pop("DJANGO_SETTINGS_MODULE", None)
        else:
            os.environ["DJANGO_SETTINGS_MODULE"] = previous_settings_module


def _slice(slice_id, attempt_id, *, dependencies=(), digest=DIGEST_A):
    return SliceDescriptorV1(
        slice_id=slice_id,
        dependency_slice_ids=dependencies,
        attempt_id=attempt_id,
        attempt_version=1,
        attempt_digest=digest,
    )


def _test_plan_generation() -> int:
    return uuid.uuid4().int % 2_000_000_000 + 1


def _parent_input(slices, *, plan_generation=1):
    return ParentWorkflowInputV1(
        schema_version="1.0",
        workspace_id=WORKSPACE_ID,
        initiative_id=INITIATIVE_ID,
        plan_generation=plan_generation,
        plan_digest=DIGEST_A,
        slices=tuple(slices),
    )


async def _wait_for_parent_state(handle, predicate, *, attempts=200):
    for _ in range(attempts):
        state = await handle.query(CurveInitiativeOrchestrationWorkflowV1.state)
        if predicate(state):
            return state
        await asyncio.sleep(0.01)
    raise AssertionError("parent state did not reach the expected condition")


async def _complete_synthetic_child(client, descriptor, *, plan_generation=1):
    child_id = slice_attempt_workflow_id(
        workspace_id=WORKSPACE_ID,
        initiative_id=INITIATIVE_ID,
        plan_generation=plan_generation,
        slice_id=descriptor.slice_id,
        attempt_id=descriptor.attempt_id,
    )
    child = client.get_workflow_handle(child_id)
    await child.signal(
        CurveSliceAttemptWorkflowV1.report_started,
        ChildSignalV1(
            **_signal(
                command_id=f"command:start:{descriptor.slice_id}",
                expected_state_version=1,
                plan_generation=plan_generation,
                slice_id=descriptor.slice_id,
                attempt_id=descriptor.attempt_id,
            )
        ),
    )
    await child.signal(
        CurveSliceAttemptWorkflowV1.complete_attempt,
        ChildCompleteSignalV1(
            **_signal(
                command_id=f"command:complete:{descriptor.slice_id}",
                expected_state_version=2,
                plan_generation=plan_generation,
                slice_id=descriptor.slice_id,
                attempt_id=descriptor.attempt_id,
                outcome=ChildPhase.SUCCEEDED,
                failure_code=None,
            )
        ),
    )


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


def test_m0_s6a_at_01_and_03_parent_runs_sorted_waves_and_rejects_duplicate_start():
    async def scenario(client, task_queue, _time_skipping):
        plan_generation = _test_plan_generation()
        root_a = _slice(SLICE_ID, ATTEMPT_ID)
        root_b = _slice(
            "00000000-0000-4000-8000-000000000102",
            "00000000-0000-4000-8000-000000000202",
            digest=DIGEST_B,
        )
        dependent = _slice(
            "00000000-0000-4000-8000-000000000103",
            "00000000-0000-4000-8000-000000000203",
            dependencies=(root_b.slice_id, root_a.slice_id),
        )
        parent_input = _parent_input((dependent, root_b, root_a), plan_generation=plan_generation)
        parent_id = initiative_workflow_id(
            workspace_id=WORKSPACE_ID,
            initiative_id=INITIATIVE_ID,
            plan_generation=plan_generation,
        )
        handle = await client.start_workflow(
            CurveInitiativeOrchestrationWorkflowV1.run,
            parent_input,
            id=parent_id,
            task_queue=task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
        with pytest.raises(WorkflowAlreadyStartedError):
            await client.start_workflow(
                CurveInitiativeOrchestrationWorkflowV1.run,
                parent_input,
                id=handle.id,
                task_queue=task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )

        first_wave = await _wait_for_parent_state(
            handle,
            lambda state: state.active_slice_ids == tuple(sorted((root_a.slice_id, root_b.slice_id))),
        )
        assert first_wave.next_wave_index == 0
        await _complete_synthetic_child(client, root_b, plan_generation=plan_generation)
        await _complete_synthetic_child(client, root_a, plan_generation=plan_generation)

        second_wave = await _wait_for_parent_state(
            handle,
            lambda state: state.active_slice_ids == (dependent.slice_id,),
        )
        assert second_wave.completed_slice_ids == tuple(sorted((root_a.slice_id, root_b.slice_id)))
        await _complete_synthetic_child(client, dependent, plan_generation=plan_generation)
        result = await handle.result()
        assert result.phase == ParentPhase.SUCCEEDED
        assert result.completed_slice_ids == tuple(sorted((root_a.slice_id, root_b.slice_id, dependent.slice_id)))
        assert not result.failed_slice_ids
        assert not result.cancelled_slice_ids
        with pytest.raises(WorkflowAlreadyStartedError):
            await client.start_workflow(
                CurveInitiativeOrchestrationWorkflowV1.run,
                parent_input,
                id=handle.id,
                task_queue=task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )

    asyncio.run(_run_with_child(scenario))


def test_m0_s6a_at_06_parent_pause_holds_the_wave_barrier_until_resume():
    async def scenario(client, task_queue, _time_skipping):
        plan_generation = _test_plan_generation()
        root = _slice(SLICE_ID, ATTEMPT_ID)
        dependent = _slice(
            "00000000-0000-4000-8000-000000000103",
            "00000000-0000-4000-8000-000000000203",
            dependencies=(root.slice_id,),
            digest=DIGEST_B,
        )
        handle = await client.start_workflow(
            CurveInitiativeOrchestrationWorkflowV1.run,
            _parent_input((root, dependent), plan_generation=plan_generation),
            id=f"parent-pause-{uuid.uuid4()}",
            task_queue=task_queue,
        )
        active = await _wait_for_parent_state(handle, lambda state: state.active_slice_ids == (root.slice_id,))
        await handle.signal(
            CurveInitiativeOrchestrationWorkflowV1.pause,
            ParentSignalV1(
                schema_version="1.0",
                workspace_id=WORKSPACE_ID,
                initiative_id=INITIATIVE_ID,
                plan_generation=plan_generation,
                command_id="command:parent:pause:1",
                expected_state_version=active.state_version,
            ),
        )
        await _complete_synthetic_child(client, root, plan_generation=plan_generation)
        paused = await _wait_for_parent_state(
            handle,
            lambda state: state.phase == ParentPhase.PAUSED and not state.active_slice_ids,
        )
        assert paused.next_wave_index == 1

        await handle.signal(
            CurveInitiativeOrchestrationWorkflowV1.resume,
            ParentSignalV1(
                schema_version="1.0",
                workspace_id=WORKSPACE_ID,
                initiative_id=INITIATIVE_ID,
                plan_generation=plan_generation,
                command_id="command:parent:resume:1",
                expected_state_version=paused.state_version,
            ),
        )
        await _wait_for_parent_state(handle, lambda state: state.active_slice_ids == (dependent.slice_id,))
        await _complete_synthetic_child(client, dependent, plan_generation=plan_generation)
        assert (await handle.result()).phase == ParentPhase.SUCCEEDED

    asyncio.run(_run_with_child(scenario))


def test_m0_s6a_at_07_parent_cancel_propagates_and_settles_all_children():
    async def scenario(client, task_queue, _time_skipping):
        plan_generation = _test_plan_generation()
        root_a = _slice(SLICE_ID, ATTEMPT_ID)
        root_b = _slice(
            "00000000-0000-4000-8000-000000000102",
            "00000000-0000-4000-8000-000000000202",
            digest=DIGEST_B,
        )
        handle = await client.start_workflow(
            CurveInitiativeOrchestrationWorkflowV1.run,
            _parent_input((root_b, root_a), plan_generation=plan_generation),
            id=f"parent-cancel-{uuid.uuid4()}",
            task_queue=task_queue,
        )
        active = await _wait_for_parent_state(
            handle,
            lambda state: state.active_slice_ids == tuple(sorted((root_a.slice_id, root_b.slice_id))),
        )
        await handle.signal(
            CurveInitiativeOrchestrationWorkflowV1.request_cancel,
            ParentCancelSignalV1(
                schema_version="1.0",
                workspace_id=WORKSPACE_ID,
                initiative_id=INITIATIVE_ID,
                plan_generation=plan_generation,
                command_id="command:parent:cancel:1",
                expected_state_version=active.state_version,
                reason_code="USER_REQUESTED",
            ),
        )
        result = await handle.result()
        assert result.phase == ParentPhase.CANCELLED
        assert result.cancelled_slice_ids == tuple(sorted((root_a.slice_id, root_b.slice_id)))
        assert not result.failed_slice_ids

    asyncio.run(_run_with_child(scenario))


def test_m0_s6a_at_08_parent_continues_as_new_after_ten_settled_waves():
    async def scenario(client, task_queue, _time_skipping):
        plan_generation = _test_plan_generation()
        descriptors = []
        for index in range(11):
            slice_id = f"00000000-0000-4000-8000-{100 + index:012d}"
            attempt_id = f"00000000-0000-4000-8000-{200 + index:012d}"
            dependencies = () if index == 0 else (descriptors[-1].slice_id,)
            descriptors.append(_slice(slice_id, attempt_id, dependencies=dependencies))

        parent_id = f"parent-continue-{uuid.uuid4()}"
        handle = await client.start_workflow(
            CurveInitiativeOrchestrationWorkflowV1.run,
            _parent_input(descriptors, plan_generation=plan_generation),
            id=parent_id,
            task_queue=task_queue,
        )
        for index, descriptor in enumerate(descriptors):
            current = client.get_workflow_handle(parent_id)
            state = await _wait_for_parent_state(
                current,
                lambda value, slice_id=descriptor.slice_id: value.active_slice_ids == (slice_id,),
            )
            if index == 10:
                assert state.continue_as_new_count == 1
            await _complete_synthetic_child(client, descriptor, plan_generation=plan_generation)

        result = await handle.result()
        assert result.phase == ParentPhase.SUCCEEDED
        assert result.continue_as_new_count == 1
        assert result.completed_slice_ids == tuple(sorted(item.slice_id for item in descriptors))

    asyncio.run(_run_with_child(scenario))
