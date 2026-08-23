# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import dataclasses
import uuid

import pytest

from plane.curve.temporal.orchestration_contracts import (
    ChildCompleteSignalV1,
    ChildPhase,
    ChildStateV1,
    CommandDisposition,
    CommandOutcome,
    FailureCode,
    MAX_PROCESSED_COMMANDS,
    OrchestrationValidationError,
    ParentPhase,
    ParentSignalV1,
    ParentWorkflowInputV1,
    ProcessedCommandV1,
    SignalErrorCode,
    SliceDescriptorV1,
    ValidationErrorCode,
    canonical_payload_digest,
    compute_topological_waves,
    decide_command,
    validate_parent_initialization,
)


pytestmark = pytest.mark.unit

WORKSPACE_ID = "00000000-0000-4000-8000-000000000001"
INITIATIVE_ID = "00000000-0000-4000-8000-000000000002"
ROOT_A_ID = "00000000-0000-4000-8000-000000000101"
ROOT_B_ID = "00000000-0000-4000-8000-000000000102"
DEPENDENT_ID = "00000000-0000-4000-8000-000000000103"
ATTEMPT_A_ID = "00000000-0000-4000-8000-000000000201"
ATTEMPT_B_ID = "00000000-0000-4000-8000-000000000202"
ATTEMPT_C_ID = "00000000-0000-4000-8000-000000000203"
DIGEST_A = f"sha256:{'1' * 64}"
DIGEST_B = f"sha256:{'2' * 64}"
DIGEST_C = f"sha256:{'3' * 64}"


def _slice(
    slice_id=ROOT_A_ID,
    *,
    dependencies=(),
    attempt_id=ATTEMPT_A_ID,
    attempt_digest=DIGEST_A,
):
    return SliceDescriptorV1(
        slice_id=slice_id,
        dependency_slice_ids=dependencies,
        attempt_id=attempt_id,
        attempt_version=1,
        attempt_digest=attempt_digest,
    )


def _parent_input(*, slices=None, **overrides):
    values = {
        "schema_version": "1.0",
        "workspace_id": WORKSPACE_ID,
        "initiative_id": INITIATIVE_ID,
        "plan_generation": 1,
        "plan_digest": DIGEST_A,
        "slices": tuple(slices if slices is not None else (_slice(),)),
    }
    values.update(overrides)
    return ParentWorkflowInputV1(**values)


def _parent_command(**overrides):
    values = {
        "schema_version": "1.0",
        "workspace_id": WORKSPACE_ID,
        "initiative_id": INITIATIVE_ID,
        "plan_generation": 1,
        "command_id": "command:pause:1",
        "expected_state_version": 1,
    }
    values.update(overrides)
    return ParentSignalV1(**values)


def test_m0_s6a_at_01_graph_sorts_independent_roots_before_dependent_slice():
    root_b = _slice(ROOT_B_ID, attempt_id=ATTEMPT_B_ID, attempt_digest=DIGEST_B)
    dependent = _slice(
        DEPENDENT_ID,
        dependencies=(ROOT_B_ID, ROOT_A_ID),
        attempt_id=ATTEMPT_C_ID,
        attempt_digest=DIGEST_C,
    )

    waves = compute_topological_waves((dependent, root_b, _slice()))

    assert tuple(item.slice_id for item in waves[0]) == (ROOT_A_ID, ROOT_B_ID)
    assert tuple(item.slice_id for item in waves[1]) == (DEPENDENT_ID,)
    assert dependent.dependency_slice_ids == (ROOT_A_ID, ROOT_B_ID)


@pytest.mark.parametrize(
    ("slices", "code"),
    [
        ((_slice(), _slice()), ValidationErrorCode.DUPLICATE_SLICE),
        (
            (
                _slice(
                    ROOT_A_ID,
                    dependencies=(ROOT_B_ID,),
                ),
            ),
            ValidationErrorCode.UNKNOWN_DEPENDENCY,
        ),
        (
            (
                _slice(ROOT_A_ID, dependencies=(ROOT_B_ID,)),
                _slice(ROOT_B_ID, dependencies=(ROOT_A_ID,), attempt_id=ATTEMPT_B_ID, attempt_digest=DIGEST_B),
            ),
            ValidationErrorCode.CYCLIC_DEPENDENCY,
        ),
    ],
)
def test_m0_s6a_at_02_graph_rejects_invalid_slice_sets(slices, code):
    with pytest.raises(OrchestrationValidationError) as error:
        compute_topological_waves(slices)

    assert error.value.code == code


def test_m0_s6a_at_02_slice_rejects_self_dependency_and_dependency_limit():
    with pytest.raises(OrchestrationValidationError) as self_error:
        _slice(dependencies=(ROOT_A_ID,))
    assert self_error.value.code == ValidationErrorCode.SELF_DEPENDENCY

    dependencies = tuple(str(uuid.uuid4()) for _ in range(17))
    with pytest.raises(OrchestrationValidationError) as limit_error:
        _slice(dependencies=dependencies)
    assert limit_error.value.code == ValidationErrorCode.COLLECTION_LIMIT_EXCEEDED


@pytest.mark.parametrize(
    "overrides",
    [
        {"workspace_id": "NOT-A-UUID"},
        {"plan_generation": 0},
        {"plan_digest": "sha256:ABC"},
        {"schema_version": "2.0"},
    ],
)
def test_parent_input_rejects_non_canonical_primitives(overrides):
    with pytest.raises(OrchestrationValidationError):
        _parent_input(**overrides)


def test_new_execution_rejects_preloaded_lifecycle_state():
    forged = _parent_input(phase=ParentPhase.SUCCEEDED)

    with pytest.raises(OrchestrationValidationError, match="preloaded_parent_state"):
        validate_parent_initialization(forged, continued_run_id=None)


def test_continued_execution_requires_server_run_id_and_monotonic_counter():
    continued = _parent_input(continue_as_new_count=1, state_version=7)
    validate_parent_initialization(
        continued,
        continued_run_id="00000000-0000-4000-8000-000000000999",
    )

    with pytest.raises(OrchestrationValidationError, match="continued_parent_state"):
        validate_parent_initialization(_parent_input(), continued_run_id="00000000-0000-4000-8000-000000000999")


def test_m0_s6a_at_04_accepted_command_is_recorded_once_and_duplicate_is_noop():
    command = _parent_command()
    accepted = decide_command(
        command=command,
        processed_commands=(),
        state_version=1,
        target_matches=True,
        transition_allowed=True,
    )

    duplicate = decide_command(
        command=command,
        processed_commands=accepted.processed_commands,
        state_version=accepted.state_version,
        target_matches=True,
        transition_allowed=False,
    )

    assert accepted.outcome == CommandOutcome.ACCEPTED
    assert accepted.state_version == 2
    assert accepted.processed_commands[0].disposition == CommandDisposition.ACCEPTED
    assert duplicate.outcome == CommandOutcome.DUPLICATE
    assert duplicate.state_version == 2
    assert duplicate.processed_commands == accepted.processed_commands


def test_m0_s6a_at_04_rejected_command_is_idempotent_and_conflict_changes_nothing():
    stale = _parent_command(expected_state_version=7)
    rejected = decide_command(
        command=stale,
        processed_commands=(),
        state_version=1,
        target_matches=True,
        transition_allowed=True,
    )
    conflicting = dataclasses.replace(stale, expected_state_version=8)
    conflict = decide_command(
        command=conflicting,
        processed_commands=rejected.processed_commands,
        state_version=rejected.state_version,
        target_matches=True,
        transition_allowed=True,
    )

    assert rejected.outcome == CommandOutcome.REJECTED
    assert rejected.rejection_code == SignalErrorCode.STALE_STATE_VERSION
    assert rejected.state_version == 2
    assert rejected.processed_commands[0].disposition == CommandDisposition.REJECTED
    assert conflict.outcome == CommandOutcome.CONFLICT
    assert conflict.rejection_code == SignalErrorCode.COMMAND_CONFLICT
    assert conflict.state_version == rejected.state_version
    assert conflict.processed_commands == rejected.processed_commands


def test_command_limit_fails_closed_without_unbounded_history_growth():
    records = tuple(
        ProcessedCommandV1(
            command_id=f"command:{index}",
            payload_digest=f"sha256:{index:064x}",
            disposition=CommandDisposition.ACCEPTED,
            rejection_code=None,
        )
        for index in range(MAX_PROCESSED_COMMANDS)
    )

    decision = decide_command(
        command=_parent_command(command_id="command:overflow"),
        processed_commands=records,
        state_version=MAX_PROCESSED_COMMANDS + 1,
        target_matches=True,
        transition_allowed=True,
    )

    assert decision.outcome == CommandOutcome.LIMIT_REACHED
    assert decision.rejection_code == SignalErrorCode.COMMAND_LIMIT_EXCEEDED
    assert len(decision.processed_commands) == MAX_PROCESSED_COMMANDS
    assert decision.state_version == MAX_PROCESSED_COMMANDS + 1


def test_complete_signal_requires_bounded_outcome_and_failure_code_pair():
    values = {
        "schema_version": "1.0",
        "workspace_id": WORKSPACE_ID,
        "initiative_id": INITIATIVE_ID,
        "plan_generation": 1,
        "slice_id": ROOT_A_ID,
        "attempt_id": ATTEMPT_A_ID,
        "attempt_version": 1,
        "command_id": "command:complete:1",
        "expected_state_version": 2,
        "outcome": ChildPhase.FAILED_TERMINAL,
        "failure_code": FailureCode.SYNTHETIC_FAILURE,
    }
    command = ChildCompleteSignalV1(**values)
    assert canonical_payload_digest(command).startswith("sha256:")

    with pytest.raises(OrchestrationValidationError):
        ChildCompleteSignalV1(**{**values, "outcome": ChildPhase.SUCCEEDED})


def test_child_state_enforces_lifecycle_dependent_question_and_failure_fields():
    values = {
        "schema_version": "1.0",
        "workspace_id": WORKSPACE_ID,
        "initiative_id": INITIATIVE_ID,
        "plan_generation": 1,
        "slice_id": ROOT_A_ID,
        "attempt_id": ATTEMPT_A_ID,
        "attempt_version": 1,
        "phase": ChildPhase.WAITING_FOR_HUMAN,
        "state_version": 3,
        "active_question_ref": "object:question:1",
        "active_question_digest": DIGEST_A,
        "answer_ref": None,
        "answer_digest": None,
        "cancellation_requested": False,
        "failure_code": None,
        "last_rejected_command_id": None,
        "last_command_rejection_code": None,
    }
    ChildStateV1(**values)

    with pytest.raises(OrchestrationValidationError):
        ChildStateV1(**{**values, "active_question_digest": None})
    with pytest.raises(OrchestrationValidationError):
        ChildStateV1(**{**values, "phase": ChildPhase.RUNNING})
