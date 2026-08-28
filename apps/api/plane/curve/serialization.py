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
    PolicyDecision,
    ProviderCapability,
    ProviderConnection,
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


def serialize_operation_summary(operation: Operation) -> dict[str, Any]:
    """Serialize only the API-safe Operation metadata approved by core policy."""

    return {
        "schema_version": operation.schema_version,
        "id": str(operation.id),
        "workspace_id": str(operation.workspace_id),
        "operation_type": operation.operation_type,
        "status": operation.status,
        "version": operation.aggregate_version,
        **_optional_values(progress_percent=operation.progress_percent),
    }


def serialize_sse_event(event: DomainEvent) -> dict[str, Any]:
    """Serialize one authorized event through an explicit safe-field allowlist."""

    data = {"status": event.payload.get("status")}
    progress = event.payload.get("progress")
    if type(progress) is int and 0 <= progress <= 100:
        data["progress_percent"] = progress
    return {
        "schema_version": "1.0",
        "event_id": str(event.id),
        "workspace_id": str(event.workspace_id),
        "event_type": event.event_type,
        "occurred_at": event.occurred_at.isoformat(),
        "resource": {
            "type": event.aggregate_type,
            "id": str(event.aggregate_id),
            "version": event.aggregate_version,
        },
        "data": data,
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


def serialize_policy_decision(decision: PolicyDecision) -> dict[str, Any]:
    resource_ref = {
        "resource_type": decision.resource_type,
        "resource_id": str(decision.resource_id),
    }
    if decision.resource_version is not None:
        resource_ref["resource_version"] = decision.resource_version
    return {
        "schema_version": decision.schema_version,
        "id": str(decision.id),
        "workspace_id": str(decision.workspace_id),
        "sequence": decision.sequence,
        "action": decision.action,
        "resource_ref": resource_ref,
        "subject": decision.subject,
        "effective_principal": decision.effective_principal,
        "effect": decision.effect,
        "reason_codes": decision.reason_codes,
        "policy_key": decision.policy_key,
        "policy_version": decision.policy_version,
        "policy_manifest_digest": decision.policy_manifest_digest,
        "input_digest": decision.input_digest,
        "normalized_classification": decision.normalized_classification,
        "permitted_projection": decision.permitted_projection,
        "evaluated_at": decision.evaluated_at.isoformat(),
        "recorded_at": decision.recorded_at.isoformat(),
        "recorded_by": decision.recorded_by,
        "correlation_id": decision.correlation_id,
    }


def serialize_provider_connection(connection: ProviderConnection) -> dict[str, Any]:
    """Project a provider connection through the schema-approved safe fields."""

    capability_document_ref = None
    if connection.current_capability_id is not None:
        capability = connection.current_capability
        capability_document_ref = {
            "resource_type": "PROVIDER_CAPABILITY",
            "resource_id": str(capability.id),
            "resource_version": capability.capability_version,
        }

    return {
        "schema_version": connection.schema_version,
        "id": str(connection.id),
        "workspace_id": str(connection.workspace_id),
        "aggregate_version": connection.aggregate_version,
        "provider_type": connection.provider_type,
        "adapter_key": connection.adapter_key,
        "adapter_version": connection.adapter_version,
        "environment": connection.environment,
        "display_name": connection.display_name,
        "configuration_digest": connection.configuration_digest,
        "allowed_classifications": connection.allowed_classifications,
        "status": connection.status,
        "created_at": connection.created_at.isoformat(),
        "created_by": connection.created_by,
        "updated_at": connection.updated_at.isoformat(),
        "updated_by": connection.updated_by,
        **_optional_values(
            external_tenant_ref=connection.external_tenant_ref,
            configuration_ref=connection.configuration_ref,
            secret_reference=connection.secret_reference,
            capability_document_ref=capability_document_ref,
            validated_at=connection.validated_at,
            validation_result_ref=connection.validation_result_ref,
            last_reconciled_at=connection.last_reconciled_at,
            next_reconcile_at=connection.next_reconcile_at,
            last_error=connection.last_error,
        ),
    }


def serialize_provider_capability(capability: ProviderCapability) -> dict[str, Any]:
    """Project an immutable capability observation, retaining explicit expiry null."""

    return {
        "schema_version": capability.schema_version,
        "id": str(capability.id),
        "workspace_id": str(capability.workspace_id),
        "connection_id": str(capability.connection_id),
        "connection_version": capability.connection_version,
        "capability_version": capability.capability_version,
        "provider_type": capability.provider_type,
        "adapter_key": capability.adapter_key,
        "adapter_version": capability.adapter_version,
        "protocol_versions": capability.protocol_versions,
        "capabilities": capability.capabilities,
        "allowed_classifications": capability.allowed_classifications,
        "observed_at": capability.observed_at.isoformat(),
        "validated_at": capability.validated_at.isoformat(),
        "expires_at": capability.expires_at.isoformat() if capability.expires_at is not None else None,
    }
