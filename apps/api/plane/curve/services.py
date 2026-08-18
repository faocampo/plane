# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from django.utils import timezone

from plane.curve.models import (
    AuditEvent,
    AuditOutcome,
    DataClassification,
    DomainEvent,
    IdempotencyRecord,
    IdempotencyState,
    InboxMessage,
    Operation,
    OperationStatus,
    OperationType,
    OutboxEvent,
    OutboxState,
)


OPERATION_EVENT_SCHEMA = "https://curve.x3m.internal/contracts/schemas/operation-event-v1.schema.json"


class CurveKernelError(Exception):
    code = "CURVE_KERNEL_ERROR"


class CurveResourceNotFound(CurveKernelError):
    code = "CURVE_RESOURCE_NOT_FOUND"


class IdempotencyConflict(CurveKernelError):
    code = "CURVE_IDEMPOTENCY_CONFLICT"


class CommandAlreadyInProgress(CurveKernelError):
    code = "CURVE_COMMAND_IN_PROGRESS"


class OptimisticConcurrencyError(CurveKernelError):
    code = "CURVE_OPTIMISTIC_CONCURRENCY"


class ReplayResourceUnavailable(CurveKernelError):
    code = "CURVE_REPLAY_RESOURCE_UNAVAILABLE"


class InvalidRelayClaim(CurveKernelError):
    code = "CURVE_INVALID_RELAY_CLAIM"


class InvalidCommand(CurveKernelError):
    code = "CURVE_INVALID_COMMAND"


class InvalidOperationTransition(CurveKernelError):
    code = "CURVE_INVALID_OPERATION_TRANSITION"


class CurveAuthorizationReceiptRequired(CurveKernelError):
    code = "CURVE_AUTHORIZATION_RECEIPT_REQUIRED"


@dataclass(frozen=True)
class OperationCommandResult:
    operation: Operation
    replayed: bool
    response_status: int
    response_digest: str
    response_resource_ref: dict


CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,99}$")
DESTINATION_PATTERN = re.compile(r"^[A-Z][A-Z0-9_.-]{0,127}$")
RESOURCE_TYPE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,99}$")
ACTOR_TYPES = frozenset({"HUMAN", "SERVICE", "AGENT", "SYSTEM"})
MAX_OUTBOX_LEASE_DURATION = timedelta(minutes=15)
ALLOWED_OPERATION_TRANSITIONS = {
    OperationStatus.PENDING: frozenset(
        {
            OperationStatus.QUEUED,
            OperationStatus.CANCEL_REQUESTED,
            OperationStatus.FAILED,
        }
    ),
    OperationStatus.QUEUED: frozenset(
        {
            OperationStatus.RUNNING,
            OperationStatus.CANCEL_REQUESTED,
            OperationStatus.FAILED,
        }
    ),
    OperationStatus.RUNNING: frozenset(
        {
            OperationStatus.CANCEL_REQUESTED,
            OperationStatus.SUCCEEDED,
            OperationStatus.FAILED,
        }
    ),
    OperationStatus.CANCEL_REQUESTED: frozenset({OperationStatus.CANCELLED}),
    OperationStatus.SUCCEEDED: frozenset(),
    OperationStatus.FAILED: frozenset(),
    OperationStatus.CANCELLED: frozenset(),
}


def _invalid(field: str):
    raise InvalidCommand(f"invalid {field}")


def _validate_uuid(value, field: str) -> uuid.UUID:
    if not isinstance(value, uuid.UUID):
        _invalid(field)
    return value


def _validate_text(value, field: str, *, maximum: int, pattern=None):
    if not isinstance(value, str) or not value or len(value) > maximum:
        _invalid(field)
    if pattern is not None and pattern.fullmatch(value) is None:
        _invalid(field)


def _validate_actor(actor: dict | None, field: str, *, required: bool):
    if actor is None and not required:
        return
    if not isinstance(actor, dict) or set(actor) != {"actor_type", "actor_id"}:
        _invalid(field)
    if actor["actor_type"] not in ACTOR_TYPES:
        _invalid(field)
    _validate_text(actor["actor_id"], field, maximum=255)


def _validate_resource_ref(reference: dict, field: str):
    if not isinstance(reference, dict):
        _invalid(field)
    if not {"resource_type", "resource_id"}.issubset(reference) or not set(reference).issubset(
        {"resource_type", "resource_id", "resource_version"}
    ):
        _invalid(field)
    _validate_text(
        reference["resource_type"],
        field,
        maximum=100,
        pattern=RESOURCE_TYPE_PATTERN,
    )
    if not isinstance(reference["resource_id"], str):
        _invalid(field)
    try:
        uuid.UUID(reference["resource_id"])
    except (AttributeError, TypeError, ValueError):
        _invalid(field)
    version = reference.get("resource_version")
    if version is not None and (type(version) is not int or version < 1):
        _invalid(field)


def _validate_safe_error(error: dict | None, field: str, *, required: bool):
    if error is None and not required:
        return
    if not isinstance(error, dict) or not {"code", "retryable"}.issubset(error):
        _invalid(field)
    if not set(error).issubset({"code", "retryable", "detail_ref"}):
        _invalid(field)
    _validate_text(error["code"], field, maximum=100, pattern=CODE_PATTERN)
    if type(error["retryable"]) is not bool:
        _invalid(field)
    if "detail_ref" in error:
        detail_ref = error["detail_ref"]
        if not isinstance(detail_ref, dict) or set(detail_ref) != {
            "object_id",
            "digest",
            "size_bytes",
            "media_type",
        }:
            _invalid(field)
        if not isinstance(detail_ref["object_id"], str):
            _invalid(field)
        try:
            uuid.UUID(detail_ref["object_id"])
        except (AttributeError, TypeError, ValueError):
            _invalid(field)
        if (
            not isinstance(detail_ref["digest"], str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", detail_ref["digest"]) is None
        ):
            _invalid(field)
        if type(detail_ref["size_bytes"]) is not int or detail_ref["size_bytes"] < 0:
            _invalid(field)
        _validate_text(detail_ref["media_type"], field, maximum=255)


def _validate_utc_datetime(value, field: str):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        _invalid(field)


def _validate_create_operation_command(
    *,
    workspace_id,
    principal_scope,
    command_scope,
    raw_idempotency_key,
    canonical_request,
    operation_type,
    command_type,
    target,
    actor,
    effective_principal,
    correlation_id,
    causation_id,
    destination,
    idempotency_ttl,
):
    _validate_uuid(workspace_id, "workspace_id")
    _validate_text(principal_scope, "principal_scope", maximum=500)
    _validate_text(command_scope, "command_scope", maximum=500)
    _validate_text(raw_idempotency_key, "idempotency_key", maximum=4096)
    if not isinstance(canonical_request, bytes) or not canonical_request:
        _invalid("canonical_request")
    if operation_type not in OperationType.values:
        _invalid("operation_type")
    _validate_text(command_type, "command_type", maximum=100, pattern=CODE_PATTERN)
    _validate_resource_ref(target, "target")
    if target["resource_type"] == "WORKSPACE" and target["resource_id"] != str(workspace_id):
        _invalid("target")
    _validate_actor(actor, "actor", required=True)
    _validate_actor(effective_principal, "effective_principal", required=False)
    _validate_text(correlation_id, "correlation_id", maximum=255)
    if causation_id is not None:
        _validate_text(causation_id, "causation_id", maximum=255)
    _validate_text(destination, "destination", maximum=128, pattern=DESTINATION_PATTERN)
    if not isinstance(idempotency_ttl, timedelta) or idempotency_ttl.total_seconds() <= 0:
        _invalid("idempotency_ttl")


def _validate_transition_command(
    *,
    workspace_id,
    operation_id,
    expected_version,
    status,
    actor,
    effective_principal,
    correlation_id,
    causation_id,
    progress_percent,
    error,
    destination,
):
    _validate_uuid(workspace_id, "workspace_id")
    _validate_uuid(operation_id, "operation_id")
    if type(expected_version) is not int or expected_version < 1:
        _invalid("expected_version")
    if status not in OperationStatus.values:
        _invalid("status")
    _validate_actor(actor, "actor", required=True)
    _validate_actor(effective_principal, "effective_principal", required=False)
    _validate_text(correlation_id, "correlation_id", maximum=255)
    if causation_id is not None:
        _validate_text(causation_id, "causation_id", maximum=255)
    if progress_percent is not None and (type(progress_percent) is not int or not 0 <= progress_percent <= 100):
        _invalid("progress_percent")
    _validate_safe_error(error, "error", required=status == OperationStatus.FAILED)
    if status != OperationStatus.FAILED and error is not None:
        _invalid("error")
    _validate_text(destination, "destination", maximum=128, pattern=DESTINATION_PATTERN)


def sha256_digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def canonical_json_bytes(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def operation_response_digest(*, response_status: int, resource_ref: dict) -> str:
    return sha256_digest(
        canonical_json_bytes(
            {
                "response_resource_ref": resource_ref,
                "response_status": response_status,
            }
        )
    )


def idempotency_key_digest(raw_key: str) -> str:
    if not raw_key:
        raise ValueError("an idempotency key is required")
    return sha256_digest(raw_key.encode("utf-8"))


def operation_resource_ref(operation: Operation) -> dict:
    return {
        "resource_type": "OPERATION",
        "resource_id": str(operation.id),
        "resource_version": operation.aggregate_version,
    }


def _advisory_lock_key(workspace_id: uuid.UUID, target_type: str, target_id: uuid.UUID) -> int:
    material = f"{workspace_id}:{target_type}:{target_id}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=True)


def _lock_audit_sequence(workspace_id: uuid.UUID, target_type: str, target_id: uuid.UUID):
    if connection.vendor != "postgresql":
        raise RuntimeError("Curve audit sequencing requires PostgreSQL")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            [_advisory_lock_key(workspace_id, target_type, target_id)],
        )


def _append_audit_event(
    *,
    workspace_id: uuid.UUID,
    action: str,
    target_ref: dict,
    outcome: str,
    actor: dict,
    correlation_id: str,
    effective_principal: dict | None = None,
    before_digest: str | None = None,
    after_digest: str | None = None,
    causation_id: str | None = None,
    key_digest: str | None = None,
    policy_decision_ref: dict | None = None,
) -> AuditEvent:
    target_type = target_ref["resource_type"]
    target_id = uuid.UUID(str(target_ref["resource_id"]))
    _lock_audit_sequence(workspace_id, target_type, target_id)
    previous = (
        AuditEvent.objects.filter(
            workspace_id=workspace_id,
            target_type=target_type,
            target_id=target_id,
        )
        .order_by("-sequence")
        .values_list("sequence", flat=True)
        .first()
    )
    return AuditEvent.objects.create(
        workspace_id=workspace_id,
        sequence=(previous or 0) + 1,
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_ref=target_ref,
        outcome=outcome,
        actor=actor,
        effective_principal=effective_principal,
        policy_decision_ref=policy_decision_ref,
        before_digest=before_digest,
        after_digest=after_digest,
        classification=DataClassification.INTERNAL,
        correlation_id=correlation_id,
        causation_id=causation_id,
        idempotency_key_digest=key_digest,
    )


def _operation_event_payload(operation: Operation) -> dict:
    payload = {
        "workspace_id": str(operation.workspace_id),
        "operation_id": str(operation.id),
        "operation_version": operation.aggregate_version,
        "status": operation.status,
    }
    if operation.progress_percent is not None:
        payload["progress"] = operation.progress_percent
    if operation.error is not None:
        payload["error"] = operation.error
    return payload


def _append_operation_event(
    *,
    operation: Operation,
    actor: dict,
    effective_principal: dict | None,
    correlation_id: str,
    causation_id: str | None,
    key_digest: str | None,
    destination: str,
) -> DomainEvent:
    event = DomainEvent.objects.create(
        workspace_id=operation.workspace_id,
        event_type="curve.operation.state_changed",
        aggregate_type="OPERATION",
        aggregate_id=operation.id,
        aggregate_version=operation.aggregate_version,
        sequence=operation.aggregate_version,
        actor=actor,
        effective_principal=effective_principal,
        correlation_id=correlation_id,
        causation_id=causation_id,
        idempotency_key_digest=key_digest,
        classification=DataClassification.INTERNAL,
        payload_schema=OPERATION_EVENT_SCHEMA,
        payload=_operation_event_payload(operation),
    )
    OutboxEvent.objects.create(
        workspace_id=operation.workspace_id,
        event_id=event.id,
        destination=destination,
    )
    return event


def _create_idempotency_record(
    *,
    workspace_id: uuid.UUID,
    principal_scope: str,
    command_scope: str,
    key_digest: str,
    request_digest: str,
    expires_at,
) -> tuple[IdempotencyRecord | None, bool]:
    try:
        with transaction.atomic():
            return (
                IdempotencyRecord.objects.create(
                    workspace_id=workspace_id,
                    principal_scope=principal_scope,
                    command_scope=command_scope,
                    key_digest=key_digest,
                    request_digest=request_digest,
                    expires_at=expires_at,
                ),
                True,
            )
    except IntegrityError:
        return None, False


def _resolve_operation_replay(*, workspace_id: uuid.UUID, resource_ref: dict | None) -> Operation:
    if not resource_ref or resource_ref.get("resource_type") != "OPERATION":
        raise ReplayResourceUnavailable
    operation = Operation.objects.filter(
        workspace_id=workspace_id,
        id=resource_ref.get("resource_id"),
    ).first()
    if operation is None:
        raise ReplayResourceUnavailable
    return operation


def _create_operation_authorized(
    *,
    authorization_receipt,
    workspace_id: uuid.UUID,
    principal_scope: str,
    command_scope: str,
    raw_idempotency_key: str,
    canonical_request: bytes,
    operation_type: str,
    command_type: str,
    target: dict,
    actor: dict,
    correlation_id: str,
    effective_principal: dict | None = None,
    causation_id: str | None = None,
    destination: str = "CURVE_LOCAL",
    idempotency_ttl: timedelta = timedelta(days=1),
) -> OperationCommandResult:
    from plane.curve.policy_services import (
        assert_active_mutation_receipt,
        policy_decision_ref_for_receipt,
    )

    assert_active_mutation_receipt(
        authorization_receipt,
        action="CURVE.FOUNDATION_PROBE.START",
        workspace_id=workspace_id,
        resource_ref=target,
    )
    policy_decision_ref = policy_decision_ref_for_receipt(authorization_receipt)
    _validate_create_operation_command(
        workspace_id=workspace_id,
        principal_scope=principal_scope,
        command_scope=command_scope,
        raw_idempotency_key=raw_idempotency_key,
        canonical_request=canonical_request,
        operation_type=operation_type,
        command_type=command_type,
        target=target,
        actor=actor,
        effective_principal=effective_principal,
        correlation_id=correlation_id,
        causation_id=causation_id,
        destination=destination,
        idempotency_ttl=idempotency_ttl,
    )
    key_digest = idempotency_key_digest(raw_idempotency_key)
    request_digest = sha256_digest(canonical_request)
    expires_at = timezone.now() + idempotency_ttl

    conflict = False
    already_in_progress = False
    result = None
    with transaction.atomic():
        record = (
            IdempotencyRecord.objects.select_for_update()
            .filter(
                workspace_id=workspace_id,
                principal_scope=principal_scope,
                command_scope=command_scope,
                key_digest=key_digest,
            )
            .first()
        )
        record_created = False
        if record is None:
            record, record_created = _create_idempotency_record(
                workspace_id=workspace_id,
                principal_scope=principal_scope,
                command_scope=command_scope,
                key_digest=key_digest,
                request_digest=request_digest,
                expires_at=expires_at,
            )
            if record is None:
                record = IdempotencyRecord.objects.select_for_update().get(
                    workspace_id=workspace_id,
                    principal_scope=principal_scope,
                    command_scope=command_scope,
                    key_digest=key_digest,
                )

        if record.request_digest != request_digest:
            _append_audit_event(
                workspace_id=workspace_id,
                action="CURVE.COMMAND.IDEMPOTENCY_CONFLICT",
                target_ref=target,
                outcome=AuditOutcome.NO_EFFECT,
                actor=actor,
                effective_principal=effective_principal,
                correlation_id=correlation_id,
                causation_id=causation_id,
                key_digest=key_digest,
                policy_decision_ref=policy_decision_ref,
            )
            conflict = True
        elif record.state in IdempotencyRecord.TERMINAL_STATES:
            operation = _resolve_operation_replay(
                workspace_id=workspace_id,
                resource_ref=record.response_resource_ref,
            )
            result = OperationCommandResult(
                operation=operation,
                replayed=True,
                response_status=record.response_status,
                response_digest=record.response_digest,
                response_resource_ref=record.response_resource_ref,
            )
            _append_audit_event(
                workspace_id=workspace_id,
                action="CURVE.OPERATION.IDEMPOTENT_REPLAY",
                target_ref=operation_resource_ref(operation),
                outcome=AuditOutcome.NO_EFFECT,
                actor=actor,
                effective_principal=effective_principal,
                correlation_id=correlation_id,
                causation_id=causation_id,
                key_digest=key_digest,
                policy_decision_ref=policy_decision_ref,
            )
        elif not record_created:
            _append_audit_event(
                workspace_id=workspace_id,
                action="CURVE.OPERATION.ALREADY_IN_PROGRESS",
                target_ref=target,
                outcome=AuditOutcome.NO_EFFECT,
                actor=actor,
                effective_principal=effective_principal,
                correlation_id=correlation_id,
                causation_id=causation_id,
                key_digest=key_digest,
                policy_decision_ref=policy_decision_ref,
            )
            already_in_progress = True
        else:
            operation = Operation.objects.create(
                workspace_id=workspace_id,
                operation_type=operation_type,
                status=OperationStatus.PENDING,
                command_type=command_type,
                target=target,
                idempotency_key_digest=key_digest,
                causation_id=causation_id,
                policy_version_ref=policy_decision_ref,
                created_by=actor,
                updated_by=actor,
                effective_principal=effective_principal,
                correlation_id=correlation_id,
            )
            _append_operation_event(
                operation=operation,
                actor=actor,
                effective_principal=effective_principal,
                correlation_id=correlation_id,
                causation_id=causation_id,
                key_digest=key_digest,
                destination=destination,
            )
            response_status = 201
            response_resource_ref = operation_resource_ref(operation)
            response_digest = operation_response_digest(
                response_status=response_status,
                resource_ref=response_resource_ref,
            )
            _append_audit_event(
                workspace_id=workspace_id,
                action="CURVE.OPERATION.CREATE",
                target_ref=operation_resource_ref(operation),
                outcome=AuditOutcome.SUCCEEDED,
                actor=actor,
                effective_principal=effective_principal,
                correlation_id=correlation_id,
                causation_id=causation_id,
                after_digest=response_digest,
                key_digest=key_digest,
                policy_decision_ref=policy_decision_ref,
            )
            record.state = IdempotencyState.COMPLETED
            record.response_status = response_status
            record.response_digest = response_digest
            record.response_resource_ref = response_resource_ref
            record.completed_at = timezone.now()
            record.save(
                update_fields=[
                    "state",
                    "response_status",
                    "response_digest",
                    "response_resource_ref",
                    "completed_at",
                ]
            )
            result = OperationCommandResult(
                operation=operation,
                replayed=False,
                response_status=response_status,
                response_digest=response_digest,
                response_resource_ref=response_resource_ref,
            )

    if conflict:
        raise IdempotencyConflict
    if already_in_progress:
        raise CommandAlreadyInProgress
    if result is None:
        raise RuntimeError("operation command completed without a result")
    return result


def create_operation(*args, **kwargs):
    raise CurveAuthorizationReceiptRequired("create_operation requires the policy-owned mutation wrapper")


def _transition_operation_authorized(
    *,
    authorization_receipt,
    workspace_id: uuid.UUID,
    operation_id: uuid.UUID,
    expected_version: int,
    status: str,
    actor: dict,
    correlation_id: str,
    effective_principal: dict | None = None,
    causation_id: str | None = None,
    progress_percent: int | None = None,
    error: dict | None = None,
    destination: str = "CURVE_LOCAL",
) -> Operation:
    from plane.curve.policy_services import (
        assert_active_mutation_receipt,
        policy_decision_ref_for_receipt,
    )

    receipt_resource_ref = dict(authorization_receipt.resource_ref)
    assert_active_mutation_receipt(
        authorization_receipt,
        action="CURVE.OPERATION.TRANSITION",
        workspace_id=workspace_id,
        resource_ref={
            "resource_type": "OPERATION",
            "resource_id": str(operation_id),
            "resource_version": receipt_resource_ref.get("resource_version"),
        },
    )
    policy_decision_ref = policy_decision_ref_for_receipt(authorization_receipt)
    _validate_transition_command(
        workspace_id=workspace_id,
        operation_id=operation_id,
        expected_version=expected_version,
        status=status,
        actor=actor,
        effective_principal=effective_principal,
        correlation_id=correlation_id,
        causation_id=causation_id,
        progress_percent=progress_percent,
        error=error,
        destination=destination,
    )
    version_conflict = False
    invalid_transition = False
    result = None
    with transaction.atomic():
        operation = Operation.objects.select_for_update().filter(workspace_id=workspace_id, id=operation_id).first()
        if operation is None:
            raise CurveResourceNotFound
        if operation.aggregate_version != expected_version:
            _append_audit_event(
                workspace_id=workspace_id,
                action="CURVE.OPERATION.VERSION_CONFLICT",
                target_ref=operation_resource_ref(operation),
                outcome=AuditOutcome.NO_EFFECT,
                actor=actor,
                effective_principal=effective_principal,
                correlation_id=correlation_id,
                causation_id=causation_id,
                policy_decision_ref=policy_decision_ref,
            )
            version_conflict = True
        elif status not in ALLOWED_OPERATION_TRANSITIONS.get(operation.status, frozenset()):
            _append_audit_event(
                workspace_id=workspace_id,
                action="CURVE.OPERATION.INVALID_TRANSITION",
                target_ref=operation_resource_ref(operation),
                outcome=AuditOutcome.NO_EFFECT,
                actor=actor,
                effective_principal=effective_principal,
                correlation_id=correlation_id,
                causation_id=causation_id,
                policy_decision_ref=policy_decision_ref,
            )
            invalid_transition = True
        else:
            operation.status = status
            operation.progress_percent = progress_percent
            operation.error = error
            operation.aggregate_version += 1
            operation.policy_version_ref = policy_decision_ref
            operation.updated_by = actor
            if status == OperationStatus.RUNNING and operation.started_at is None:
                operation.started_at = timezone.now()
            if status in {
                OperationStatus.SUCCEEDED,
                OperationStatus.FAILED,
                OperationStatus.CANCELLED,
            }:
                operation.completed_at = timezone.now()
            operation.save()
            _append_operation_event(
                operation=operation,
                actor=actor,
                effective_principal=effective_principal,
                correlation_id=correlation_id,
                causation_id=causation_id,
                key_digest=None,
                destination=destination,
            )
            _append_audit_event(
                workspace_id=workspace_id,
                action="CURVE.OPERATION.TRANSITION",
                target_ref=operation_resource_ref(operation),
                outcome=AuditOutcome.SUCCEEDED,
                actor=actor,
                effective_principal=effective_principal,
                correlation_id=correlation_id,
                causation_id=causation_id,
                policy_decision_ref=policy_decision_ref,
            )
            result = operation

    if version_conflict:
        raise OptimisticConcurrencyError
    if invalid_transition:
        raise InvalidOperationTransition
    if result is None:
        raise RuntimeError("operation transition completed without a result")
    return result


def transition_operation(*args, **kwargs):
    raise CurveAuthorizationReceiptRequired("transition_operation requires the policy-owned mutation wrapper")


def claim_due_outbox(
    *,
    workspace_id: uuid.UUID,
    worker_id: str,
    limit: int,
    lease_duration: timedelta,
    now=None,
) -> list[OutboxEvent]:
    _validate_uuid(workspace_id, "workspace_id")
    _validate_text(worker_id, "worker_id", maximum=255)
    if type(limit) is not int or limit < 1 or limit > 1000:
        _invalid("limit")
    if (
        not isinstance(lease_duration, timedelta)
        or lease_duration.total_seconds() <= 0
        or lease_duration > MAX_OUTBOX_LEASE_DURATION
    ):
        _invalid("lease_duration")
    now = now or timezone.now()
    _validate_utc_datetime(now, "now")
    with transaction.atomic():
        due = (
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(workspace_id=workspace_id)
            .filter(Q(state=OutboxState.PENDING) | Q(state=OutboxState.RETRY_SCHEDULED, next_attempt_at__lte=now))
            .order_by("created_at", "id")[:limit]
        )
        claimed = list(due)
        for item in claimed:
            item.state = OutboxState.CLAIMED
            item.claimed_by = worker_id
            item.claimed_until = now + lease_duration
            item.next_attempt_at = None
            item.attempt_count += 1
            item.save(
                update_fields=[
                    "state",
                    "claimed_by",
                    "claimed_until",
                    "next_attempt_at",
                    "attempt_count",
                ]
            )
        return claimed


def _locked_active_claim(*, workspace_id: uuid.UUID, outbox_id: uuid.UUID, worker_id: str, now) -> OutboxEvent:
    item = OutboxEvent.objects.select_for_update().filter(workspace_id=workspace_id, id=outbox_id).first()
    if (
        item is None
        or item.state != OutboxState.CLAIMED
        or item.claimed_by != worker_id
        or item.claimed_until is None
        or item.claimed_until <= now
    ):
        raise InvalidRelayClaim
    return item


def acknowledge_outbox(*, workspace_id: uuid.UUID, outbox_id: uuid.UUID, worker_id: str, now=None) -> OutboxEvent:
    _validate_uuid(workspace_id, "workspace_id")
    _validate_uuid(outbox_id, "outbox_id")
    _validate_text(worker_id, "worker_id", maximum=255)
    now = now or timezone.now()
    _validate_utc_datetime(now, "now")
    with transaction.atomic():
        item = _locked_active_claim(
            workspace_id=workspace_id,
            outbox_id=outbox_id,
            worker_id=worker_id,
            now=now,
        )
        item.state = OutboxState.DELIVERED
        item.delivered_at = now
        item.claimed_by = None
        item.claimed_until = None
        item.save(update_fields=["state", "delivered_at", "claimed_by", "claimed_until"])
        return item


def retry_outbox(
    *,
    workspace_id: uuid.UUID,
    outbox_id: uuid.UUID,
    worker_id: str,
    next_attempt_at,
    error: dict,
    now=None,
) -> OutboxEvent:
    _validate_uuid(workspace_id, "workspace_id")
    _validate_uuid(outbox_id, "outbox_id")
    _validate_text(worker_id, "worker_id", maximum=255)
    _validate_safe_error(error, "error", required=True)
    now = now or timezone.now()
    _validate_utc_datetime(now, "now")
    _validate_utc_datetime(next_attempt_at, "next_attempt_at")
    if next_attempt_at is None or next_attempt_at <= now:
        _invalid("next_attempt_at")
    with transaction.atomic():
        item = _locked_active_claim(
            workspace_id=workspace_id,
            outbox_id=outbox_id,
            worker_id=worker_id,
            now=now,
        )
        item.state = OutboxState.RETRY_SCHEDULED
        item.next_attempt_at = next_attempt_at
        item.last_error = error
        item.claimed_by = None
        item.claimed_until = None
        item.save(
            update_fields=[
                "state",
                "next_attempt_at",
                "last_error",
                "claimed_by",
                "claimed_until",
            ]
        )
        return item


def dead_letter_outbox(
    *,
    workspace_id: uuid.UUID,
    outbox_id: uuid.UUID,
    worker_id: str,
    error: dict,
    now=None,
) -> OutboxEvent:
    _validate_uuid(workspace_id, "workspace_id")
    _validate_uuid(outbox_id, "outbox_id")
    _validate_text(worker_id, "worker_id", maximum=255)
    _validate_safe_error(error, "error", required=True)
    now = now or timezone.now()
    _validate_utc_datetime(now, "now")
    with transaction.atomic():
        item = _locked_active_claim(
            workspace_id=workspace_id,
            outbox_id=outbox_id,
            worker_id=worker_id,
            now=now,
        )
        item.state = OutboxState.DEAD_LETTER
        item.last_error = error
        item.claimed_by = None
        item.claimed_until = None
        item.save(update_fields=["state", "last_error", "claimed_by", "claimed_until"])
        return item


def recover_expired_outbox_claims(
    *, workspace_id: uuid.UUID, actor: dict, correlation_id: str, now=None, limit: int = 100
) -> list[OutboxEvent]:
    _validate_uuid(workspace_id, "workspace_id")
    _validate_actor(actor, "actor", required=True)
    _validate_text(correlation_id, "correlation_id", maximum=255)
    if type(limit) is not int or limit < 1 or limit > 1000:
        _invalid("limit")
    now = now or timezone.now()
    _validate_utc_datetime(now, "now")
    with transaction.atomic():
        expired = list(
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(
                workspace_id=workspace_id,
                state=OutboxState.CLAIMED,
                claimed_until__lte=now,
            )
            .order_by("claimed_until", "id")[:limit]
        )
        for item in expired:
            item.state = OutboxState.RETRY_SCHEDULED
            item.next_attempt_at = now
            item.last_error = {"code": "CLAIM_EXPIRED", "retryable": True}
            item.claimed_by = None
            item.claimed_until = None
            item.save(
                update_fields=[
                    "state",
                    "next_attempt_at",
                    "last_error",
                    "claimed_by",
                    "claimed_until",
                ]
            )
            _append_audit_event(
                workspace_id=workspace_id,
                action="CURVE.OUTBOX.CLAIM_EXPIRED",
                target_ref={
                    "resource_type": "OUTBOX_EVENT",
                    "resource_id": str(item.id),
                },
                outcome=AuditOutcome.NO_EFFECT,
                actor=actor,
                correlation_id=correlation_id,
            )
        return expired


def receive_inbox_message(
    *, workspace_id: uuid.UUID, consumer_id: str, event_id: uuid.UUID
) -> tuple[InboxMessage, bool]:
    _validate_uuid(workspace_id, "workspace_id")
    _validate_text(consumer_id, "consumer_id", maximum=255)
    _validate_uuid(event_id, "event_id")
    try:
        with transaction.atomic():
            return (
                InboxMessage.objects.create(
                    workspace_id=workspace_id,
                    consumer_id=consumer_id,
                    event_id=event_id,
                ),
                True,
            )
    except IntegrityError:
        return (
            InboxMessage.objects.get(
                workspace_id=workspace_id,
                consumer_id=consumer_id,
                event_id=event_id,
            ),
            False,
        )
