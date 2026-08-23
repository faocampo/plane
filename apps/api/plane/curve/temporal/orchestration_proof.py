# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import argparse
import asyncio
import hashlib
import json
import os
import uuid

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.worker import Replayer

from plane.curve.temporal.constants import (
    TASK_QUEUE,
    initiative_workflow_id,
    slice_attempt_workflow_id,
)
from plane.curve.temporal.orchestration_contracts import (
    MESSAGE_SCHEMA_VERSION,
    ChildAnswerSignalV1,
    ChildCompleteSignalV1,
    ChildPhase,
    ChildQuestionSignalV1,
    ChildSignalV1,
    ChildWorkflowInputV1,
    ParentCancelSignalV1,
    ParentPhase,
    ParentWorkflowInputV1,
    SliceDescriptorV1,
)
from plane.curve.temporal.orchestration_workflows import (
    CurveInitiativeOrchestrationWorkflowV1,
    CurveSliceAttemptWorkflowV1,
)
from plane.curve.temporal.registry import CURVE_WORKFLOWS_V1


SENTINEL = "CURVE_PROTECTED_SENTINEL_M0_S6A"
DIGEST = f"sha256:{'6' * 64}"
PLAN_GENERATION = 1


def _derived_uuid(proof_id: uuid.UUID, label: str) -> str:
    return str(uuid.uuid5(proof_id, label))


def _proof_identity(proof_id: uuid.UUID) -> dict[str, str]:
    return {
        "workspace_id": _derived_uuid(proof_id, "workspace"),
        "initiative_id": _derived_uuid(proof_id, "initiative"),
        "slice_id": _derived_uuid(proof_id, "slice:0"),
        "attempt_id": _derived_uuid(proof_id, "attempt:0"),
    }


async def _client() -> Client:
    return await Client.connect(
        os.environ["TEMPORAL_ADDRESS"],
        namespace=os.environ["TEMPORAL_NAMESPACE"],
    )


async def _wait_for_state(handle, query, predicate, *, attempts: int = 300):
    for _ in range(attempts):
        state = await handle.query(query)
        if predicate(state):
            return state
        await asyncio.sleep(0.1)
    raise TimeoutError("synthetic orchestration did not reach its expected state")


async def _history_evidence(handle) -> tuple[str, bool]:
    history = await handle.fetch_history()
    history_json = history.to_json()
    if SENTINEL in history_json:
        raise RuntimeError("protected sentinel leaked into Temporal history")
    await Replayer(workflows=CURVE_WORKFLOWS_V1).replay_workflow(history)
    return hashlib.sha256(history_json.encode()).hexdigest(), True


def _child_input(identity: dict[str, str]) -> ChildWorkflowInputV1:
    return ChildWorkflowInputV1(
        schema_version=MESSAGE_SCHEMA_VERSION,
        workspace_id=identity["workspace_id"],
        initiative_id=identity["initiative_id"],
        plan_generation=PLAN_GENERATION,
        slice_id=identity["slice_id"],
        dependency_slice_ids=(),
        attempt_id=identity["attempt_id"],
        attempt_version=1,
        attempt_digest=DIGEST,
    )


def _child_signal(identity: dict[str, str], *, command_id: str, expected_state_version: int) -> dict:
    return {
        "schema_version": MESSAGE_SCHEMA_VERSION,
        "workspace_id": identity["workspace_id"],
        "initiative_id": identity["initiative_id"],
        "plan_generation": PLAN_GENERATION,
        "slice_id": identity["slice_id"],
        "attempt_id": identity["attempt_id"],
        "attempt_version": 1,
        "command_id": command_id,
        "expected_state_version": expected_state_version,
    }


async def prepare_restart_proof() -> dict:
    proof_id = uuid.uuid4()
    identity = _proof_identity(proof_id)
    workflow_id = slice_attempt_workflow_id(
        workspace_id=identity["workspace_id"],
        initiative_id=identity["initiative_id"],
        plan_generation=PLAN_GENERATION,
        slice_id=identity["slice_id"],
        attempt_id=identity["attempt_id"],
    )
    client = await _client()
    handle = await client.start_workflow(
        CurveSliceAttemptWorkflowV1.run,
        _child_input(identity),
        id=workflow_id,
        task_queue=TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
    )
    await handle.signal(
        CurveSliceAttemptWorkflowV1.report_started,
        ChildSignalV1(
            **_child_signal(
                identity,
                command_id=f"command:restart:start:{proof_id}",
                expected_state_version=1,
            )
        ),
    )
    question_ref = f"object:question:{proof_id}"
    await handle.signal(
        CurveSliceAttemptWorkflowV1.ask_question,
        ChildQuestionSignalV1(
            **_child_signal(
                identity,
                command_id=f"command:restart:question:{proof_id}",
                expected_state_version=2,
            ),
            question_ref=question_ref,
            question_digest=DIGEST,
        ),
    )
    state = await _wait_for_state(
        handle,
        CurveSliceAttemptWorkflowV1.state,
        lambda value: value.phase == ChildPhase.WAITING_FOR_HUMAN,
    )
    return {
        "schema_version": "curve-m0-s6a-restart-proof/v1",
        "phase": "PREPARED",
        "proof_id": str(proof_id),
        "workflow_id": workflow_id,
        "workflow_phase": state.phase,
        "state_version": state.state_version,
        "processed_command_count": state.state_version - 1,
    }


async def verify_restart_proof(proof_id: uuid.UUID) -> dict:
    identity = _proof_identity(proof_id)
    workflow_id = slice_attempt_workflow_id(
        workspace_id=identity["workspace_id"],
        initiative_id=identity["initiative_id"],
        plan_generation=PLAN_GENERATION,
        slice_id=identity["slice_id"],
        attempt_id=identity["attempt_id"],
    )
    client = await _client()
    handle = client.get_workflow_handle_for(CurveSliceAttemptWorkflowV1.run, workflow_id)
    waiting = await handle.query(CurveSliceAttemptWorkflowV1.state)
    if waiting.phase != ChildPhase.WAITING_FOR_HUMAN or waiting.state_version != 3:
        raise RuntimeError("restarted child did not recover its waiting state exactly")
    await handle.signal(
        CurveSliceAttemptWorkflowV1.answer_question,
        ChildAnswerSignalV1(
            **_child_signal(
                identity,
                command_id=f"command:restart:answer:{proof_id}",
                expected_state_version=waiting.state_version,
            ),
            question_ref=f"object:question:{proof_id}",
            answer_ref=f"object:answer:{proof_id}",
            answer_digest=DIGEST,
        ),
    )
    running = await _wait_for_state(
        handle,
        CurveSliceAttemptWorkflowV1.state,
        lambda value: value.phase == ChildPhase.RUNNING and value.state_version == 4,
    )
    await handle.signal(
        CurveSliceAttemptWorkflowV1.complete_attempt,
        ChildCompleteSignalV1(
            **_child_signal(
                identity,
                command_id=f"command:restart:complete:{proof_id}",
                expected_state_version=running.state_version,
            ),
            outcome=ChildPhase.SUCCEEDED,
            failure_code=None,
        ),
    )
    result = await handle.result()
    history_sha256, replay_passed = await _history_evidence(handle)
    if result.phase != ChildPhase.SUCCEEDED or result.state_version != 5:
        raise RuntimeError("restarted child produced an unexpected terminal result")
    return {
        "schema_version": "curve-m0-s6a-restart-proof/v1",
        "phase": "VERIFIED",
        "proof_id": str(proof_id),
        "workflow_id": workflow_id,
        "workflow_phase": result.phase,
        "state_version": result.state_version,
        "processed_command_count": 4,
        "history_sha256": history_sha256,
        "history_replay_passed": replay_passed,
        "sentinel_absent_from_history": True,
        "duplicate_command_absent": True,
    }


def _slice(proof_id: uuid.UUID, index: int, dependency_slice_ids: tuple[str, ...] = ()) -> SliceDescriptorV1:
    return SliceDescriptorV1(
        slice_id=_derived_uuid(proof_id, f"slice:{index}"),
        dependency_slice_ids=dependency_slice_ids,
        attempt_id=_derived_uuid(proof_id, f"attempt:{index}"),
        attempt_version=1,
        attempt_digest=DIGEST,
    )


def _parent_input(proof_id: uuid.UUID, slices: tuple[SliceDescriptorV1, ...]) -> ParentWorkflowInputV1:
    identity = _proof_identity(proof_id)
    return ParentWorkflowInputV1(
        schema_version=MESSAGE_SCHEMA_VERSION,
        workspace_id=identity["workspace_id"],
        initiative_id=identity["initiative_id"],
        plan_generation=PLAN_GENERATION,
        plan_digest=DIGEST,
        slices=slices,
    )


async def _complete_child(client: Client, parent_input: ParentWorkflowInputV1, descriptor: SliceDescriptorV1) -> None:
    identity = {
        "workspace_id": parent_input.workspace_id,
        "initiative_id": parent_input.initiative_id,
        "slice_id": descriptor.slice_id,
        "attempt_id": descriptor.attempt_id,
    }
    workflow_id = slice_attempt_workflow_id(
        workspace_id=parent_input.workspace_id,
        initiative_id=parent_input.initiative_id,
        plan_generation=parent_input.plan_generation,
        slice_id=descriptor.slice_id,
        attempt_id=descriptor.attempt_id,
    )
    handle = client.get_workflow_handle_for(CurveSliceAttemptWorkflowV1.run, workflow_id)
    await handle.signal(
        CurveSliceAttemptWorkflowV1.report_started,
        ChildSignalV1(
            **_child_signal(
                identity,
                command_id=f"command:parent:start:{descriptor.slice_id}",
                expected_state_version=1,
            )
        ),
    )
    await handle.signal(
        CurveSliceAttemptWorkflowV1.complete_attempt,
        ChildCompleteSignalV1(
            **_child_signal(
                identity,
                command_id=f"command:parent:complete:{descriptor.slice_id}",
                expected_state_version=2,
            ),
            outcome=ChildPhase.SUCCEEDED,
            failure_code=None,
        ),
    )


async def run_cancel_proof() -> dict:
    proof_id = uuid.uuid4()
    identity = _proof_identity(proof_id)
    slices = (_slice(proof_id, 0), _slice(proof_id, 1))
    parent_input = _parent_input(proof_id, slices)
    workflow_id = initiative_workflow_id(
        workspace_id=identity["workspace_id"],
        initiative_id=identity["initiative_id"],
        plan_generation=PLAN_GENERATION,
    )
    client = await _client()
    handle = await client.start_workflow(
        CurveInitiativeOrchestrationWorkflowV1.run,
        parent_input,
        id=workflow_id,
        task_queue=TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
    )
    active = await _wait_for_state(
        handle,
        CurveInitiativeOrchestrationWorkflowV1.state,
        lambda value: len(value.active_slice_ids) == 2,
    )
    await handle.signal(
        CurveInitiativeOrchestrationWorkflowV1.request_cancel,
        ParentCancelSignalV1(
            schema_version=MESSAGE_SCHEMA_VERSION,
            workspace_id=parent_input.workspace_id,
            initiative_id=parent_input.initiative_id,
            plan_generation=PLAN_GENERATION,
            command_id=f"command:parent:cancel:{proof_id}",
            expected_state_version=active.state_version,
            reason_code="USER_REQUESTED",
        ),
    )
    result = await handle.result()
    history_sha256, replay_passed = await _history_evidence(handle)
    if result.phase != ParentPhase.CANCELLED or result.cancelled_slice_ids != tuple(
        sorted(item.slice_id for item in slices)
    ):
        raise RuntimeError("parent cancellation did not settle every child")
    return {
        "schema_version": "curve-m0-s6a-cancel-proof/v1",
        "proof_id": str(proof_id),
        "workflow_id": workflow_id,
        "workflow_phase": result.phase,
        "cancelled_slice_count": len(result.cancelled_slice_ids),
        "active_slice_count": 0,
        "history_sha256": history_sha256,
        "history_replay_passed": replay_passed,
        "sentinel_absent_from_history": True,
    }


async def run_continue_as_new_proof() -> dict:
    proof_id = uuid.uuid4()
    identity = _proof_identity(proof_id)
    descriptors: list[SliceDescriptorV1] = []
    for index in range(11):
        dependencies = () if index == 0 else (descriptors[-1].slice_id,)
        descriptors.append(_slice(proof_id, index, dependencies))
    parent_input = _parent_input(proof_id, tuple(descriptors))
    workflow_id = initiative_workflow_id(
        workspace_id=identity["workspace_id"],
        initiative_id=identity["initiative_id"],
        plan_generation=PLAN_GENERATION,
    )
    client = await _client()
    handle = await client.start_workflow(
        CurveInitiativeOrchestrationWorkflowV1.run,
        parent_input,
        id=workflow_id,
        task_queue=TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
    )
    for descriptor in descriptors:
        current = client.get_workflow_handle_for(CurveInitiativeOrchestrationWorkflowV1.run, workflow_id)
        await _wait_for_state(
            current,
            CurveInitiativeOrchestrationWorkflowV1.state,
            lambda value, slice_id=descriptor.slice_id: value.active_slice_ids == (slice_id,),
        )
        await _complete_child(client, parent_input, descriptor)

    result = await handle.result()
    current = client.get_workflow_handle_for(CurveInitiativeOrchestrationWorkflowV1.run, workflow_id)
    history_sha256, replay_passed = await _history_evidence(current)
    if (
        result.phase != ParentPhase.SUCCEEDED
        or result.continue_as_new_count != 1
        or result.completed_slice_ids != tuple(sorted(item.slice_id for item in descriptors))
    ):
        raise RuntimeError("continue-as-new did not preserve exact orchestration state")
    return {
        "schema_version": "curve-m0-s6a-continue-proof/v1",
        "proof_id": str(proof_id),
        "workflow_id": workflow_id,
        "workflow_phase": result.phase,
        "continue_as_new_count": result.continue_as_new_count,
        "completed_slice_count": len(result.completed_slice_ids),
        "history_sha256": history_sha256,
        "history_replay_passed": replay_passed,
        "sentinel_absent_from_history": True,
        "duplicate_child_absent": True,
    }


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("prepare-restart")
    verify_parser = subcommands.add_parser("verify-restart")
    verify_parser.add_argument("proof_id", type=uuid.UUID)
    subcommands.add_parser("run-cancel")
    subcommands.add_parser("run-continue-as-new")
    return parser


def main() -> None:
    args = _argument_parser().parse_args()
    if args.command == "prepare-restart":
        output = asyncio.run(prepare_restart_proof())
    elif args.command == "verify-restart":
        output = asyncio.run(verify_restart_proof(args.proof_id))
    elif args.command == "run-cancel":
        output = asyncio.run(run_cancel_proof())
    else:
        output = asyncio.run(run_continue_as_new_proof())
    print(json.dumps(output, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
