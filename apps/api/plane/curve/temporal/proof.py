# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import argparse
import asyncio
import hashlib
import json
import os
import uuid
from types import SimpleNamespace


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings.curve_worker")

import django  # noqa: E402


django.setup()

from temporalio.client import Client  # noqa: E402
from temporalio.common import WorkflowIDReusePolicy  # noqa: E402
from temporalio.exceptions import WorkflowAlreadyStartedError  # noqa: E402
from temporalio.worker import Replayer  # noqa: E402

from plane.curve.models import (  # noqa: E402
    AuditEvent,
    DomainEvent,
    InboxMessage,
    Operation,
    OperationStatus,
    OutboxEvent,
)
from plane.curve.policy_services import start_foundation_probe  # noqa: E402
from plane.curve.temporal.constants import (  # noqa: E402
    TASK_QUEUE,
    TEMPORAL_DESTINATION,
    WORKFLOW_TYPE,
    operation_workflow_id,
)
from plane.curve.temporal.control import (  # noqa: E402
    _record_cancellation_request,
    request_cancellation,
)
from plane.curve.temporal.contracts import CurveOperationWorkflowInputV1  # noqa: E402
from plane.curve.temporal.workflows import CurveOperationWorkflowV1  # noqa: E402
from plane.db.models import User, Workspace, WorkspaceMember  # noqa: E402


SENTINEL = "CURVE_PROTECTED_SENTINEL_M0_S3"


def _proof_context() -> tuple[Workspace, SimpleNamespace]:
    user, _ = User.objects.get_or_create(
        email="curve-local-proof@example.invalid",
        defaults={"username": "curve-local-proof@example.invalid"},
    )
    workspace, _ = Workspace.objects.get_or_create(
        slug="curve-local-proof",
        defaults={"name": "Curve local proof", "owner": user},
    )
    WorkspaceMember.objects.get_or_create(
        workspace=workspace,
        member=user,
        defaults={"role": 20, "is_active": True},
    )
    return workspace, SimpleNamespace(user=user)


def _create_probe(*, label: str) -> Operation:
    workspace, request = _proof_context()
    result = start_foundation_probe(
        request=request,
        workspace_slug=workspace.slug,
        raw_idempotency_key=f"curve-local-proof:{uuid.uuid4()}",
        canonical_request=json.dumps(
            {"fixture": label, "sentinel": SENTINEL},
            separators=(",", ":"),
            sort_keys=True,
        ).encode(),
        command_type="CREATE_FOUNDATION_PROBE",
        destination=TEMPORAL_DESTINATION,
    )
    return result.operation


def _load_operation(operation_id: uuid.UUID) -> Operation:
    return Operation.objects.get(id=operation_id)


async def _wait_for_status(operation_id: uuid.UUID, statuses: set[str], *, timeout: float = 30) -> Operation:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        operation = await asyncio.to_thread(_load_operation, operation_id)
        if operation.status in statuses:
            return operation
        await asyncio.sleep(0.1)
    raise TimeoutError(f"Curve Operation did not reach {sorted(statuses)}")


def _workflow_input(operation: Operation) -> CurveOperationWorkflowInputV1:
    return CurveOperationWorkflowInputV1(
        schema_version="1.0",
        workspace_id=str(operation.workspace_id),
        operation_id=str(operation.id),
        operation_version=operation.aggregate_version,
        operation_type=operation.operation_type,
        correlation_id=operation.correlation_id,
    )


async def _assert_duplicate_start_rejected(client: Client, operation: Operation) -> bool:
    try:
        await client.start_workflow(
            WORKFLOW_TYPE,
            _workflow_input(operation),
            id=operation.workflow_id,
            task_queue=TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    except WorkflowAlreadyStartedError:
        return True
    return False


async def _history_evidence(client: Client, operation: Operation) -> tuple[object, str]:
    workflow_id = operation_workflow_id(
        workspace_id=str(operation.workspace_id),
        operation_id=str(operation.id),
    )
    history = await client.get_workflow_handle(workflow_id).fetch_history()
    history_json = history.to_json()
    if SENTINEL in history_json:
        raise RuntimeError("protected sentinel leaked into Temporal history")
    await Replayer(workflows=[CurveOperationWorkflowV1]).replay_workflow(history)
    return history, history_json


def _evidence_counts(operation: Operation) -> dict[str, int]:
    event_ids = DomainEvent.objects.filter(
        workspace_id=operation.workspace_id,
        aggregate_id=operation.id,
    ).values_list("id", flat=True)
    inbox = InboxMessage.objects.filter(
        workspace_id=operation.workspace_id,
        received_at__gte=operation.created_at,
    )
    if operation.completed_at is not None:
        inbox = inbox.filter(received_at__lte=operation.completed_at)
    return {
        "operations": Operation.objects.filter(workspace_id=operation.workspace_id, id=operation.id).count(),
        "events": event_ids.count(),
        "outbox": OutboxEvent.objects.filter(
            workspace_id=operation.workspace_id,
            event_id__in=event_ids,
        ).count(),
        "inbox": inbox.count(),
        "audit": AuditEvent.objects.filter(
            workspace_id=operation.workspace_id,
            target_id=operation.id,
        ).count(),
    }


async def run_proof() -> dict:
    client = await Client.connect(
        os.environ["TEMPORAL_ADDRESS"],
        namespace=os.environ["TEMPORAL_NAMESPACE"],
    )

    success = await asyncio.to_thread(_create_probe, label="success")
    success = await _wait_for_status(success.id, {OperationStatus.SUCCEEDED})
    success_result = await client.get_workflow_handle_for(
        CurveOperationWorkflowV1.run,
        success.workflow_id,
    ).result()
    _, success_history_json = await _history_evidence(client, success)
    duplicate_rejected = await _assert_duplicate_start_rejected(client, success)
    success_evidence = await asyncio.to_thread(_evidence_counts, success)

    cancelled = await asyncio.to_thread(_create_probe, label="cancellation")
    cancelled = await _wait_for_status(cancelled.id, {OperationStatus.RUNNING})
    await request_cancellation(
        client=client,
        workspace_id=cancelled.workspace_id,
        operation_id=cancelled.id,
        actor_ref="developer:federico",
        reason_code="TEST_REQUESTED",
        command_id=f"cancel:{cancelled.id}",
        correlation_id=cancelled.correlation_id,
    )
    cancelled = await _wait_for_status(cancelled.id, {OperationStatus.CANCELLED})
    cancel_result = await client.get_workflow_handle_for(
        CurveOperationWorkflowV1.run,
        cancelled.workflow_id,
    ).result()
    _, cancelled_history_json = await _history_evidence(client, cancelled)
    cancelled_evidence = await asyncio.to_thread(_evidence_counts, cancelled)

    durable_cancelled = await asyncio.to_thread(_create_probe, label="durable-cancellation")
    durable_cancelled = await _wait_for_status(durable_cancelled.id, {OperationStatus.RUNNING})
    await asyncio.to_thread(
        _record_cancellation_request,
        workspace_id=durable_cancelled.workspace_id,
        operation_id=durable_cancelled.id,
        correlation_id=durable_cancelled.correlation_id,
        command_id=f"cancel-recovery:{durable_cancelled.id}",
    )
    durable_cancelled = await _wait_for_status(durable_cancelled.id, {OperationStatus.CANCELLED})
    durable_cancel_result = await client.get_workflow_handle_for(
        CurveOperationWorkflowV1.run,
        durable_cancelled.workflow_id,
    ).result()
    _, durable_cancel_history_json = await _history_evidence(client, durable_cancelled)
    durable_cancel_evidence = await asyncio.to_thread(_evidence_counts, durable_cancelled)

    if success_result.operation_status != OperationStatus.SUCCEEDED:
        raise RuntimeError("success workflow returned an unexpected status")
    if cancel_result.operation_status != OperationStatus.CANCELLED:
        raise RuntimeError("cancel workflow returned an unexpected status")
    if durable_cancel_result.operation_status != OperationStatus.CANCELLED:
        raise RuntimeError("durable cancel workflow returned an unexpected status")
    if not duplicate_rejected:
        raise RuntimeError("duplicate workflow start was accepted")

    return {
        "schema_version": "curve-temporal-proof/v1",
        "success": {
            "operation_id": str(success.id),
            "workflow_id": success.workflow_id,
            "status": success.status,
            "version": success.aggregate_version,
            "history_sha256": hashlib.sha256(success_history_json.encode()).hexdigest(),
            "evidence": success_evidence,
        },
        "cancellation": {
            "operation_id": str(cancelled.id),
            "workflow_id": cancelled.workflow_id,
            "status": cancelled.status,
            "version": cancelled.aggregate_version,
            "history_sha256": hashlib.sha256(cancelled_history_json.encode()).hexdigest(),
            "evidence": cancelled_evidence,
        },
        "durable_cancellation": {
            "operation_id": str(durable_cancelled.id),
            "workflow_id": durable_cancelled.workflow_id,
            "status": durable_cancelled.status,
            "version": durable_cancelled.aggregate_version,
            "history_sha256": hashlib.sha256(durable_cancel_history_json.encode()).hexdigest(),
            "evidence": durable_cancel_evidence,
        },
        "duplicate_start_rejected": duplicate_rejected,
        "history_replay_passed": True,
        "sentinel_absent_from_histories": True,
    }


async def prepare_restart_proof() -> dict:
    operation = await asyncio.to_thread(_create_probe, label="worker-restart")
    operation = await _wait_for_status(operation.id, {OperationStatus.RUNNING})
    return {
        "schema_version": "curve-temporal-restart-proof/v1",
        "phase": "PREPARED",
        "operation_id": str(operation.id),
        "workflow_id": operation.workflow_id,
        "status": operation.status,
        "version": operation.aggregate_version,
        "evidence": await asyncio.to_thread(_evidence_counts, operation),
    }


async def verify_restart_proof(operation_id: uuid.UUID) -> dict:
    client = await Client.connect(
        os.environ["TEMPORAL_ADDRESS"],
        namespace=os.environ["TEMPORAL_NAMESPACE"],
    )
    operation = await _wait_for_status(operation_id, {OperationStatus.SUCCEEDED})
    result = await client.get_workflow_handle_for(
        CurveOperationWorkflowV1.run,
        operation.workflow_id,
    ).result()
    _, history_json = await _history_evidence(client, operation)
    evidence = await asyncio.to_thread(_evidence_counts, operation)
    expected_evidence = {
        "operations": 1,
        "events": 4,
        "outbox": 4,
        "inbox": 2,
        "audit": 4,
    }
    if result.operation_status != OperationStatus.SUCCEEDED:
        raise RuntimeError("restarted workflow returned an unexpected status")
    if operation.aggregate_version != 4 or evidence != expected_evidence:
        raise RuntimeError("worker restart produced duplicate or missing effects")
    return {
        "schema_version": "curve-temporal-restart-proof/v1",
        "phase": "VERIFIED",
        "operation_id": str(operation.id),
        "workflow_id": operation.workflow_id,
        "status": operation.status,
        "version": operation.aggregate_version,
        "history_sha256": hashlib.sha256(history_json.encode()).hexdigest(),
        "history_replay_passed": True,
        "sentinel_absent_from_history": True,
        "duplicate_effect_absent": True,
        "evidence": evidence,
    }


async def export_history(workflow_id: str) -> dict:
    client = await Client.connect(
        os.environ["TEMPORAL_ADDRESS"],
        namespace=os.environ["TEMPORAL_NAMESPACE"],
    )
    history = await client.get_workflow_handle(workflow_id).fetch_history()
    return {
        "schema_version": "curve-temporal-history-fixture/v1",
        "workflow_id": workflow_id,
        "history": history.to_json_dict(),
    }


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("run")
    subcommands.add_parser("prepare-restart")
    verify_restart_parser = subcommands.add_parser("verify-restart")
    verify_restart_parser.add_argument("operation_id", type=uuid.UUID)
    export_parser = subcommands.add_parser("export-history")
    export_parser.add_argument("workflow_id")
    parser.set_defaults(command="run")
    return parser


def main() -> None:
    args = _argument_parser().parse_args()

    if args.command == "run":
        output = asyncio.run(run_proof())
    elif args.command == "prepare-restart":
        output = asyncio.run(prepare_restart_proof())
    elif args.command == "verify-restart":
        output = asyncio.run(verify_restart_proof(args.operation_id))
    else:
        output = asyncio.run(export_history(args.workflow_id))
    print(json.dumps(output, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
