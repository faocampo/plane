# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Deterministic, model-free Temporal orchestration workflows for Curve."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Callable

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from plane.curve.temporal.constants import (
        ATTEMPT_TERMINAL_TIMEOUT_SECONDS,
        CHILD_ATTEMPT_PATCH_ID,
        CHILD_START_SIGNAL_TIMEOUT_SECONDS,
        CONTINUE_AS_NEW_WAVE_THRESHOLD,
        PARENT_CANCEL_TIMEOUT_SECONDS,
        PARENT_ORCHESTRATION_PATCH_ID,
        QUESTION_ANSWER_TIMEOUT_SECONDS,
        slice_attempt_workflow_id,
    )
    from plane.curve.temporal.orchestration_contracts import (
        MAX_QUESTIONS_PER_ATTEMPT,
        MESSAGE_SCHEMA_VERSION,
        ChildAnswerSignalV1,
        ChildCompleteSignalV1,
        ChildPhase,
        ChildQuestionSignalV1,
        ChildResultV1,
        ChildSignalV1,
        ChildStateV1,
        ChildWorkflowInputV1,
        CommandOutcome,
        FailureCode,
        ParentCancelSignalV1,
        ParentPhase,
        ParentResultV1,
        ParentSignalV1,
        ParentStateV1,
        ParentWorkflowInputV1,
        ProcessedCommandV1,
        SliceDescriptorV1,
        child_target_matches,
        compute_topological_waves,
        decide_command,
        parent_target_matches,
        validate_parent_initialization,
    )


CHILD_TERMINAL_PHASES = {
    ChildPhase.SUCCEEDED,
    ChildPhase.FAILED_RETRYABLE,
    ChildPhase.FAILED_TERMINAL,
    ChildPhase.CANCELLED,
}


@workflow.defn(name="CurveSliceAttemptWorkflowV1")
class CurveSliceAttemptWorkflowV1:
    """Coordinate one immutable, synthetic slice attempt without side effects."""

    @workflow.init
    def __init__(self, workflow_input: ChildWorkflowInputV1) -> None:
        self._input = workflow_input
        self._phase = ChildPhase.QUEUED
        self._state_version = 1
        self._processed_commands: tuple[ProcessedCommandV1, ...] = ()
        self._active_question_ref: str | None = None
        self._active_question_digest: str | None = None
        self._answer_ref: str | None = None
        self._answer_digest: str | None = None
        self._attempt_deadline: datetime | None = None
        self._question_deadline: datetime | None = None
        self._question_count = 0
        self._cancellation_requested = False
        self._failure_code: FailureCode | None = None
        self._last_rejected_command_id: str | None = None
        self._last_command_rejection_code: str | None = None

    @workflow.run
    async def run(self, workflow_input: ChildWorkflowInputV1) -> ChildResultV1:
        if not workflow.patched(CHILD_ATTEMPT_PATCH_ID):
            raise RuntimeError("CurveSliceAttemptWorkflowV1 initial patch is inactive")
        if workflow_input != self._input:
            raise RuntimeError("CurveSliceAttemptWorkflowV1 input changed after initialization")

        try:
            try:
                await workflow.wait_condition(
                    lambda: self._phase != ChildPhase.QUEUED,
                    timeout=timedelta(seconds=CHILD_START_SIGNAL_TIMEOUT_SECONDS),
                    timeout_summary="waiting for synthetic attempt start",
                )
            except asyncio.TimeoutError:
                self._set_failure(FailureCode.START_TIMEOUT)

            while self._phase not in CHILD_TERMINAL_PHASES:
                now = workflow.now()
                if self._phase == ChildPhase.WAITING_FOR_HUMAN:
                    if self._question_deadline is None:
                        raise RuntimeError("question deadline is not initialized")
                    deadline = self._question_deadline
                    timeout_failure = FailureCode.QUESTION_TIMEOUT
                else:
                    if self._attempt_deadline is None:
                        raise RuntimeError("attempt deadline is not initialized")
                    deadline = self._attempt_deadline
                    timeout_failure = FailureCode.ATTEMPT_TIMEOUT

                remaining = deadline - now
                if remaining <= timedelta(0):
                    self._set_failure(timeout_failure)
                    break

                phase_before_wait = self._phase
                state_version_before_wait = self._state_version
                try:
                    await workflow.wait_condition(
                        lambda: (self._phase != phase_before_wait or self._state_version != state_version_before_wait),
                        timeout=remaining,
                        timeout_summary="waiting for synthetic attempt command",
                    )
                except asyncio.TimeoutError:
                    self._set_failure(timeout_failure)
        except asyncio.CancelledError:
            self._cancellation_requested = True
            self._phase = ChildPhase.CANCELLED
            self._state_version += 1
            self._failure_code = None

        return self._result()

    def _set_failure(self, failure_code: FailureCode) -> None:
        self._phase = ChildPhase.FAILED_TERMINAL
        self._failure_code = failure_code
        self._active_question_ref = None
        self._active_question_digest = None
        self._question_deadline = None
        self._state_version += 1

    def _apply_command(
        self,
        command: ChildSignalV1 | ChildQuestionSignalV1 | ChildAnswerSignalV1 | ChildCompleteSignalV1,
        *,
        transition_allowed: bool,
        transition: Callable[[], None],
    ) -> None:
        decision = decide_command(
            command=command,
            processed_commands=self._processed_commands,
            state_version=self._state_version,
            target_matches=child_target_matches(command, self._input),
            transition_allowed=transition_allowed,
        )
        if decision.outcome in {CommandOutcome.CONFLICT, CommandOutcome.DUPLICATE, CommandOutcome.LIMIT_REACHED}:
            return

        self._processed_commands = decision.processed_commands
        self._state_version = decision.state_version
        if decision.outcome == CommandOutcome.REJECTED:
            self._last_rejected_command_id = command.command_id
            self._last_command_rejection_code = decision.rejection_code
            return

        self._last_rejected_command_id = None
        self._last_command_rejection_code = None
        transition()

    @workflow.signal(name="report_started")
    def report_started(self, command: ChildSignalV1) -> None:
        self._apply_command(
            command,
            transition_allowed=self._phase == ChildPhase.QUEUED,
            transition=lambda: self._set_running(),
        )

    def _set_running(self) -> None:
        self._phase = ChildPhase.RUNNING
        self._attempt_deadline = workflow.now() + timedelta(seconds=ATTEMPT_TERMINAL_TIMEOUT_SECONDS)

    @workflow.signal(name="ask_question")
    def ask_question(self, command: ChildQuestionSignalV1) -> None:
        def transition() -> None:
            self._phase = ChildPhase.WAITING_FOR_HUMAN
            self._active_question_ref = command.question_ref
            self._active_question_digest = command.question_digest
            self._answer_ref = None
            self._answer_digest = None
            self._attempt_deadline = None
            self._question_deadline = workflow.now() + timedelta(seconds=QUESTION_ANSWER_TIMEOUT_SECONDS)
            self._question_count += 1

        self._apply_command(
            command,
            transition_allowed=(self._phase == ChildPhase.RUNNING and self._question_count < MAX_QUESTIONS_PER_ATTEMPT),
            transition=transition,
        )

    @workflow.signal(name="answer_question")
    def answer_question(self, command: ChildAnswerSignalV1) -> None:
        def transition() -> None:
            self._phase = ChildPhase.RUNNING
            self._active_question_ref = None
            self._active_question_digest = None
            self._answer_ref = command.answer_ref
            self._answer_digest = command.answer_digest
            self._question_deadline = None
            self._attempt_deadline = workflow.now() + timedelta(seconds=ATTEMPT_TERMINAL_TIMEOUT_SECONDS)

        self._apply_command(
            command,
            transition_allowed=(
                self._phase == ChildPhase.WAITING_FOR_HUMAN and command.question_ref == self._active_question_ref
            ),
            transition=transition,
        )

    @workflow.signal(name="complete_attempt")
    def complete_attempt(self, command: ChildCompleteSignalV1) -> None:
        def transition() -> None:
            self._phase = ChildPhase(command.outcome)
            self._failure_code = FailureCode(command.failure_code) if command.failure_code is not None else None

        self._apply_command(
            command,
            transition_allowed=self._phase == ChildPhase.RUNNING,
            transition=transition,
        )

    @workflow.query(name="state")
    def state(self) -> ChildStateV1:
        return ChildStateV1(
            schema_version=MESSAGE_SCHEMA_VERSION,
            workspace_id=self._input.workspace_id,
            initiative_id=self._input.initiative_id,
            plan_generation=self._input.plan_generation,
            slice_id=self._input.slice_id,
            attempt_id=self._input.attempt_id,
            attempt_version=self._input.attempt_version,
            phase=self._phase,
            state_version=self._state_version,
            active_question_ref=self._active_question_ref,
            active_question_digest=self._active_question_digest,
            answer_ref=self._answer_ref,
            answer_digest=self._answer_digest,
            cancellation_requested=self._cancellation_requested,
            failure_code=self._failure_code,
            last_rejected_command_id=self._last_rejected_command_id,
            last_command_rejection_code=self._last_command_rejection_code,
        )

    def _result(self) -> ChildResultV1:
        return ChildResultV1(
            schema_version=MESSAGE_SCHEMA_VERSION,
            workspace_id=self._input.workspace_id,
            initiative_id=self._input.initiative_id,
            plan_generation=self._input.plan_generation,
            slice_id=self._input.slice_id,
            attempt_id=self._input.attempt_id,
            attempt_version=self._input.attempt_version,
            phase=self._phase,
            state_version=self._state_version,
            failure_code=self._failure_code,
        )


@workflow.defn(name="CurveInitiativeOrchestrationWorkflowV1")
class CurveInitiativeOrchestrationWorkflowV1:
    """Schedule immutable slice attempts in deterministic dependency waves."""

    @workflow.init
    def __init__(self, workflow_input: ParentWorkflowInputV1) -> None:
        self._input = workflow_input
        self._phase = ParentPhase(workflow_input.phase)
        self._state_version = workflow_input.state_version
        self._completed_slice_ids = workflow_input.completed_slice_ids
        self._failed_slice_ids = workflow_input.failed_slice_ids
        self._cancelled_slice_ids = workflow_input.cancelled_slice_ids
        self._next_wave_index = workflow_input.next_wave_index
        self._processed_commands = workflow_input.processed_commands
        self._continue_as_new_count = workflow_input.continue_as_new_count
        self._cancellation_requested = workflow_input.phase == ParentPhase.CANCEL_REQUESTED
        self._failure_code: FailureCode | None = None
        self._last_rejected_command_id = workflow_input.last_rejected_command_id
        self._last_command_rejection_code = workflow_input.last_command_rejection_code
        self._active_handles: dict[str, workflow.ChildWorkflowHandle[ChildResultV1]] = {}

    @workflow.run
    async def run(self, workflow_input: ParentWorkflowInputV1) -> ParentResultV1:
        if not workflow.patched(PARENT_ORCHESTRATION_PATCH_ID):
            raise RuntimeError("CurveInitiativeOrchestrationWorkflowV1 initial patch is inactive")
        if workflow_input != self._input:
            raise RuntimeError("CurveInitiativeOrchestrationWorkflowV1 input changed after initialization")
        validate_parent_initialization(
            workflow_input,
            continued_run_id=workflow.info().continued_run_id,
        )
        waves = compute_topological_waves(workflow_input.slices)
        waves_completed_in_run = 0

        while self._next_wave_index < len(waves):
            if self._cancellation_requested:
                self._phase = ParentPhase.CANCELLED
                self._state_version += 1
                return self._result()

            if self._phase == ParentPhase.PAUSED:
                await workflow.wait_condition(
                    lambda: self._phase != ParentPhase.PAUSED,
                    timeout_summary="waiting for initiative orchestration resume",
                )
                continue

            if self._should_continue_as_new(waves_completed_in_run):
                workflow.continue_as_new(self._continuation_input())

            wave = waves[self._next_wave_index]
            await self._start_wave(wave)
            wave_results = await self._wait_for_active_wave()
            if wave_results is None:
                return self._result()

            self._settle_wave(wave_results)
            waves_completed_in_run += 1
            if self._phase in {ParentPhase.FAILED, ParentPhase.CANCELLED}:
                return self._result()

        self._phase = ParentPhase.SUCCEEDED
        self._state_version += 1
        return self._result()

    def _should_continue_as_new(self, waves_completed_in_run: int) -> bool:
        return (
            self._phase == ParentPhase.RUNNING
            and not self._active_handles
            and workflow.all_handlers_finished()
            and (
                waves_completed_in_run >= CONTINUE_AS_NEW_WAVE_THRESHOLD
                or workflow.info().is_continue_as_new_suggested()
            )
        )

    def _continuation_input(self) -> ParentWorkflowInputV1:
        return ParentWorkflowInputV1(
            schema_version=MESSAGE_SCHEMA_VERSION,
            workspace_id=self._input.workspace_id,
            initiative_id=self._input.initiative_id,
            plan_generation=self._input.plan_generation,
            plan_digest=self._input.plan_digest,
            slices=self._input.slices,
            phase=ParentPhase.RUNNING,
            state_version=self._state_version,
            completed_slice_ids=self._completed_slice_ids,
            failed_slice_ids=self._failed_slice_ids,
            cancelled_slice_ids=self._cancelled_slice_ids,
            next_wave_index=self._next_wave_index,
            processed_commands=self._processed_commands,
            continue_as_new_count=self._continue_as_new_count + 1,
            last_rejected_command_id=self._last_rejected_command_id,
            last_command_rejection_code=self._last_command_rejection_code,
        )

    async def _start_wave(self, wave: tuple[SliceDescriptorV1, ...]) -> None:
        for descriptor in wave:
            child_input = ChildWorkflowInputV1(
                schema_version=MESSAGE_SCHEMA_VERSION,
                workspace_id=self._input.workspace_id,
                initiative_id=self._input.initiative_id,
                plan_generation=self._input.plan_generation,
                slice_id=descriptor.slice_id,
                dependency_slice_ids=descriptor.dependency_slice_ids,
                attempt_id=descriptor.attempt_id,
                attempt_version=descriptor.attempt_version,
                attempt_digest=descriptor.attempt_digest,
            )
            self._active_handles[descriptor.slice_id] = await workflow.start_child_workflow(
                CurveSliceAttemptWorkflowV1.run,
                child_input,
                id=slice_attempt_workflow_id(
                    workspace_id=self._input.workspace_id,
                    initiative_id=self._input.initiative_id,
                    plan_generation=self._input.plan_generation,
                    slice_id=descriptor.slice_id,
                    attempt_id=descriptor.attempt_id,
                ),
                task_queue=workflow.info().task_queue,
                result_type=ChildResultV1,
                cancellation_type=workflow.ChildWorkflowCancellationType.WAIT_CANCELLATION_COMPLETED,
                parent_close_policy=workflow.ParentClosePolicy.REQUEST_CANCEL,
            )
        self._state_version += 1

    async def _wait_for_active_wave(self) -> tuple[tuple[str, ChildResultV1 | BaseException], ...] | None:
        tasks = {
            slice_id: asyncio.ensure_future(self._active_handles[slice_id]) for slice_id in sorted(self._active_handles)
        }
        await workflow.wait_condition(
            lambda: self._cancellation_requested or all(task.done() for task in tasks.values()),
            timeout_summary="waiting for synthetic child wave",
        )
        if self._cancellation_requested and not all(task.done() for task in tasks.values()):
            self._cancel_active_children()
            try:
                await workflow.wait_condition(
                    lambda: all(task.done() for task in tasks.values()),
                    timeout=timedelta(seconds=PARENT_CANCEL_TIMEOUT_SECONDS),
                    timeout_summary="waiting for synthetic child cancellation",
                )
            except asyncio.TimeoutError:
                self._phase = ParentPhase.FAILED
                self._failure_code = FailureCode.CANCEL_TIMEOUT
                self._state_version += 1
                return None

        results: list[tuple[str, ChildResultV1 | BaseException]] = []
        for slice_id in sorted(tasks):
            try:
                results.append((slice_id, tasks[slice_id].result()))
            except BaseException as error:
                results.append((slice_id, error))
        self._active_handles.clear()
        return tuple(results)

    def _settle_wave(self, results: tuple[tuple[str, ChildResultV1 | BaseException], ...]) -> None:
        completed = list(self._completed_slice_ids)
        failed = list(self._failed_slice_ids)
        cancelled = list(self._cancelled_slice_ids)
        bounded_failure: FailureCode | None = None
        for slice_id, result in results:
            if isinstance(result, BaseException):
                failed.append(slice_id)
                bounded_failure = FailureCode.SYNTHETIC_FAILURE
            elif result.phase == ChildPhase.SUCCEEDED:
                completed.append(slice_id)
            elif result.phase == ChildPhase.CANCELLED:
                cancelled.append(slice_id)
            else:
                failed.append(slice_id)
                bounded_failure = FailureCode(result.failure_code or FailureCode.SYNTHETIC_FAILURE)

        self._completed_slice_ids = tuple(sorted(completed))
        self._failed_slice_ids = tuple(sorted(failed))
        self._cancelled_slice_ids = tuple(sorted(cancelled))
        self._next_wave_index += 1
        self._state_version += 1
        if self._cancellation_requested:
            self._phase = ParentPhase.CANCELLED
        elif failed:
            self._phase = ParentPhase.FAILED
            self._failure_code = bounded_failure or FailureCode.SYNTHETIC_FAILURE
        elif cancelled:
            self._phase = ParentPhase.CANCELLED

    def _apply_parent_command(
        self,
        command: ParentSignalV1 | ParentCancelSignalV1,
        *,
        transition_allowed: bool,
        transition: Callable[[], None],
    ) -> None:
        decision = decide_command(
            command=command,
            processed_commands=self._processed_commands,
            state_version=self._state_version,
            target_matches=parent_target_matches(command, self._input),
            transition_allowed=transition_allowed,
        )
        if decision.outcome in {CommandOutcome.CONFLICT, CommandOutcome.DUPLICATE, CommandOutcome.LIMIT_REACHED}:
            return
        self._processed_commands = decision.processed_commands
        self._state_version = decision.state_version
        if decision.outcome == CommandOutcome.REJECTED:
            self._last_rejected_command_id = command.command_id
            self._last_command_rejection_code = decision.rejection_code
            return
        self._last_rejected_command_id = None
        self._last_command_rejection_code = None
        transition()

    @workflow.signal(name="pause")
    def pause(self, command: ParentSignalV1) -> None:
        self._apply_parent_command(
            command,
            transition_allowed=self._phase == ParentPhase.RUNNING,
            transition=lambda: self._set_phase(ParentPhase.PAUSED),
        )

    @workflow.signal(name="resume")
    def resume(self, command: ParentSignalV1) -> None:
        self._apply_parent_command(
            command,
            transition_allowed=self._phase == ParentPhase.PAUSED,
            transition=lambda: self._set_phase(ParentPhase.RUNNING),
        )

    @workflow.signal(name="request_cancel")
    def request_cancel(self, command: ParentCancelSignalV1) -> None:
        def transition() -> None:
            self._cancellation_requested = True
            self._phase = ParentPhase.CANCEL_REQUESTED
            self._cancel_active_children()

        self._apply_parent_command(
            command,
            transition_allowed=self._phase in {ParentPhase.RUNNING, ParentPhase.PAUSED},
            transition=transition,
        )

    def _set_phase(self, phase: ParentPhase) -> None:
        self._phase = phase

    def _cancel_active_children(self) -> None:
        for slice_id in sorted(self._active_handles):
            self._active_handles[slice_id].cancel()

    @workflow.query(name="state")
    def state(self) -> ParentStateV1:
        return ParentStateV1(
            schema_version=MESSAGE_SCHEMA_VERSION,
            workspace_id=self._input.workspace_id,
            initiative_id=self._input.initiative_id,
            plan_generation=self._input.plan_generation,
            phase=self._phase,
            state_version=self._state_version,
            active_slice_ids=tuple(sorted(self._active_handles)),
            completed_slice_ids=self._completed_slice_ids,
            failed_slice_ids=self._failed_slice_ids,
            cancelled_slice_ids=self._cancelled_slice_ids,
            next_wave_index=self._next_wave_index,
            continue_as_new_count=self._continue_as_new_count,
            cancellation_requested=self._cancellation_requested,
            failure_code=self._failure_code,
            last_rejected_command_id=self._last_rejected_command_id,
            last_command_rejection_code=self._last_command_rejection_code,
        )

    def _result(self) -> ParentResultV1:
        return ParentResultV1(
            schema_version=MESSAGE_SCHEMA_VERSION,
            workspace_id=self._input.workspace_id,
            initiative_id=self._input.initiative_id,
            plan_generation=self._input.plan_generation,
            phase=self._phase,
            state_version=self._state_version,
            completed_slice_ids=self._completed_slice_ids,
            failed_slice_ids=self._failed_slice_ids,
            cancelled_slice_ids=self._cancelled_slice_ids,
            continue_as_new_count=self._continue_as_new_count,
            failure_code=self._failure_code,
        )
