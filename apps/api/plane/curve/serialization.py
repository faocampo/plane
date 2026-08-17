# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import datetime
from typing import Any
from uuid import UUID

from plane.curve.models import (
    AuditEvent,
    DomainEvent,
    IdempotencyRecord,
    InboxMessage,
    Operation,
    OutboxEvent,
)


def _wire_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _optional_values(**values: Any) -> dict[str, Any]:
    return {key: _wire_value(value) for key, value in values.items() if value is not None}


def serialize_operation(operation: Operation) -> dict[str, Any]:
    return {
        "schema_version": operation.schema_version,
        "id": str(operation.id),
        "workspace_id": str(operation.workspace_id),
        "operation_type": operation.operation_type,
        "status": operation.status,
        "version": operation.aggregate_version,
        "command_type": operation.command_type,
        "target": operation.target,
        "idempotency_key_digest": operation.idempotency_key_digest,
        "created_at": operation.created_at.isoformat(),
        "updated_at": operation.updated_at.isoformat(),
        "created_by": operation.created_by,
        "correlation_id": operation.correlation_id,
        **_optional_values(
            causation_id=operation.causation_id,
            workflow_id=operation.workflow_id,
            policy_version_ref=operation.policy_version_ref,
            progress_percent=operation.progress_percent,
            progress_summary=operation.progress_summary,
            result_ref=operation.result_ref,
            error=operation.error,
            started_at=operation.started_at,
            last_heartbeat_at=operation.last_heartbeat_at,
            completed_at=operation.completed_at,
            effective_principal=operation.effective_principal,
        ),
    }


def serialize_domain_event(event: DomainEvent) -> dict[str, Any]:
    return {
        "schema_version": event.schema_version,
        "event_id": str(event.id),
        "event_type": event.event_type,
        "workspace_id": str(event.workspace_id),
        "aggregate_type": event.aggregate_type,
        "aggregate_id": str(event.aggregate_id),
        "aggregate_version": event.aggregate_version,
        "sequence": event.sequence,
        "occurred_at": event.occurred_at.isoformat(),
        "recorded_at": event.recorded_at.isoformat(),
        "actor": event.actor,
        "correlation_id": event.correlation_id,
        "classification": event.classification,
        "payload_schema": event.payload_schema,
        "payload": event.payload,
        **_optional_values(
            initiative_id=event.initiative_id,
            workflow_version_id=event.workflow_version_id,
            effective_principal=event.effective_principal,
            causation_id=event.causation_id,
            idempotency_key_digest=event.idempotency_key_digest,
        ),
    }


def serialize_outbox_event(event: OutboxEvent) -> dict[str, Any]:
    return {
        "schema_version": event.schema_version,
        "id": str(event.id),
        "workspace_id": str(event.workspace_id),
        "event_id": str(event.event_id),
        "destination": event.destination,
        "state": event.state,
        "attempt_count": event.attempt_count,
        "created_at": event.created_at.isoformat(),
        **_optional_values(
            next_attempt_at=event.next_attempt_at,
            claimed_by=event.claimed_by,
            claimed_until=event.claimed_until,
            delivered_at=event.delivered_at,
            last_error=event.last_error,
        ),
    }


def serialize_inbox_message(message: InboxMessage) -> dict[str, Any]:
    return {
        "schema_version": message.schema_version,
        "id": str(message.id),
        "workspace_id": str(message.workspace_id),
        "consumer_id": message.consumer_id,
        "event_id": str(message.event_id),
        "state": message.state,
        "received_at": message.received_at.isoformat(),
        **_optional_values(
            processed_at=message.processed_at,
            result_digest=message.result_digest,
            last_error=message.last_error,
        ),
    }


def serialize_idempotency_record(record: IdempotencyRecord) -> dict[str, Any]:
    return {
        "schema_version": record.schema_version,
        "id": str(record.id),
        "workspace_id": str(record.workspace_id),
        "principal_scope": record.principal_scope,
        "command_scope": record.command_scope,
        "key_digest": record.key_digest,
        "request_digest": record.request_digest,
        "state": record.state,
        "external_effect_refs": record.external_effect_refs,
        "created_at": record.created_at.isoformat(),
        "expires_at": record.expires_at.isoformat(),
        **_optional_values(
            response_status=record.response_status,
            response_digest=record.response_digest,
            response_resource_ref=record.response_resource_ref,
            completed_at=record.completed_at,
        ),
    }


def serialize_audit_event(event: AuditEvent) -> dict[str, Any]:
    return {
        "schema_version": event.schema_version,
        "id": str(event.id),
        "workspace_id": str(event.workspace_id),
        "sequence": event.sequence,
        "action": event.action,
        "target_ref": event.target_ref,
        "outcome": event.outcome,
        "actor": event.actor,
        "classification": event.classification,
        "occurred_at": event.occurred_at.isoformat(),
        "recorded_at": event.recorded_at.isoformat(),
        "correlation_id": event.correlation_id,
        **_optional_values(
            effective_principal=event.effective_principal,
            policy_decision_ref=event.policy_decision_ref,
            before_digest=event.before_digest,
            after_digest=event.after_digest,
            details_ref=event.details_ref,
            causation_id=event.causation_id,
            idempotency_key_digest=event.idempotency_key_digest,
        ),
    }
