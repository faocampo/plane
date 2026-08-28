# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from django.db import transaction
from django.utils import timezone

from plane.curve.config import is_curve_provider_registry_enabled_for_workspace
from plane.curve.models import (
    AuditOutcome,
    DataClassification,
    DomainEvent,
    IdempotencyRecord,
    IdempotencyState,
    InboxState,
    Operation,
    OperationStatus,
    OperationType,
    OutboxEvent,
    ProviderCapability as ProviderCapabilityModel,
    ProviderConnection,
    ProviderConnectionStatus,
    ProviderEnvironment,
    ProviderType as ProviderTypeModel,
)
from plane.curve.policy_services import (
    CurvePolicyResourceNotFound,
    assert_active_mutation_receipt,
    build_provider_administration_context,
    build_provider_registration_context,
    correlation_id_for_request,
    execute_authorized_mutation,
    policy_decision_ref_for_receipt,
)
from plane.curve.policy_types import DataClassification as PolicyDataClassification
from plane.curve.providers import (
    STATIC_PROVIDER_REGISTRY,
    ActorRef,
    ActorType,
    NeverCancelled,
    NormalizedProviderError,
    ProviderCallContext,
    ProviderCapability,
    ProviderCapabilityObservation,
    ProviderCapabilityRisk,
    ProviderErrorCode,
    ProviderObservationRef,
    ProviderReconciliationFailed,
    ProviderRegistryError,
    ProviderType,
    reconcile_with_retry,
)
from plane.curve.providers.event_contracts import validate_provider_event_payload
from plane.curve.providers.reconciliation import ProviderReconciliationExecutionError
from plane.curve.services import (
    CommandAlreadyInProgress,
    CurveKernelError,
    CurveResourceNotFound,
    IdempotencyConflict,
    InvalidCommand,
    OptimisticConcurrencyError,
    ReplayResourceUnavailable,
    _append_audit_event,
    _create_idempotency_record,
    _create_operation_authorized,
    acknowledge_outbox,
    canonical_json_bytes,
    claim_due_outbox,
    complete_inbox_message,
    dead_letter_outbox,
    idempotency_key_digest,
    operation_resource_ref,
    operation_response_digest,
    receive_inbox_message,
    recover_expired_outbox_claims,
    retry_outbox,
    sha256_digest,
)
from plane.db.models import Workspace


PROVIDER_LOCAL_DESTINATION = "CURVE_PROVIDER_LOCAL_V1"
PROVIDER_LOCAL_CONSUMER_ID = "curve-provider-local-v1"
PROVIDER_LOCAL_WORKER_ID = "curve-provider-local-v1"
PROVIDER_LOCAL_BATCH_SIZE = 10
PROVIDER_LOCAL_CLAIM_LEASE = timedelta(seconds=30)
PROVIDER_LOCAL_RETRY_DELAY = timedelta(seconds=5)
PROVIDER_LOCAL_MAX_ATTEMPTS = 3
PROVIDER_RECONCILIATION_INTERVAL = timedelta(seconds=900)
PROVIDER_SERVICE_ACTOR = {"actor_type": "SERVICE", "actor_id": "provider-registry"}

_REGISTER_ACTION = "CURVE.PROVIDER_CONNECTION.REGISTER"
_ADMINISTER_ACTION = "CURVE.PROVIDER_CONNECTION.ADMINISTER"
_FAKE_ADAPTER_KEY = "curve.fake-local"
_FAKE_ADAPTER_VERSION = "1.0.0"
_LOCAL_EVENT_TYPES = frozenset(
    {
        "curve.operation.state_changed",
        "curve.provider_connection.registered",
        "curve.provider_connection.validated",
        "curve.provider_connection.degraded",
        "curve.provider_connection.disabled",
        "curve.provider_connection.enabled",
        "curve.provider_connection.revoked",
        "curve.provider_reconciliation.completed",
        "curve.provider_reconciliation.failed",
    }
)
_LIFECYCLE_TRANSITIONS = {
    "DISABLE": {
        ProviderConnectionStatus.PENDING_VALIDATION: ProviderConnectionStatus.DISABLED,
        ProviderConnectionStatus.ACTIVE: ProviderConnectionStatus.DISABLED,
        ProviderConnectionStatus.DEGRADED: ProviderConnectionStatus.DISABLED,
    },
    "ENABLE": {
        ProviderConnectionStatus.DISABLED: ProviderConnectionStatus.PENDING_VALIDATION,
    },
    "REVOKE": {
        ProviderConnectionStatus.PENDING_VALIDATION: ProviderConnectionStatus.REVOKED,
        ProviderConnectionStatus.ACTIVE: ProviderConnectionStatus.REVOKED,
        ProviderConnectionStatus.DEGRADED: ProviderConnectionStatus.REVOKED,
        ProviderConnectionStatus.DISABLED: ProviderConnectionStatus.REVOKED,
    },
}
_LIFECYCLE_EVENT_TYPES = {
    "DISABLE": "curve.provider_connection.disabled",
    "ENABLE": "curve.provider_connection.enabled",
    "REVOKE": "curve.provider_connection.revoked",
}


class ProviderRegistryDisabled(CurveKernelError):
    code = "CURVE_PROVIDER_REGISTRY_DISABLED"


class InvalidProviderTransition(CurveKernelError):
    code = "CURVE_PROVIDER_INVALID_TRANSITION"


class ProviderObservationRejected(CurveKernelError):
    code = "CURVE_PROVIDER_OBSERVATION_REJECTED"


@dataclass(frozen=True, slots=True)
class ProviderConnectionCommandResult:
    connection: ProviderConnection
    replayed: bool
    response_status: int
    response_digest: str
    response_resource_ref: dict


@dataclass(frozen=True, slots=True)
class ProviderReconciliationCommandResult:
    operation: Operation
    connection: ProviderConnection
    capability: ProviderCapabilityModel | None
    replayed: bool
    attempts: int


@dataclass(frozen=True, slots=True)
class LocalProviderDrainResult:
    claimed: int
    delivered: int
    deduplicated: int
    retry_scheduled: int
    dead_lettered: int


def provider_connection_resource_ref(connection: ProviderConnection) -> dict[str, object]:
    return {
        "resource_type": "PROVIDER_CONNECTION",
        "resource_id": str(connection.id),
        "resource_version": connection.aggregate_version,
    }


def provider_capability_resource_ref(capability: ProviderCapabilityModel) -> dict[str, object]:
    return {
        "resource_type": "PROVIDER_CAPABILITY",
        "resource_id": str(capability.id),
        "resource_version": capability.capability_version,
    }


def _human_actor(request) -> dict[str, str]:
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return {"actor_type": "SYSTEM", "actor_id": "anonymous"}
    return {"actor_type": "HUMAN", "actor_id": str(user.id)}


def _workspace_for_provider_command(workspace_slug: str) -> Workspace:
    if not is_curve_provider_registry_enabled_for_workspace(workspace_slug):
        raise ProviderRegistryDisabled
    workspace = Workspace.objects.only("id", "slug").filter(slug=workspace_slug).first()
    if workspace is None:
        raise CurvePolicyResourceNotFound
    return workspace


def _safe_local_event_result_digest(event: DomainEvent) -> str:
    return sha256_digest(
        canonical_json_bytes(
            {
                "event_id": str(event.id),
                "event_type": event.event_type,
                "workspace_id": str(event.workspace_id),
                "aggregate_type": event.aggregate_type,
                "aggregate_id": str(event.aggregate_id),
                "aggregate_version": event.aggregate_version,
            }
        )
    )


def drain_local_provider_events(
    *,
    workspace_id: uuid.UUID,
    correlation_id: str,
    now=None,
) -> LocalProviderDrainResult:
    """Synchronously deliver one bounded batch of committed local provider events."""

    drain_time = now or timezone.now()
    recover_expired_outbox_claims(
        workspace_id=workspace_id,
        actor=PROVIDER_SERVICE_ACTOR,
        correlation_id=correlation_id,
        now=drain_time,
        limit=PROVIDER_LOCAL_BATCH_SIZE,
        destination=PROVIDER_LOCAL_DESTINATION,
        maximum_attempts=PROVIDER_LOCAL_MAX_ATTEMPTS,
    )
    claimed = claim_due_outbox(
        workspace_id=workspace_id,
        worker_id=PROVIDER_LOCAL_WORKER_ID,
        limit=PROVIDER_LOCAL_BATCH_SIZE,
        lease_duration=PROVIDER_LOCAL_CLAIM_LEASE,
        now=drain_time,
        destination=PROVIDER_LOCAL_DESTINATION,
        maximum_attempts=PROVIDER_LOCAL_MAX_ATTEMPTS,
    )
    delivered = 0
    deduplicated = 0
    retry_scheduled = 0
    dead_lettered = 0

    for item in claimed:
        item_delivered = False
        item_deduplicated = False
        try:
            with transaction.atomic():
                event = DomainEvent.objects.filter(
                    workspace_id=workspace_id,
                    id=item.event_id,
                ).first()
                if event is None or event.event_type not in _LOCAL_EVENT_TYPES:
                    raise InvalidCommand("invalid local provider event")
                inbox, created = receive_inbox_message(
                    workspace_id=workspace_id,
                    consumer_id=PROVIDER_LOCAL_CONSUMER_ID,
                    event_id=event.id,
                )
                if not created and inbox.state == InboxState.PROCESSED:
                    item_deduplicated = True
                elif inbox.state == InboxState.RECEIVED:
                    complete_inbox_message(
                        workspace_id=workspace_id,
                        consumer_id=PROVIDER_LOCAL_CONSUMER_ID,
                        event_id=event.id,
                        result_digest=_safe_local_event_result_digest(event),
                        now=drain_time,
                    )
                    item_delivered = True
                else:
                    raise InvalidCommand("invalid local provider inbox state")
                acknowledge_outbox(
                    workspace_id=workspace_id,
                    outbox_id=item.id,
                    worker_id=PROVIDER_LOCAL_WORKER_ID,
                    now=drain_time,
                )
            delivered += int(item_delivered)
            deduplicated += int(item_deduplicated)
        except Exception:
            safe_error = {
                "code": "LOCAL_PROVIDER_DELIVERY_FAILED",
                "retryable": item.attempt_count < PROVIDER_LOCAL_MAX_ATTEMPTS,
            }
            if item.attempt_count >= PROVIDER_LOCAL_MAX_ATTEMPTS:
                dead_letter_outbox(
                    workspace_id=workspace_id,
                    outbox_id=item.id,
                    worker_id=PROVIDER_LOCAL_WORKER_ID,
                    error=safe_error,
                    now=drain_time,
                )
                dead_lettered += 1
            else:
                retry_outbox(
                    workspace_id=workspace_id,
                    outbox_id=item.id,
                    worker_id=PROVIDER_LOCAL_WORKER_ID,
                    next_attempt_at=drain_time + PROVIDER_LOCAL_RETRY_DELAY,
                    error=safe_error,
                    now=drain_time,
                )
                retry_scheduled += 1

    return LocalProviderDrainResult(
        claimed=len(claimed),
        delivered=delivered,
        deduplicated=deduplicated,
        retry_scheduled=retry_scheduled,
        dead_lettered=dead_lettered,
    )


def _post_commit_drain(*, workspace_id: uuid.UUID, correlation_id: str) -> None:
    try:
        drain_local_provider_events(
            workspace_id=workspace_id,
            correlation_id=correlation_id,
        )
    except Exception:
        # The command is already durable. The next provider command is the
        # explicit recovery trigger for any still-pending local delivery.
        return


def _schedule_post_commit_drain(*, workspace_id: uuid.UUID, correlation_id: str) -> None:
    transaction.on_commit(
        lambda: _post_commit_drain(
            workspace_id=workspace_id,
            correlation_id=correlation_id,
        )
    )


def _append_provider_event(
    *,
    connection: ProviderConnection,
    event_type: str,
    actor: dict,
    effective_principal: dict | None,
    correlation_id: str,
    causation_id: str | None,
    key_digest: str | None,
    extra_payload: dict | None = None,
) -> DomainEvent:
    payload = {
        "workspace_id": str(connection.workspace_id),
        "connection_id": str(connection.id),
        "connection_version": connection.aggregate_version,
        "status": connection.status,
        **(extra_payload or {}),
    }
    payload_schema = validate_provider_event_payload(
        aggregate_type="PROVIDER_CONNECTION",
        event_type=event_type,
        payload=payload,
    )
    event = DomainEvent.objects.create(
        workspace_id=connection.workspace_id,
        event_type=event_type,
        aggregate_type="PROVIDER_CONNECTION",
        aggregate_id=connection.id,
        aggregate_version=connection.aggregate_version,
        sequence=connection.aggregate_version,
        actor=actor,
        effective_principal=effective_principal,
        correlation_id=correlation_id,
        causation_id=causation_id,
        idempotency_key_digest=key_digest,
        classification=DataClassification.INTERNAL,
        payload_schema=payload_schema,
        payload=payload,
    )
    OutboxEvent.objects.create(
        workspace_id=connection.workspace_id,
        event_id=event.id,
        destination=PROVIDER_LOCAL_DESTINATION,
    )
    return event


def _append_reconciliation_event(
    *,
    operation: Operation,
    event_type: str,
    actor: dict,
    effective_principal: dict | None,
    correlation_id: str,
    error: dict | None = None,
) -> DomainEvent:
    payload = {
        "workspace_id": str(operation.workspace_id),
        "operation_id": str(operation.id),
        "operation_version": operation.aggregate_version,
        "status": operation.status,
    }
    if error is not None:
        payload["error"] = error
    payload_schema = validate_provider_event_payload(
        aggregate_type="OPERATION",
        event_type=event_type,
        payload=payload,
    )
    event = DomainEvent.objects.create(
        workspace_id=operation.workspace_id,
        event_type=event_type,
        aggregate_type="OPERATION",
        aggregate_id=operation.id,
        aggregate_version=operation.aggregate_version,
        sequence=operation.aggregate_version,
        actor=actor,
        effective_principal=effective_principal,
        correlation_id=correlation_id,
        causation_id=operation.causation_id,
        idempotency_key_digest=operation.idempotency_key_digest,
        classification=DataClassification.INTERNAL,
        payload_schema=payload_schema,
        payload=payload,
    )
    OutboxEvent.objects.create(
        workspace_id=operation.workspace_id,
        event_id=event.id,
        destination=PROVIDER_LOCAL_DESTINATION,
    )
    return event


def _resolve_connection_replay(*, workspace_id: uuid.UUID, resource_ref: dict | None) -> ProviderConnection:
    if not resource_ref or resource_ref.get("resource_type") != "PROVIDER_CONNECTION":
        raise ReplayResourceUnavailable
    connection = ProviderConnection.objects.find_by_id(
        workspace_id=workspace_id,
        record_id=resource_ref.get("resource_id"),
    )
    if connection is None:
        raise ReplayResourceUnavailable
    return connection


def _complete_idempotency(
    *,
    record: IdempotencyRecord,
    response_status: int,
    response_resource_ref: dict,
) -> tuple[str, dict]:
    response_digest = operation_response_digest(
        response_status=response_status,
        resource_ref=response_resource_ref,
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
    return response_digest, response_resource_ref


def register_fake_local_provider_connection(
    *,
    request,
    workspace_slug: str,
    display_name: str,
    raw_idempotency_key: str,
    configuration: dict | None = None,
) -> ProviderConnectionCommandResult:
    """Register the one exact local synthetic provider allowed by M0-S9A."""

    workspace = _workspace_for_provider_command(workspace_slug)
    correlation_id = correlation_id_for_request(request)
    configuration = {} if configuration is None else configuration
    if configuration != {}:
        raise InvalidCommand("the local fake provider accepts only empty configuration")
    if not isinstance(display_name, str) or not 1 <= len(display_name) <= 255:
        raise InvalidCommand("invalid provider display name")
    STATIC_PROVIDER_REGISTRY.registration_for(
        _FAKE_ADAPTER_KEY,
        adapter_version=_FAKE_ADAPTER_VERSION,
        provider_type=ProviderType.FAKE_LOCAL,
    )
    actor = _human_actor(request)
    canonical_request = canonical_json_bytes(
        {
            "adapter_key": _FAKE_ADAPTER_KEY,
            "adapter_version": _FAKE_ADAPTER_VERSION,
            "configuration": configuration,
            "display_name": display_name,
            "environment": ProviderEnvironment.LOCAL,
            "provider_type": ProviderTypeModel.FAKE_LOCAL,
        }
    )
    key_digest = idempotency_key_digest(raw_idempotency_key)
    request_digest = sha256_digest(canonical_request)
    configuration_digest = sha256_digest(canonical_json_bytes(configuration))
    principal_scope = f"{actor['actor_type']}:{actor['actor_id']}"
    command_scope = f"REGISTER_PROVIDER:{workspace.id}:{_FAKE_ADAPTER_KEY}"

    def context_builder():
        return build_provider_registration_context(
            request=request,
            workspace_slug=workspace_slug,
            correlation_id=correlation_id,
        )

    def mutation_callback(receipt, _observation):
        resource_ref = dict(receipt.resource_ref)
        assert_active_mutation_receipt(
            receipt,
            action=_REGISTER_ACTION,
            workspace_id=receipt.workspace_id,
            resource_ref=resource_ref,
        )
        drain_local_provider_events(
            workspace_id=receipt.workspace_id,
            correlation_id=correlation_id,
        )
        policy_decision_ref = policy_decision_ref_for_receipt(receipt)
        record = (
            IdempotencyRecord.objects.select_for_update()
            .filter(
                workspace_id=receipt.workspace_id,
                principal_scope=principal_scope,
                command_scope=command_scope,
                key_digest=key_digest,
            )
            .first()
        )
        if record is not None and record.request_digest != request_digest:
            _append_audit_event(
                workspace_id=receipt.workspace_id,
                action="CURVE.PROVIDER_CONNECTION.IDEMPOTENCY_CONFLICT",
                target_ref=resource_ref,
                outcome=AuditOutcome.NO_EFFECT,
                actor=actor,
                effective_principal=actor,
                correlation_id=correlation_id,
                key_digest=key_digest,
                policy_decision_ref=policy_decision_ref,
            )
            raise IdempotencyConflict
        if record is not None and record.state in IdempotencyRecord.TERMINAL_STATES:
            connection = _resolve_connection_replay(
                workspace_id=receipt.workspace_id,
                resource_ref=record.response_resource_ref,
            )
            _append_audit_event(
                workspace_id=receipt.workspace_id,
                action="CURVE.PROVIDER_CONNECTION.IDEMPOTENT_REPLAY",
                target_ref=record.response_resource_ref,
                outcome=AuditOutcome.NO_EFFECT,
                actor=actor,
                effective_principal=actor,
                correlation_id=correlation_id,
                key_digest=key_digest,
                policy_decision_ref=policy_decision_ref,
            )
            return ProviderConnectionCommandResult(
                connection=connection,
                replayed=True,
                response_status=record.response_status,
                response_digest=record.response_digest,
                response_resource_ref=record.response_resource_ref,
            )
        if record is not None:
            _append_audit_event(
                workspace_id=receipt.workspace_id,
                action="CURVE.PROVIDER_CONNECTION.ALREADY_IN_PROGRESS",
                target_ref=resource_ref,
                outcome=AuditOutcome.NO_EFFECT,
                actor=actor,
                effective_principal=actor,
                correlation_id=correlation_id,
                key_digest=key_digest,
                policy_decision_ref=policy_decision_ref,
            )
            raise CommandAlreadyInProgress
        existing = (
            ProviderConnection.objects.for_workspace(receipt.workspace_id)
            .filter(
                environment=ProviderEnvironment.LOCAL,
                adapter_key=_FAKE_ADAPTER_KEY,
            )
            .first()
        )
        if existing is not None:
            _append_audit_event(
                workspace_id=receipt.workspace_id,
                action="CURVE.PROVIDER_CONNECTION.DUPLICATE",
                target_ref=provider_connection_resource_ref(existing),
                outcome=AuditOutcome.NO_EFFECT,
                actor=actor,
                effective_principal=actor,
                correlation_id=correlation_id,
                key_digest=key_digest,
                policy_decision_ref=policy_decision_ref,
            )
            raise InvalidCommand("provider connection already exists")
        record, created = _create_idempotency_record(
            workspace_id=receipt.workspace_id,
            principal_scope=principal_scope,
            command_scope=command_scope,
            key_digest=key_digest,
            request_digest=request_digest,
            expires_at=timezone.now() + timedelta(days=1),
        )
        if record is None or not created:
            raise CommandAlreadyInProgress
        connection = ProviderConnection.objects.create(
            workspace_id=receipt.workspace_id,
            provider_type=ProviderTypeModel.FAKE_LOCAL,
            adapter_key=_FAKE_ADAPTER_KEY,
            adapter_version=_FAKE_ADAPTER_VERSION,
            environment=ProviderEnvironment.LOCAL,
            display_name=display_name,
            configuration_digest=configuration_digest,
            allowed_classifications=[DataClassification.INTERNAL],
            status=ProviderConnectionStatus.PENDING_VALIDATION,
            created_by=actor,
            updated_by=actor,
        )
        response_status = 201
        response_ref = provider_connection_resource_ref(connection)
        response_digest, response_ref = _complete_idempotency(
            record=record,
            response_status=response_status,
            response_resource_ref=response_ref,
        )
        _append_provider_event(
            connection=connection,
            event_type="curve.provider_connection.registered",
            actor=actor,
            effective_principal=actor,
            correlation_id=correlation_id,
            causation_id=None,
            key_digest=key_digest,
            extra_payload={"configuration_digest": configuration_digest},
        )
        _append_audit_event(
            workspace_id=receipt.workspace_id,
            action="CURVE.PROVIDER_CONNECTION.REGISTER",
            target_ref=response_ref,
            outcome=AuditOutcome.SUCCEEDED,
            actor=actor,
            effective_principal=actor,
            correlation_id=correlation_id,
            after_digest=response_digest,
            key_digest=key_digest,
            policy_decision_ref=policy_decision_ref,
        )
        _schedule_post_commit_drain(
            workspace_id=receipt.workspace_id,
            correlation_id=correlation_id,
        )
        return ProviderConnectionCommandResult(
            connection=connection,
            replayed=False,
            response_status=response_status,
            response_digest=response_digest,
            response_resource_ref=response_ref,
        )

    return execute_authorized_mutation(
        context_builder=context_builder,
        mutation_callback=mutation_callback,
        no_effect_exceptions=(IdempotencyConflict, CommandAlreadyInProgress, InvalidCommand),
    )


def _transition_provider_connection(
    *,
    request,
    workspace_slug: str,
    connection_id: uuid.UUID,
    expected_version: int,
    raw_idempotency_key: str,
    command: str,
) -> ProviderConnectionCommandResult:
    _workspace_for_provider_command(workspace_slug)
    correlation_id = correlation_id_for_request(request)
    if command not in _LIFECYCLE_TRANSITIONS:
        raise InvalidCommand("invalid provider lifecycle command")
    actor = _human_actor(request)
    canonical_request = canonical_json_bytes(
        {
            "command": command,
            "connection_id": str(connection_id),
            "expected_version": expected_version,
        }
    )
    key_digest = idempotency_key_digest(raw_idempotency_key)
    request_digest = sha256_digest(canonical_request)
    principal_scope = f"{actor['actor_type']}:{actor['actor_id']}"
    command_scope = f"{command}_PROVIDER:{connection_id}"

    def context_builder():
        return build_provider_administration_context(
            request=request,
            workspace_slug=workspace_slug,
            connection_id=connection_id,
            correlation_id=correlation_id,
        )

    def mutation_callback(receipt, _observation):
        receipt_ref = dict(receipt.resource_ref)
        assert_active_mutation_receipt(
            receipt,
            action=_ADMINISTER_ACTION,
            workspace_id=receipt.workspace_id,
            resource_ref=receipt_ref,
        )
        drain_local_provider_events(
            workspace_id=receipt.workspace_id,
            correlation_id=correlation_id,
        )
        policy_decision_ref = policy_decision_ref_for_receipt(receipt)
        connection = ProviderConnection.objects.find_by_id(
            workspace_id=receipt.workspace_id,
            record_id=connection_id,
            for_update=True,
        )
        if connection is None:
            raise CurveResourceNotFound
        record = (
            IdempotencyRecord.objects.select_for_update()
            .filter(
                workspace_id=receipt.workspace_id,
                principal_scope=principal_scope,
                command_scope=command_scope,
                key_digest=key_digest,
            )
            .first()
        )
        if record is not None and record.request_digest != request_digest:
            _append_audit_event(
                workspace_id=receipt.workspace_id,
                action="CURVE.PROVIDER_CONNECTION.IDEMPOTENCY_CONFLICT",
                target_ref=provider_connection_resource_ref(connection),
                outcome=AuditOutcome.NO_EFFECT,
                actor=actor,
                effective_principal=actor,
                correlation_id=correlation_id,
                key_digest=key_digest,
                policy_decision_ref=policy_decision_ref,
            )
            raise IdempotencyConflict
        if record is not None and record.state in IdempotencyRecord.TERMINAL_STATES:
            replayed_connection = _resolve_connection_replay(
                workspace_id=receipt.workspace_id,
                resource_ref=record.response_resource_ref,
            )
            _append_audit_event(
                workspace_id=receipt.workspace_id,
                action="CURVE.PROVIDER_CONNECTION.IDEMPOTENT_REPLAY",
                target_ref=record.response_resource_ref,
                outcome=AuditOutcome.NO_EFFECT,
                actor=actor,
                effective_principal=actor,
                correlation_id=correlation_id,
                key_digest=key_digest,
                policy_decision_ref=policy_decision_ref,
            )
            return ProviderConnectionCommandResult(
                connection=replayed_connection,
                replayed=True,
                response_status=record.response_status,
                response_digest=record.response_digest,
                response_resource_ref=record.response_resource_ref,
            )
        if record is not None:
            _append_audit_event(
                workspace_id=receipt.workspace_id,
                action="CURVE.PROVIDER_CONNECTION.ALREADY_IN_PROGRESS",
                target_ref=provider_connection_resource_ref(connection),
                outcome=AuditOutcome.NO_EFFECT,
                actor=actor,
                effective_principal=actor,
                correlation_id=correlation_id,
                key_digest=key_digest,
                policy_decision_ref=policy_decision_ref,
            )
            raise CommandAlreadyInProgress
        if connection.aggregate_version != expected_version:
            _append_audit_event(
                workspace_id=receipt.workspace_id,
                action="CURVE.PROVIDER_CONNECTION.VERSION_CONFLICT",
                target_ref=provider_connection_resource_ref(connection),
                outcome=AuditOutcome.NO_EFFECT,
                actor=actor,
                effective_principal=actor,
                correlation_id=correlation_id,
                key_digest=key_digest,
                policy_decision_ref=policy_decision_ref,
            )
            raise OptimisticConcurrencyError
        next_status = _LIFECYCLE_TRANSITIONS[command].get(connection.status)
        if next_status is None:
            _append_audit_event(
                workspace_id=receipt.workspace_id,
                action="CURVE.PROVIDER_CONNECTION.INVALID_TRANSITION",
                target_ref=provider_connection_resource_ref(connection),
                outcome=AuditOutcome.NO_EFFECT,
                actor=actor,
                effective_principal=actor,
                correlation_id=correlation_id,
                key_digest=key_digest,
                policy_decision_ref=policy_decision_ref,
            )
            raise InvalidProviderTransition
        record, created = _create_idempotency_record(
            workspace_id=receipt.workspace_id,
            principal_scope=principal_scope,
            command_scope=command_scope,
            key_digest=key_digest,
            request_digest=request_digest,
            expires_at=timezone.now() + timedelta(days=1),
        )
        if record is None or not created:
            raise CommandAlreadyInProgress
        connection.status = next_status
        connection.aggregate_version += 1
        connection.updated_by = actor
        connection.next_reconcile_at = None
        connection.last_error = None
        if command == "ENABLE":
            connection.current_capability = None
            connection.validated_at = None
            connection.validation_result_ref = None
            connection.last_reconciled_at = None
        connection.save()
        response_status = 200
        response_ref = provider_connection_resource_ref(connection)
        response_digest, response_ref = _complete_idempotency(
            record=record,
            response_status=response_status,
            response_resource_ref=response_ref,
        )
        _append_provider_event(
            connection=connection,
            event_type=_LIFECYCLE_EVENT_TYPES[command],
            actor=actor,
            effective_principal=actor,
            correlation_id=correlation_id,
            causation_id=None,
            key_digest=key_digest,
        )
        _append_audit_event(
            workspace_id=receipt.workspace_id,
            action=f"CURVE.PROVIDER_CONNECTION.{command}",
            target_ref=response_ref,
            outcome=AuditOutcome.SUCCEEDED,
            actor=actor,
            effective_principal=actor,
            correlation_id=correlation_id,
            after_digest=response_digest,
            key_digest=key_digest,
            policy_decision_ref=policy_decision_ref,
        )
        _schedule_post_commit_drain(
            workspace_id=receipt.workspace_id,
            correlation_id=correlation_id,
        )
        return ProviderConnectionCommandResult(
            connection=connection,
            replayed=False,
            response_status=response_status,
            response_digest=response_digest,
            response_resource_ref=response_ref,
        )

    return execute_authorized_mutation(
        context_builder=context_builder,
        mutation_callback=mutation_callback,
        no_effect_exceptions=(
            IdempotencyConflict,
            CommandAlreadyInProgress,
            OptimisticConcurrencyError,
            InvalidProviderTransition,
        ),
    )


def disable_provider_connection(**kwargs) -> ProviderConnectionCommandResult:
    return _transition_provider_connection(command="DISABLE", **kwargs)


def enable_provider_connection(**kwargs) -> ProviderConnectionCommandResult:
    return _transition_provider_connection(command="ENABLE", **kwargs)


def revoke_provider_connection(**kwargs) -> ProviderConnectionCommandResult:
    return _transition_provider_connection(command="REVOKE", **kwargs)


def _capability_observation_from_model(capability: ProviderCapabilityModel) -> ProviderCapabilityObservation:
    return ProviderCapabilityObservation(
        workspace_id=str(capability.workspace_id),
        connection_id=str(capability.connection_id),
        provider_type=ProviderType(capability.provider_type),
        adapter_key=capability.adapter_key,
        adapter_version=capability.adapter_version,
        protocol_versions=tuple(capability.protocol_versions),
        capabilities=tuple(
            ProviderCapability(
                name=item["name"],
                risk=ProviderCapabilityRisk(item["risk"]),
                enabled=item["enabled"],
                schema_uri=item.get("schema_uri"),
            )
            for item in capability.capabilities
        ),
        allowed_classifications=tuple(PolicyDataClassification(item) for item in capability.allowed_classifications),
    )


def _provider_call_context(
    *,
    operation: Operation,
    connection: ProviderConnection,
    monotonic: Callable[[], float],
    cancellation_token,
) -> ProviderCallContext:
    policy_ref = operation.policy_version_ref or {}
    decision_id = policy_ref.get("resource_id")
    from plane.curve.models import PolicyDecision

    decision = PolicyDecision.objects.filter(
        workspace_id=operation.workspace_id,
        id=decision_id,
    ).first()
    if decision is None:
        raise ProviderObservationRejected
    principal = operation.effective_principal or {}
    try:
        effective_principal = ActorRef(
            actor_type=ActorType(principal["actor_type"]),
            actor_id=principal["actor_id"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ProviderObservationRejected from error
    return ProviderCallContext.start(
        workspace_id=str(operation.workspace_id),
        connection_id=str(connection.id),
        effective_principal=effective_principal,
        correlation_id=operation.correlation_id,
        causation_id=f"provider-reconciliation:{operation.id}",
        idempotency_key_digest=operation.idempotency_key_digest,
        cancellation_token=cancellation_token,
        policy_key=decision.policy_key,
        policy_version=decision.policy_version,
        policy_manifest_digest=decision.policy_manifest_digest,
        provider_type=ProviderType(connection.provider_type),
        adapter_key=connection.adapter_key,
        adapter_version=connection.adapter_version,
        monotonic=monotonic,
    )


def _complete_reconciliation_operation(
    *,
    operation: Operation,
    status: str,
    now,
    result_ref: dict | None,
    error: dict | None,
) -> None:
    operation.status = status
    operation.aggregate_version += 1
    operation.started_at = operation.started_at or operation.created_at
    operation.completed_at = now
    operation.progress_percent = 100
    operation.result_ref = result_ref
    operation.error = error
    operation.updated_by = PROVIDER_SERVICE_ACTOR
    operation.save()


_OPTIMISTIC_CONCURRENCY_ERROR = {"code": "OPTIMISTIC_CONCURRENCY", "retryable": False}


def _append_stale_operation_result_audit(*, workspace_id, operation, connection) -> None:
    _append_audit_event(
        workspace_id=workspace_id,
        action="CURVE.PROVIDER_RECONCILIATION.OPTIMISTIC_CONCURRENCY",
        target_ref=operation_resource_ref(operation),
        outcome=AuditOutcome.NO_EFFECT,
        actor=PROVIDER_SERVICE_ACTOR,
        effective_principal=operation.effective_principal,
        correlation_id=operation.correlation_id,
        causation_id=str(operation.id),
        before_digest=sha256_digest(canonical_json_bytes(provider_connection_resource_ref(connection))),
    )


def _settle_stale_connection_operation(*, workspace_id, connection, operation, attempts, accepted_at, replayed):
    _complete_reconciliation_operation(
        operation=operation,
        status=OperationStatus.FAILED,
        now=accepted_at,
        result_ref=None,
        error=_OPTIMISTIC_CONCURRENCY_ERROR,
    )
    _append_reconciliation_event(
        operation=operation,
        event_type="curve.provider_reconciliation.failed",
        actor=PROVIDER_SERVICE_ACTOR,
        effective_principal=operation.effective_principal,
        correlation_id=operation.correlation_id,
        error=_OPTIMISTIC_CONCURRENCY_ERROR,
    )
    _append_audit_event(
        workspace_id=workspace_id,
        action="CURVE.PROVIDER_RECONCILIATION.VERSION_CONFLICT",
        target_ref=provider_connection_resource_ref(connection),
        outcome=AuditOutcome.NO_EFFECT,
        actor=PROVIDER_SERVICE_ACTOR,
        effective_principal=operation.effective_principal,
        correlation_id=operation.correlation_id,
        causation_id=str(operation.id),
    )
    _schedule_post_commit_drain(workspace_id=workspace_id, correlation_id=operation.correlation_id)
    return ProviderReconciliationCommandResult(
        operation=operation,
        connection=connection,
        capability=connection.current_capability,
        replayed=replayed,
        attempts=attempts,
    )


def _apply_reconciliation_success(
    *,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
    expected_connection_version: int,
    operation_id: uuid.UUID,
    expected_operation_version: int,
    observation: ProviderCapabilityObservation,
    attempts: int,
    accepted_at,
    replayed: bool = False,
) -> ProviderReconciliationCommandResult:
    stale_operation = False
    result = None
    with transaction.atomic():
        connection = ProviderConnection.objects.find_by_id(
            workspace_id=workspace_id, record_id=connection_id, for_update=True
        )
        operation = Operation.objects.select_for_update().filter(
            workspace_id=workspace_id, id=operation_id
        ).first()
        if connection is None or operation is None:
            raise CurveResourceNotFound
        if operation.aggregate_version != expected_operation_version or operation.status != OperationStatus.PENDING:
            _append_stale_operation_result_audit(
                workspace_id=workspace_id, operation=operation, connection=connection
            )
            stale_operation = True
        elif connection.aggregate_version != expected_connection_version:
            result = _settle_stale_connection_operation(
                workspace_id=workspace_id,
                connection=connection,
                operation=operation,
                attempts=attempts,
                accepted_at=accepted_at,
                replayed=replayed,
            )
        else:
            previous_status = connection.status
            current_observation = (
                _capability_observation_from_model(connection.current_capability)
                if connection.current_capability_id is not None
                else None
            )
            if (
                current_observation is not None
                and current_observation.capability_digest == observation.capability_digest
            ):
                capability = connection.current_capability
            else:
                current_version = (
                    ProviderCapabilityModel.objects.for_workspace(workspace_id)
                    .filter(connection_id=connection.id)
                    .order_by("-capability_version")
                    .values_list("capability_version", flat=True)
                    .first()
                )
                capability = ProviderCapabilityModel.objects.create(
                    workspace_id=workspace_id,
                    connection=connection,
                    connection_version=connection.aggregate_version + 1,
                    capability_version=(current_version or 0) + 1,
                    provider_type=observation.provider_type.value,
                    adapter_key=observation.adapter_key,
                    adapter_version=observation.adapter_version,
                    protocol_versions=list(observation.protocol_versions),
                    capabilities=[
                        {
                            "name": item.name,
                            "risk": item.risk.value,
                            "enabled": item.enabled,
                            **({"schema_uri": item.schema_uri} if item.schema_uri is not None else {}),
                        }
                        for item in observation.capabilities
                    ],
                    allowed_classifications=[item.value for item in observation.allowed_classifications],
                    observed_at=accepted_at,
                    validated_at=accepted_at,
                )
            result_ref = {
                "resource_type": "OPERATION",
                "resource_id": str(operation.id),
                "resource_version": operation.aggregate_version + 1,
            }
            connection.aggregate_version += 1
            connection.current_capability = capability
            connection.status = ProviderConnectionStatus.ACTIVE
            connection.validated_at = accepted_at
            connection.validation_result_ref = result_ref
            connection.last_reconciled_at = accepted_at
            connection.next_reconcile_at = accepted_at + PROVIDER_RECONCILIATION_INTERVAL
            connection.last_error = None
            connection.updated_by = PROVIDER_SERVICE_ACTOR
            connection.save()
            _complete_reconciliation_operation(
                operation=operation,
                status=OperationStatus.SUCCEEDED,
                now=accepted_at,
                result_ref=provider_connection_resource_ref(connection),
                error=None,
            )
            connection_event_type = (
                "curve.provider_connection.validated"
                if previous_status == ProviderConnectionStatus.PENDING_VALIDATION
                else "curve.provider_reconciliation.completed"
            )
            _append_provider_event(
                connection=connection,
                event_type=connection_event_type,
                actor=PROVIDER_SERVICE_ACTOR,
                effective_principal=operation.effective_principal,
                correlation_id=operation.correlation_id,
                causation_id=str(operation.id),
                key_digest=operation.idempotency_key_digest,
                extra_payload={
                    "capability_digest": observation.capability_digest,
                    "capability_version": capability.capability_version,
                },
            )
            _append_reconciliation_event(
                operation=operation,
                event_type="curve.provider_reconciliation.completed",
                actor=PROVIDER_SERVICE_ACTOR,
                effective_principal=operation.effective_principal,
                correlation_id=operation.correlation_id,
            )
            _append_audit_event(
                workspace_id=workspace_id,
                action="CURVE.PROVIDER_RECONCILIATION.COMPLETE",
                target_ref=provider_connection_resource_ref(connection),
                outcome=AuditOutcome.SUCCEEDED,
                actor=PROVIDER_SERVICE_ACTOR,
                effective_principal=operation.effective_principal,
                correlation_id=operation.correlation_id,
                causation_id=str(operation.id),
                after_digest=observation.capability_digest,
            )
            _schedule_post_commit_drain(
                workspace_id=workspace_id, correlation_id=operation.correlation_id
            )
            result = ProviderReconciliationCommandResult(
                operation=operation,
                connection=connection,
                capability=capability,
                replayed=replayed,
                attempts=attempts,
            )
    if stale_operation:
        raise OptimisticConcurrencyError
    if result is None:
        raise RuntimeError("reconciliation success completed without a result")
    return result


def _apply_reconciliation_failure(
    *,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
    expected_connection_version: int,
    operation_id: uuid.UUID,
    expected_operation_version: int,
    normalized_error: NormalizedProviderError,
    attempts: int,
    accepted_at,
    replayed: bool = False,
) -> ProviderReconciliationCommandResult:
    safe_error = {
        "code": normalized_error.code.value,
        "retryable": normalized_error.retryable,
    }
    stale_operation = False
    result = None
    with transaction.atomic():
        connection = ProviderConnection.objects.find_by_id(
            workspace_id=workspace_id,
            record_id=connection_id,
            for_update=True,
        )
        operation = (
            Operation.objects.select_for_update()
            .filter(
                workspace_id=workspace_id,
                id=operation_id,
            )
            .first()
        )
        if connection is None or operation is None:
            raise CurveResourceNotFound
        if operation.aggregate_version != expected_operation_version or operation.status != OperationStatus.PENDING:
            _append_stale_operation_result_audit(
                workspace_id=workspace_id, operation=operation, connection=connection
            )
            stale_operation = True
        elif connection.aggregate_version != expected_connection_version:
            result = _settle_stale_connection_operation(
                workspace_id=workspace_id,
                connection=connection,
                operation=operation,
                attempts=attempts,
                accepted_at=accepted_at,
                replayed=replayed,
            )
        else:
            ambiguous = normalized_error.code is ProviderErrorCode.AMBIGUOUS_MUTATION
            if not ambiguous:
                if connection.status in {
                    ProviderConnectionStatus.ACTIVE,
                    ProviderConnectionStatus.DEGRADED,
                }:
                    connection.status = ProviderConnectionStatus.DEGRADED
                connection.aggregate_version += 1
                connection.last_reconciled_at = accepted_at
                connection.next_reconcile_at = None
                connection.last_error = safe_error
                connection.updated_by = PROVIDER_SERVICE_ACTOR
                connection.validation_result_ref = {
                    "resource_type": "OPERATION",
                    "resource_id": str(operation.id),
                    "resource_version": operation.aggregate_version + 1,
                }
                connection.save()
                connection_event_type = (
                    "curve.provider_connection.degraded"
                    if connection.status == ProviderConnectionStatus.DEGRADED
                    else "curve.provider_reconciliation.failed"
                )
                _append_provider_event(
                    connection=connection,
                    event_type=connection_event_type,
                    actor=PROVIDER_SERVICE_ACTOR,
                    effective_principal=operation.effective_principal,
                    correlation_id=operation.correlation_id,
                    causation_id=str(operation.id),
                    key_digest=operation.idempotency_key_digest,
                    extra_payload={"error": safe_error},
                )
            _complete_reconciliation_operation(
                operation=operation,
                status=OperationStatus.FAILED,
                now=accepted_at,
                result_ref=None,
                error=safe_error,
            )
            _append_reconciliation_event(
                operation=operation,
                event_type="curve.provider_reconciliation.failed",
                actor=PROVIDER_SERVICE_ACTOR,
                effective_principal=operation.effective_principal,
                correlation_id=operation.correlation_id,
                error=safe_error,
            )
            _append_audit_event(
                workspace_id=workspace_id,
                action=(
                    "CURVE.PROVIDER_RECONCILIATION.NO_EFFECT"
                    if ambiguous
                    else "CURVE.PROVIDER_RECONCILIATION.FAIL"
                ),
                target_ref=provider_connection_resource_ref(connection),
                outcome=AuditOutcome.NO_EFFECT if ambiguous else AuditOutcome.FAILED,
                actor=PROVIDER_SERVICE_ACTOR,
                effective_principal=operation.effective_principal,
                correlation_id=operation.correlation_id,
                causation_id=str(operation.id),
            )
            _schedule_post_commit_drain(
                workspace_id=workspace_id, correlation_id=operation.correlation_id
            )
            result = ProviderReconciliationCommandResult(
                operation=operation,
                connection=connection,
                capability=connection.current_capability,
                replayed=replayed,
                attempts=attempts,
            )
    if stale_operation:
        raise OptimisticConcurrencyError
    if result is None:
        raise RuntimeError("reconciliation failure completed without a result")
    return result


def reconcile_provider_connection(
    *,
    request,
    workspace_slug: str,
    connection_id: uuid.UUID,
    expected_version: int,
    raw_idempotency_key: str,
    cancellation_token=None,
    monotonic: Callable[[], float] | None = None,
    accepted_at_factory: Callable = timezone.now,
) -> ProviderReconciliationCommandResult:
    """Run one explicit local reconciliation through the two-transaction boundary."""

    workspace = _workspace_for_provider_command(workspace_slug)
    correlation_id = correlation_id_for_request(request)
    actor = _human_actor(request)
    canonical_request = canonical_json_bytes(
        {
            "command": "RECONCILE_PROVIDER",
            "connection_id": str(connection_id),
            "expected_version": expected_version,
        }
    )
    principal_scope = f"{actor['actor_type']}:{actor['actor_id']}"
    command_scope = f"RECONCILE_PROVIDER:{connection_id}"
    key_digest = idempotency_key_digest(raw_idempotency_key)

    def context_builder():
        return build_provider_administration_context(
            request=request,
            workspace_slug=workspace_slug,
            connection_id=connection_id,
            correlation_id=correlation_id,
        )

    def mutation_callback(receipt, _observation):
        assert_active_mutation_receipt(
            receipt,
            action=_ADMINISTER_ACTION,
            workspace_id=receipt.workspace_id,
            resource_ref=dict(receipt.resource_ref),
        )
        drain_local_provider_events(
            workspace_id=receipt.workspace_id,
            correlation_id=correlation_id,
        )
        connection = ProviderConnection.objects.find_by_id(
            workspace_id=receipt.workspace_id,
            record_id=connection_id,
            for_update=True,
        )
        if connection is None:
            raise CurveResourceNotFound
        existing_record = (
            IdempotencyRecord.objects.select_for_update()
            .filter(
                workspace_id=receipt.workspace_id,
                principal_scope=principal_scope,
                command_scope=command_scope,
                key_digest=key_digest,
            )
            .first()
        )
        if existing_record is None:
            policy_ref = policy_decision_ref_for_receipt(receipt)
            if connection.aggregate_version != expected_version:
                _append_audit_event(
                    workspace_id=receipt.workspace_id,
                    action="CURVE.PROVIDER_RECONCILIATION.VERSION_CONFLICT",
                    target_ref=provider_connection_resource_ref(connection),
                    outcome=AuditOutcome.NO_EFFECT,
                    actor=actor,
                    effective_principal=actor,
                    correlation_id=correlation_id,
                    key_digest=key_digest,
                    policy_decision_ref=policy_ref,
                )
                raise OptimisticConcurrencyError
            if connection.status in {
                ProviderConnectionStatus.DISABLED,
                ProviderConnectionStatus.REVOKED,
            }:
                _append_audit_event(
                    workspace_id=receipt.workspace_id,
                    action="CURVE.PROVIDER_RECONCILIATION.INVALID_STATE",
                    target_ref=provider_connection_resource_ref(connection),
                    outcome=AuditOutcome.NO_EFFECT,
                    actor=actor,
                    effective_principal=actor,
                    correlation_id=correlation_id,
                    key_digest=key_digest,
                    policy_decision_ref=policy_ref,
                )
                raise InvalidProviderTransition
        operation_result = _create_operation_authorized(
            authorization_receipt=receipt,
            workspace_id=receipt.workspace_id,
            principal_scope=principal_scope,
            command_scope=command_scope,
            raw_idempotency_key=raw_idempotency_key,
            canonical_request=canonical_request,
            operation_type=OperationType.PROVIDER_RECONCILIATION,
            command_type="RECONCILE_PROVIDER",
            target=dict(receipt.resource_ref),
            actor=actor,
            effective_principal=actor,
            correlation_id=correlation_id,
            causation_id=f"provider-connection:{connection_id}",
            destination=PROVIDER_LOCAL_DESTINATION,
            authorization_action=_ADMINISTER_ACTION,
        )
        _schedule_post_commit_drain(
            workspace_id=receipt.workspace_id,
            correlation_id=correlation_id,
        )
        return operation_result

    operation_result = execute_authorized_mutation(
        context_builder=context_builder,
        mutation_callback=mutation_callback,
        no_effect_exceptions=(
            IdempotencyConflict,
            CommandAlreadyInProgress,
            OptimisticConcurrencyError,
            InvalidProviderTransition,
        ),
    )
    connection = ProviderConnection.objects.find_by_id(
        workspace_id=workspace.id,
        record_id=connection_id,
    )
    if connection is None:
        raise CurveResourceNotFound
    if operation_result.replayed and operation_result.operation.status != OperationStatus.PENDING:
        return ProviderReconciliationCommandResult(
            operation=operation_result.operation,
            connection=connection,
            capability=connection.current_capability,
            replayed=True,
            attempts=0,
        )
    expected_operation_version = operation_result.operation.aggregate_version
    monotonic = monotonic or time.monotonic
    try:
        adapter = STATIC_PROVIDER_REGISTRY.resolve(
            connection.adapter_key,
            adapter_version=connection.adapter_version,
            provider_type=ProviderType(connection.provider_type),
        )
        previous = (
            ProviderObservationRef.from_observation(_capability_observation_from_model(connection.current_capability))
            if connection.current_capability_id is not None
            else None
        )
        context = _provider_call_context(
            operation=operation_result.operation,
            connection=connection,
            monotonic=monotonic,
            cancellation_token=cancellation_token or NeverCancelled(),
        )
        execution = reconcile_with_retry(
            adapter,
            context,
            previous,
            monotonic=monotonic,
        )
        STATIC_PROVIDER_REGISTRY.validate_observation(execution.observation.capability_observation)
    except ProviderReconciliationExecutionError as error:
        return _apply_reconciliation_failure(
            workspace_id=workspace.id,
            connection_id=connection.id,
            expected_connection_version=expected_version,
            operation_id=operation_result.operation.id,
            expected_operation_version=expected_operation_version,
            normalized_error=error.error,
            attempts=error.attempts,
            accepted_at=accepted_at_factory(),
            replayed=operation_result.replayed,
        )
    except ProviderRegistryError:
        error = ProviderReconciliationFailed(
            NormalizedProviderError(ProviderErrorCode.NOT_SUPPORTED),
            1,
        )
        return _apply_reconciliation_failure(
            workspace_id=workspace.id,
            connection_id=connection.id,
            expected_connection_version=expected_version,
            operation_id=operation_result.operation.id,
            expected_operation_version=expected_operation_version,
            normalized_error=error.error,
            attempts=error.attempts,
            accepted_at=accepted_at_factory(),
            replayed=operation_result.replayed,
        )
    except Exception:
        return _apply_reconciliation_failure(
            workspace_id=workspace.id,
            connection_id=connection.id,
            expected_connection_version=expected_version,
            operation_id=operation_result.operation.id,
            expected_operation_version=expected_operation_version,
            normalized_error=NormalizedProviderError(ProviderErrorCode.TERMINAL),
            attempts=0,
            accepted_at=accepted_at_factory(),
            replayed=operation_result.replayed,
        )
    return _apply_reconciliation_success(
        workspace_id=workspace.id,
        connection_id=connection.id,
        expected_connection_version=expected_version,
        operation_id=operation_result.operation.id,
        expected_operation_version=expected_operation_version,
        observation=execution.observation.capability_observation,
        attempts=execution.attempts,
        accepted_at=accepted_at_factory(),
        replayed=operation_result.replayed,
    )
