# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Closed, reference-only contracts for Curve's synthetic Temporal orchestration."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable


MESSAGE_SCHEMA_VERSION = "1.0"
MAX_SLICES = 64
MAX_DEPENDENCIES_PER_SLICE = 16
MAX_PROCESSED_COMMANDS = 256
MAX_QUESTIONS_PER_ATTEMPT = 32
MAX_INTEGER = 2_147_483_647

UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
TEMPORAL_RUN_ID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
OPAQUE_REFERENCE_PATTERN = re.compile(r"^[a-z][a-z0-9._:/-]{0,127}$")


class ParentPhase(StrEnum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ChildPhase(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    CANCELLED = "CANCELLED"


class CommandDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CommandOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"
    LIMIT_REACHED = "LIMIT_REACHED"


class SignalErrorCode(StrEnum):
    COMMAND_CONFLICT = "COMMAND_CONFLICT"
    STALE_STATE_VERSION = "STALE_STATE_VERSION"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    TARGET_MISMATCH = "TARGET_MISMATCH"
    COMMAND_LIMIT_EXCEEDED = "COMMAND_LIMIT_EXCEEDED"


class ValidationErrorCode(StrEnum):
    INVALID_IDENTIFIER = "INVALID_IDENTIFIER"
    INVALID_VERSION = "INVALID_VERSION"
    INVALID_DIGEST = "INVALID_DIGEST"
    UNKNOWN_DEPENDENCY = "UNKNOWN_DEPENDENCY"
    DUPLICATE_SLICE = "DUPLICATE_SLICE"
    SELF_DEPENDENCY = "SELF_DEPENDENCY"
    CYCLIC_DEPENDENCY = "CYCLIC_DEPENDENCY"
    COLLECTION_LIMIT_EXCEEDED = "COLLECTION_LIMIT_EXCEEDED"


class FailureCode(StrEnum):
    START_TIMEOUT = "START_TIMEOUT"
    ATTEMPT_TIMEOUT = "ATTEMPT_TIMEOUT"
    QUESTION_TIMEOUT = "QUESTION_TIMEOUT"
    SYNTHETIC_FAILURE = "SYNTHETIC_FAILURE"
    CANCEL_TIMEOUT = "CANCEL_TIMEOUT"


class CompletionOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"


class CancelReasonCode(StrEnum):
    USER_REQUESTED = "USER_REQUESTED"
    POLICY_REQUESTED = "POLICY_REQUESTED"
    SUPERSEDED = "SUPERSEDED"


class OrchestrationValidationError(ValueError):
    """A bounded contract error safe to expose without payload detail."""

    def __init__(self, code: ValidationErrorCode, field_name: str) -> None:
        self.code = code
        self.field_name = field_name
        super().__init__(f"{code.value}:{field_name}")


def require_uuid(value: str, field_name: str) -> None:
    if not isinstance(value, str) or UUID_PATTERN.fullmatch(value) is None:
        raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, field_name)
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as error:
        raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, field_name) from error


def require_temporal_run_id(value: str, field_name: str) -> None:
    """Accept canonical Temporal run IDs, including server-generated UUIDv7 values."""

    if not isinstance(value, str) or TEMPORAL_RUN_ID_PATTERN.fullmatch(value) is None:
        raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, field_name)
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as error:
        raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, field_name) from error


def require_positive_integer(value: int, field_name: str) -> None:
    if type(value) is not int or not 1 <= value <= MAX_INTEGER:
        raise OrchestrationValidationError(ValidationErrorCode.INVALID_VERSION, field_name)


def require_non_negative_integer(value: int, field_name: str) -> None:
    if type(value) is not int or not 0 <= value <= MAX_INTEGER:
        raise OrchestrationValidationError(ValidationErrorCode.INVALID_VERSION, field_name)


def require_digest(value: str, field_name: str) -> None:
    if not isinstance(value, str) or DIGEST_PATTERN.fullmatch(value) is None:
        raise OrchestrationValidationError(ValidationErrorCode.INVALID_DIGEST, field_name)


def require_opaque_reference(value: str, field_name: str) -> None:
    if not isinstance(value, str) or OPAQUE_REFERENCE_PATTERN.fullmatch(value) is None:
        raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, field_name)


def require_schema_version(value: str) -> None:
    if value != MESSAGE_SCHEMA_VERSION:
        raise OrchestrationValidationError(ValidationErrorCode.INVALID_VERSION, "schema_version")


def require_optional_pair(left: str | None, right: str | None, left_name: str, right_name: str) -> None:
    if (left is None) != (right is None):
        raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, f"{left_name}/{right_name}")
    if left is not None:
        require_opaque_reference(left, left_name)
        require_digest(right, right_name)


def _normalize_tuple(value: Iterable[Any], field_name: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)):
        raise OrchestrationValidationError(ValidationErrorCode.COLLECTION_LIMIT_EXCEEDED, field_name)
    try:
        return tuple(value)
    except TypeError as error:
        raise OrchestrationValidationError(ValidationErrorCode.COLLECTION_LIMIT_EXCEEDED, field_name) from error


@dataclass(frozen=True, slots=True)
class SliceDescriptorV1:
    slice_id: str
    dependency_slice_ids: tuple[str, ...]
    attempt_id: str
    attempt_version: int
    attempt_digest: str

    def __post_init__(self) -> None:
        dependencies = _normalize_tuple(self.dependency_slice_ids, "dependency_slice_ids")
        object.__setattr__(self, "dependency_slice_ids", dependencies)
        require_uuid(self.slice_id, "slice_id")
        require_uuid(self.attempt_id, "attempt_id")
        require_positive_integer(self.attempt_version, "attempt_version")
        require_digest(self.attempt_digest, "attempt_digest")
        if len(dependencies) > MAX_DEPENDENCIES_PER_SLICE:
            raise OrchestrationValidationError(ValidationErrorCode.COLLECTION_LIMIT_EXCEEDED, "dependency_slice_ids")
        seen: set[str] = set()
        for dependency_id in dependencies:
            require_uuid(dependency_id, "dependency_slice_ids")
            if dependency_id == self.slice_id:
                raise OrchestrationValidationError(ValidationErrorCode.SELF_DEPENDENCY, "dependency_slice_ids")
            if dependency_id in seen:
                raise OrchestrationValidationError(ValidationErrorCode.DUPLICATE_SLICE, "dependency_slice_ids")
            seen.add(dependency_id)
        object.__setattr__(self, "dependency_slice_ids", tuple(sorted(dependencies)))


@dataclass(frozen=True, slots=True)
class ProcessedCommandV1:
    command_id: str
    payload_digest: str
    disposition: str
    rejection_code: str | None

    def __post_init__(self) -> None:
        require_opaque_reference(self.command_id, "command_id")
        require_digest(self.payload_digest, "payload_digest")
        if self.disposition not in {item.value for item in CommandDisposition}:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "disposition")
        if self.disposition == CommandDisposition.ACCEPTED and self.rejection_code is not None:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "rejection_code")
        if self.disposition == CommandDisposition.REJECTED and self.rejection_code not in {
            item.value for item in SignalErrorCode
        }:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "rejection_code")


@dataclass(frozen=True, slots=True)
class CommandDecisionV1:
    outcome: CommandOutcome
    payload_digest: str
    processed_commands: tuple[ProcessedCommandV1, ...]
    state_version: int
    rejection_code: str | None


def canonical_payload_digest(value: Any) -> str:
    if not dataclasses.is_dataclass(value):
        raise TypeError("canonical payload must be a dataclass")
    payload = json.dumps(
        dataclasses.asdict(value),
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=True,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def decide_command(
    *,
    command: Any,
    processed_commands: Iterable[ProcessedCommandV1],
    state_version: int,
    target_matches: bool,
    transition_allowed: bool,
) -> CommandDecisionV1:
    require_positive_integer(state_version, "state_version")
    commands = _normalize_tuple(processed_commands, "processed_commands")
    payload_digest = canonical_payload_digest(command)
    command_id = getattr(command, "command_id")
    require_opaque_reference(command_id, "command_id")

    for existing in commands:
        if existing.command_id != command_id:
            continue
        if existing.payload_digest == payload_digest:
            return CommandDecisionV1(
                outcome=CommandOutcome.DUPLICATE,
                payload_digest=payload_digest,
                processed_commands=commands,
                state_version=state_version,
                rejection_code=existing.rejection_code,
            )
        return CommandDecisionV1(
            outcome=CommandOutcome.CONFLICT,
            payload_digest=payload_digest,
            processed_commands=commands,
            state_version=state_version,
            rejection_code=SignalErrorCode.COMMAND_CONFLICT,
        )

    if len(commands) >= MAX_PROCESSED_COMMANDS:
        return CommandDecisionV1(
            outcome=CommandOutcome.LIMIT_REACHED,
            payload_digest=payload_digest,
            processed_commands=commands,
            state_version=state_version,
            rejection_code=SignalErrorCode.COMMAND_LIMIT_EXCEEDED,
        )

    expected_state_version = getattr(command, "expected_state_version")
    rejection_code: SignalErrorCode | None = None
    if not target_matches:
        rejection_code = SignalErrorCode.TARGET_MISMATCH
    elif expected_state_version != state_version:
        rejection_code = SignalErrorCode.STALE_STATE_VERSION
    elif not transition_allowed:
        rejection_code = SignalErrorCode.INVALID_TRANSITION

    disposition = CommandDisposition.REJECTED if rejection_code else CommandDisposition.ACCEPTED
    record = ProcessedCommandV1(
        command_id=command_id,
        payload_digest=payload_digest,
        disposition=disposition,
        rejection_code=rejection_code,
    )
    return CommandDecisionV1(
        outcome=CommandOutcome.REJECTED if rejection_code else CommandOutcome.ACCEPTED,
        payload_digest=payload_digest,
        processed_commands=(*commands, record),
        state_version=state_version + 1,
        rejection_code=rejection_code,
    )


@dataclass(frozen=True, slots=True)
class ParentWorkflowInputV1:
    schema_version: str
    workspace_id: str
    initiative_id: str
    plan_generation: int
    plan_digest: str
    slices: tuple[SliceDescriptorV1, ...]
    phase: str = ParentPhase.RUNNING
    state_version: int = 1
    completed_slice_ids: tuple[str, ...] = field(default_factory=tuple)
    failed_slice_ids: tuple[str, ...] = field(default_factory=tuple)
    cancelled_slice_ids: tuple[str, ...] = field(default_factory=tuple)
    next_wave_index: int = 0
    processed_commands: tuple[ProcessedCommandV1, ...] = field(default_factory=tuple)
    continue_as_new_count: int = 0
    last_rejected_command_id: str | None = None
    last_command_rejection_code: str | None = None

    def __post_init__(self) -> None:
        require_schema_version(self.schema_version)
        require_uuid(self.workspace_id, "workspace_id")
        require_uuid(self.initiative_id, "initiative_id")
        require_positive_integer(self.plan_generation, "plan_generation")
        require_digest(self.plan_digest, "plan_digest")
        object.__setattr__(self, "slices", _normalize_tuple(self.slices, "slices"))
        object.__setattr__(
            self, "completed_slice_ids", _normalize_tuple(self.completed_slice_ids, "completed_slice_ids")
        )
        object.__setattr__(self, "failed_slice_ids", _normalize_tuple(self.failed_slice_ids, "failed_slice_ids"))
        object.__setattr__(
            self, "cancelled_slice_ids", _normalize_tuple(self.cancelled_slice_ids, "cancelled_slice_ids")
        )
        object.__setattr__(self, "processed_commands", _normalize_tuple(self.processed_commands, "processed_commands"))
        if self.phase not in {item.value for item in ParentPhase}:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "phase")
        require_positive_integer(self.state_version, "state_version")
        require_non_negative_integer(self.next_wave_index, "next_wave_index")
        require_non_negative_integer(self.continue_as_new_count, "continue_as_new_count")
        if len(self.slices) > MAX_SLICES or len(self.processed_commands) > MAX_PROCESSED_COMMANDS:
            raise OrchestrationValidationError(ValidationErrorCode.COLLECTION_LIMIT_EXCEEDED, "parent_state")
        for state_field, identifiers in (
            ("completed_slice_ids", self.completed_slice_ids),
            ("failed_slice_ids", self.failed_slice_ids),
            ("cancelled_slice_ids", self.cancelled_slice_ids),
        ):
            if len(set(identifiers)) != len(identifiers):
                raise OrchestrationValidationError(ValidationErrorCode.DUPLICATE_SLICE, state_field)
            for identifier in identifiers:
                require_uuid(identifier, state_field)
        if (self.last_rejected_command_id is None) != (self.last_command_rejection_code is None):
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "last_rejection")
        if self.last_rejected_command_id is not None:
            require_opaque_reference(self.last_rejected_command_id, "last_rejected_command_id")
            if self.last_command_rejection_code not in {item.value for item in SignalErrorCode}:
                raise OrchestrationValidationError(
                    ValidationErrorCode.INVALID_IDENTIFIER, "last_command_rejection_code"
                )
        compute_topological_waves(self.slices)


def validate_parent_initialization(value: ParentWorkflowInputV1, *, continued_run_id: str | None) -> None:
    if continued_run_id is None:
        if (
            value.phase != ParentPhase.RUNNING
            or value.state_version != 1
            or value.completed_slice_ids
            or value.failed_slice_ids
            or value.cancelled_slice_ids
            or value.next_wave_index != 0
            or value.processed_commands
            or value.continue_as_new_count != 0
            or value.last_rejected_command_id is not None
            or value.last_command_rejection_code is not None
        ):
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_VERSION, "preloaded_parent_state")
        return
    require_temporal_run_id(continued_run_id, "continued_run_id")
    if value.phase != ParentPhase.RUNNING or value.continue_as_new_count < 1:
        raise OrchestrationValidationError(ValidationErrorCode.INVALID_VERSION, "continued_parent_state")


@dataclass(frozen=True, slots=True)
class ChildWorkflowInputV1:
    schema_version: str
    workspace_id: str
    initiative_id: str
    plan_generation: int
    slice_id: str
    dependency_slice_ids: tuple[str, ...]
    attempt_id: str
    attempt_version: int
    attempt_digest: str

    def __post_init__(self) -> None:
        require_schema_version(self.schema_version)
        descriptor = SliceDescriptorV1(
            slice_id=self.slice_id,
            dependency_slice_ids=self.dependency_slice_ids,
            attempt_id=self.attempt_id,
            attempt_version=self.attempt_version,
            attempt_digest=self.attempt_digest,
        )
        require_uuid(self.workspace_id, "workspace_id")
        require_uuid(self.initiative_id, "initiative_id")
        require_positive_integer(self.plan_generation, "plan_generation")
        object.__setattr__(self, "dependency_slice_ids", descriptor.dependency_slice_ids)


@dataclass(frozen=True, slots=True)
class ParentSignalV1:
    schema_version: str
    workspace_id: str
    initiative_id: str
    plan_generation: int
    command_id: str
    expected_state_version: int

    def __post_init__(self) -> None:
        _validate_parent_command(self)


@dataclass(frozen=True, slots=True)
class ParentCancelSignalV1:
    schema_version: str
    workspace_id: str
    initiative_id: str
    plan_generation: int
    command_id: str
    expected_state_version: int
    reason_code: str

    def __post_init__(self) -> None:
        _validate_parent_command(self)
        if self.reason_code not in {item.value for item in CancelReasonCode}:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "reason_code")


def _validate_parent_command(value: ParentSignalV1 | ParentCancelSignalV1) -> None:
    require_schema_version(value.schema_version)
    require_uuid(value.workspace_id, "workspace_id")
    require_uuid(value.initiative_id, "initiative_id")
    require_positive_integer(value.plan_generation, "plan_generation")
    require_opaque_reference(value.command_id, "command_id")
    require_positive_integer(value.expected_state_version, "expected_state_version")


@dataclass(frozen=True, slots=True)
class ChildSignalV1:
    schema_version: str
    workspace_id: str
    initiative_id: str
    plan_generation: int
    slice_id: str
    attempt_id: str
    attempt_version: int
    command_id: str
    expected_state_version: int

    def __post_init__(self) -> None:
        _validate_child_command(self)


@dataclass(frozen=True, slots=True)
class ChildQuestionSignalV1:
    schema_version: str
    workspace_id: str
    initiative_id: str
    plan_generation: int
    slice_id: str
    attempt_id: str
    attempt_version: int
    command_id: str
    expected_state_version: int
    question_ref: str
    question_digest: str

    def __post_init__(self) -> None:
        _validate_child_command(self)
        require_opaque_reference(self.question_ref, "question_ref")
        require_digest(self.question_digest, "question_digest")


@dataclass(frozen=True, slots=True)
class ChildAnswerSignalV1:
    schema_version: str
    workspace_id: str
    initiative_id: str
    plan_generation: int
    slice_id: str
    attempt_id: str
    attempt_version: int
    command_id: str
    expected_state_version: int
    question_ref: str
    answer_ref: str
    answer_digest: str

    def __post_init__(self) -> None:
        _validate_child_command(self)
        require_opaque_reference(self.question_ref, "question_ref")
        require_opaque_reference(self.answer_ref, "answer_ref")
        require_digest(self.answer_digest, "answer_digest")


@dataclass(frozen=True, slots=True)
class ChildCompleteSignalV1:
    schema_version: str
    workspace_id: str
    initiative_id: str
    plan_generation: int
    slice_id: str
    attempt_id: str
    attempt_version: int
    command_id: str
    expected_state_version: int
    outcome: str
    failure_code: str | None

    def __post_init__(self) -> None:
        _validate_child_command(self)
        if self.outcome not in {item.value for item in CompletionOutcome}:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "outcome")
        if self.outcome == CompletionOutcome.SUCCEEDED and self.failure_code is not None:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "failure_code")
        if self.outcome != CompletionOutcome.SUCCEEDED and self.failure_code != FailureCode.SYNTHETIC_FAILURE:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "failure_code")


def _validate_child_command(
    value: ChildSignalV1 | ChildQuestionSignalV1 | ChildAnswerSignalV1 | ChildCompleteSignalV1,
) -> None:
    require_schema_version(value.schema_version)
    require_uuid(value.workspace_id, "workspace_id")
    require_uuid(value.initiative_id, "initiative_id")
    require_positive_integer(value.plan_generation, "plan_generation")
    require_uuid(value.slice_id, "slice_id")
    require_uuid(value.attempt_id, "attempt_id")
    require_positive_integer(value.attempt_version, "attempt_version")
    require_opaque_reference(value.command_id, "command_id")
    require_positive_integer(value.expected_state_version, "expected_state_version")


@dataclass(frozen=True, slots=True)
class ParentStateV1:
    schema_version: str
    workspace_id: str
    initiative_id: str
    plan_generation: int
    phase: str
    state_version: int
    active_slice_ids: tuple[str, ...]
    completed_slice_ids: tuple[str, ...]
    failed_slice_ids: tuple[str, ...]
    cancelled_slice_ids: tuple[str, ...]
    next_wave_index: int
    continue_as_new_count: int
    cancellation_requested: bool
    failure_code: str | None
    last_rejected_command_id: str | None
    last_command_rejection_code: str | None

    def __post_init__(self) -> None:
        require_schema_version(self.schema_version)
        require_uuid(self.workspace_id, "workspace_id")
        require_uuid(self.initiative_id, "initiative_id")
        require_positive_integer(self.plan_generation, "plan_generation")
        require_positive_integer(self.state_version, "state_version")
        require_non_negative_integer(self.next_wave_index, "next_wave_index")
        require_non_negative_integer(self.continue_as_new_count, "continue_as_new_count")
        if self.phase not in {item.value for item in ParentPhase} or type(self.cancellation_requested) is not bool:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "parent_state")
        for field_name in (
            "active_slice_ids",
            "completed_slice_ids",
            "failed_slice_ids",
            "cancelled_slice_ids",
        ):
            values = _normalize_tuple(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, values)
            if len(set(values)) != len(values):
                raise OrchestrationValidationError(ValidationErrorCode.DUPLICATE_SLICE, field_name)
            for value in values:
                require_uuid(value, field_name)
        if self.phase == ParentPhase.FAILED:
            if self.failure_code not in {item.value for item in FailureCode}:
                raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "failure_code")
        elif self.failure_code is not None:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "failure_code")
        _validate_last_rejection(self.last_rejected_command_id, self.last_command_rejection_code)


@dataclass(frozen=True, slots=True)
class ParentResultV1:
    schema_version: str
    workspace_id: str
    initiative_id: str
    plan_generation: int
    phase: str
    state_version: int
    completed_slice_ids: tuple[str, ...]
    failed_slice_ids: tuple[str, ...]
    cancelled_slice_ids: tuple[str, ...]
    continue_as_new_count: int
    failure_code: str | None

    def __post_init__(self) -> None:
        require_schema_version(self.schema_version)
        require_uuid(self.workspace_id, "workspace_id")
        require_uuid(self.initiative_id, "initiative_id")
        require_positive_integer(self.plan_generation, "plan_generation")
        require_positive_integer(self.state_version, "state_version")
        require_non_negative_integer(self.continue_as_new_count, "continue_as_new_count")
        if self.phase not in {ParentPhase.SUCCEEDED, ParentPhase.FAILED, ParentPhase.CANCELLED}:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "phase")
        for field_name in ("completed_slice_ids", "failed_slice_ids", "cancelled_slice_ids"):
            values = _normalize_tuple(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, values)
            for value in values:
                require_uuid(value, field_name)
        if self.phase == ParentPhase.FAILED:
            if self.failure_code not in {item.value for item in FailureCode}:
                raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "failure_code")
        elif self.failure_code is not None:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "failure_code")


@dataclass(frozen=True, slots=True)
class ChildStateV1:
    schema_version: str
    workspace_id: str
    initiative_id: str
    plan_generation: int
    slice_id: str
    attempt_id: str
    attempt_version: int
    phase: str
    state_version: int
    active_question_ref: str | None
    active_question_digest: str | None
    answer_ref: str | None
    answer_digest: str | None
    cancellation_requested: bool
    failure_code: str | None
    last_rejected_command_id: str | None
    last_command_rejection_code: str | None

    def __post_init__(self) -> None:
        require_schema_version(self.schema_version)
        require_uuid(self.workspace_id, "workspace_id")
        require_uuid(self.initiative_id, "initiative_id")
        require_uuid(self.slice_id, "slice_id")
        require_uuid(self.attempt_id, "attempt_id")
        require_positive_integer(self.plan_generation, "plan_generation")
        require_positive_integer(self.attempt_version, "attempt_version")
        require_positive_integer(self.state_version, "state_version")
        if self.phase not in {item.value for item in ChildPhase} or type(self.cancellation_requested) is not bool:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "child_state")
        require_optional_pair(
            self.active_question_ref,
            self.active_question_digest,
            "active_question_ref",
            "active_question_digest",
        )
        require_optional_pair(self.answer_ref, self.answer_digest, "answer_ref", "answer_digest")
        if self.phase == ChildPhase.WAITING_FOR_HUMAN and self.active_question_ref is None:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "active_question_ref")
        if self.phase != ChildPhase.WAITING_FOR_HUMAN and self.active_question_ref is not None:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "active_question_ref")
        if self.phase in {ChildPhase.FAILED_RETRYABLE, ChildPhase.FAILED_TERMINAL}:
            if self.failure_code not in {item.value for item in FailureCode}:
                raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "failure_code")
        elif self.failure_code is not None:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "failure_code")
        _validate_last_rejection(self.last_rejected_command_id, self.last_command_rejection_code)


@dataclass(frozen=True, slots=True)
class ChildResultV1:
    schema_version: str
    workspace_id: str
    initiative_id: str
    plan_generation: int
    slice_id: str
    attempt_id: str
    attempt_version: int
    phase: str
    state_version: int
    failure_code: str | None

    def __post_init__(self) -> None:
        require_schema_version(self.schema_version)
        require_uuid(self.workspace_id, "workspace_id")
        require_uuid(self.initiative_id, "initiative_id")
        require_uuid(self.slice_id, "slice_id")
        require_uuid(self.attempt_id, "attempt_id")
        require_positive_integer(self.plan_generation, "plan_generation")
        require_positive_integer(self.attempt_version, "attempt_version")
        require_positive_integer(self.state_version, "state_version")
        if self.phase not in {
            ChildPhase.SUCCEEDED,
            ChildPhase.FAILED_RETRYABLE,
            ChildPhase.FAILED_TERMINAL,
            ChildPhase.CANCELLED,
        }:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "phase")
        if self.phase in {ChildPhase.FAILED_RETRYABLE, ChildPhase.FAILED_TERMINAL}:
            if self.failure_code not in {item.value for item in FailureCode}:
                raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "failure_code")
        elif self.failure_code is not None:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "failure_code")


def _validate_last_rejection(command_id: str | None, rejection_code: str | None) -> None:
    if (command_id is None) != (rejection_code is None):
        raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "last_rejection")
    if command_id is not None:
        require_opaque_reference(command_id, "last_rejected_command_id")
        if rejection_code not in {item.value for item in SignalErrorCode}:
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "last_command_rejection_code")


def compute_topological_waves(slices: Iterable[SliceDescriptorV1]) -> tuple[tuple[SliceDescriptorV1, ...], ...]:
    descriptors = _normalize_tuple(slices, "slices")
    if len(descriptors) > MAX_SLICES:
        raise OrchestrationValidationError(ValidationErrorCode.COLLECTION_LIMIT_EXCEEDED, "slices")
    by_id: dict[str, SliceDescriptorV1] = {}
    for descriptor in descriptors:
        if not isinstance(descriptor, SliceDescriptorV1):
            raise OrchestrationValidationError(ValidationErrorCode.INVALID_IDENTIFIER, "slices")
        if descriptor.slice_id in by_id:
            raise OrchestrationValidationError(ValidationErrorCode.DUPLICATE_SLICE, "slices")
        by_id[descriptor.slice_id] = descriptor
    for descriptor in descriptors:
        if any(dependency_id not in by_id for dependency_id in descriptor.dependency_slice_ids):
            raise OrchestrationValidationError(ValidationErrorCode.UNKNOWN_DEPENDENCY, "dependency_slice_ids")

    remaining = set(by_id)
    completed: set[str] = set()
    waves: list[tuple[SliceDescriptorV1, ...]] = []
    while remaining:
        wave_ids = sorted(
            slice_id for slice_id in remaining if set(by_id[slice_id].dependency_slice_ids).issubset(completed)
        )
        if not wave_ids:
            raise OrchestrationValidationError(ValidationErrorCode.CYCLIC_DEPENDENCY, "slices")
        waves.append(tuple(by_id[slice_id] for slice_id in wave_ids))
        remaining.difference_update(wave_ids)
        completed.update(wave_ids)
    return tuple(waves)


def parent_target_matches(command: ParentSignalV1 | ParentCancelSignalV1, value: ParentWorkflowInputV1) -> bool:
    return (
        command.workspace_id == value.workspace_id
        and command.initiative_id == value.initiative_id
        and command.plan_generation == value.plan_generation
    )


def child_target_matches(
    command: ChildSignalV1 | ChildQuestionSignalV1 | ChildAnswerSignalV1 | ChildCompleteSignalV1,
    value: ChildWorkflowInputV1,
) -> bool:
    return (
        command.workspace_id == value.workspace_id
        and command.initiative_id == value.initiative_id
        and command.plan_generation == value.plan_generation
        and command.slice_id == value.slice_id
        and command.attempt_id == value.attempt_id
        and command.attempt_version == value.attempt_version
    )
