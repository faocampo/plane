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
        QUESTION_ANSWER_TIMEOUT_SECONDS,
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
        ProcessedCommandV1,
        child_target_matches,
        decide_command,
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
