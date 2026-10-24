# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Synchronous local association commands; no adapters or source writes."""

import uuid
from dataclasses import dataclass

from django.db import IntegrityError
from django.utils import timezone

from .models import AuditOutcome, DomainEvent, IdempotencyState, OutboxEvent, ProductState, ProjectAssociation
from .project_association_guards import (
    AssociationBindingGuardUnavailable,
    AssociationHasActiveBindings,
    assert_association_can_end,
)
from .project_association_policy import ASSOCIATE, END, READ, append_association_audit, execute_association_action
from .product_services import _command_identity, _load_or_create_idempotency
from .services import (
    CommandAlreadyInProgress,
    IdempotencyConflict,
    OptimisticConcurrencyError,
    ReplayResourceUnavailable,
    canonical_json_bytes,
    operation_response_digest,
)


EVENT_SCHEMA = "https://curve.example.invalid/candidates/project-association-event-v1.schema.json"
OUTBOX_DESTINATION = "CURVE_PROJECT_ASSOCIATION_LOCAL_V1"


class AssociationCommandError(Exception):
    code = "PROJECT_ASSOCIATION_COMMAND_REJECTED"
    status_code = 409
    field = None


class AssociationValidationError(AssociationCommandError):
    code = "PROJECT_ASSOCIATION_REQUEST_INVALID"
    status_code = 422

    def __init__(self, field=None):
        self.field = field


class AssociationPreconditionRequired(AssociationCommandError):
    code = "PROJECT_ASSOCIATION_PRECONDITION_REQUIRED"
    status_code = 428

    def __init__(self, field):
        self.field = field


class AssociationConflict(AssociationCommandError):
    code = "PROJECT_ASSOCIATION_ACTIVE_CONFLICT"


class AssociationStateConflict(AssociationCommandError):
    code = "PROJECT_ASSOCIATION_STATE_CONFLICT"


@dataclass(frozen=True)
class AssociationCommandResult:
    data: dict
    response_status: int
    replayed: bool = False


def _closed(payload, allowed):
    if type(payload) is not dict or set(payload) != set(allowed):
        raise AssociationValidationError


def _uuid(value, field):
    if not isinstance(value, (str, uuid.UUID)):
        raise AssociationValidationError(field)
    try:
        parsed = uuid.UUID(str(value))
        if isinstance(value, str) and str(parsed) != value:
            raise AssociationValidationError(field)
        return parsed
    except ValueError as error:
        raise AssociationValidationError(field) from error


def _version(value, field="If-Match"):
    if value is None:
        raise AssociationPreconditionRequired(field)
    if type(value) is not int or not 1 <= value <= 9007199254740991:
        raise AssociationValidationError(field)
    return value


def _idempotency(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise AssociationValidationError("Idempotency-Key")
    return value


def serialize_association(association):
    return {
        "schema_version": "1.0",
        "id": str(association.id),
        "workspace_id": str(association.workspace_id),
        "provider_installation_id": str(association.provider_installation_id),
        "source_project_id": str(association.source_project_id),
        "product_id": str(association.product_id),
        "state": association.state,
        "version": association.version,
        "effective_at": association.effective_at.isoformat(),
        "initiated_by": str(association.initiated_by),
        "policy_edition": association.policy_edition,
        "command_receipt_id": str(association.command_receipt_id),
        "source_observed_at": association.source_observed_at.isoformat(),
        "source_version": association.source_version,
        "ended_at": association.ended_at.isoformat() if association.ended_at else None,
        "ended_by": str(association.ended_by) if association.ended_by else None,
        "end_reason": association.end_reason,
        "end_receipt_id": str(association.end_receipt_id) if association.end_receipt_id else None,
    }


def association_ref(association):
    return {
        "resource_type": "PROJECT_ASSOCIATION",
        "resource_id": str(association.id),
        "resource_version": association.version,
    }


def _replay(*, receipt, context, record):
    ref = record.response_resource_ref or {}
    association = (
        ProjectAssociation.objects.find_by_id(
            workspace_id=context.workspace.id,
            record_id=ref.get("resource_id"),
            for_update=True,
        )
        if ref.get("resource_type") == "PROJECT_ASSOCIATION"
        else None
    )
    if (
        association is None
        or association.provider_installation_id != context.installation_id
        or association.product_id != context.product.id
        or association.source_project_id != context.project.id
        or (context.association is not None and association.id != context.association.id)
    ):
        raise ReplayResourceUnavailable
    event = DomainEvent.objects.filter(
        workspace_id=context.workspace.id,
        aggregate_type="PROJECT_ASSOCIATION",
        aggregate_id=association.id,
        aggregate_version=ref.get("resource_version"),
    ).first()
    if event is None or "association" not in event.payload:
        raise ReplayResourceUnavailable
    # The immutable event carries the original safe DTO. Current aggregate or
    # source state cannot silently rewrite an idempotent command's outcome.
    data = event.payload["association"]
    append_association_audit(receipt, target_ref=ref, outcome=AuditOutcome.NO_EFFECT, key_digest=record.key_digest)
    return AssociationCommandResult(data, record.response_status, True)


def _complete(*, receipt, record, association, event_id, event_type, response_status):
    data = serialize_association(association)
    event = DomainEvent.objects.create(
        id=event_id,
        workspace_id=association.workspace_id,
        event_type=event_type,
        aggregate_type="PROJECT_ASSOCIATION",
        aggregate_id=association.id,
        aggregate_version=association.version,
        sequence=association.version,
        actor=receipt.actor,
        effective_principal=receipt.actor,
        correlation_id=receipt.correlation_id,
        idempotency_key_digest=record.key_digest,
        classification="INTERNAL",
        payload_schema=EVENT_SCHEMA,
        payload={
            "schema_version": "1.0",
            "event_type": event_type,
            "association": data,
            "policy_decision_id": str(receipt.decision_id),
        },
        occurred_at=timezone.now(),
    )
    OutboxEvent.objects.create(workspace_id=association.workspace_id, event_id=event.id, destination=OUTBOX_DESTINATION)
    ref = association_ref(association)
    digest = operation_response_digest(response_status=response_status, resource_ref=ref)
    append_association_audit(
        receipt, target_ref=ref, outcome=AuditOutcome.SUCCEEDED, key_digest=record.key_digest, after_digest=digest
    )
    record.state = IdempotencyState.COMPLETED
    record.response_status, record.response_resource_ref, record.response_digest = response_status, ref, digest
    record.completed_at = timezone.now()
    record.save(update_fields=["state", "response_status", "response_resource_ref", "response_digest", "completed_at"])
    return AssociationCommandResult(data, response_status)


_NO_EFFECT = (
    AssociationCommandError,
    AssociationBindingGuardUnavailable,
    AssociationHasActiveBindings,
    IdempotencyConflict,
    CommandAlreadyInProgress,
    OptimisticConcurrencyError,
    ReplayResourceUnavailable,
    IntegrityError,
)


def associate_project(*, request, workspace_slug, product_id, payload, expected_version, raw_idempotency_key):
    _closed(payload, {"provider_installation_id", "source_project_id"})
    installation = _uuid(payload["provider_installation_id"], "provider_installation_id")
    project_id = _uuid(payload["source_project_id"], "source_project_id")
    _version(expected_version)
    _idempotency(raw_idempotency_key)
    subject = {
        "command_type": "ASSOCIATE",
        "product_id": str(product_id),
        "provider_installation_id": str(installation),
        "source_project_id": str(project_id),
        "expected_product_version": expected_version,
    }

    def callback(receipt, context):
        identity = _command_identity(
            receipt,
            command_scope=f"{ASSOCIATE}:{product_id}",
            raw_idempotency_key=raw_idempotency_key,
            canonical_request=canonical_json_bytes(subject),
        )
        record, _, replay = _load_or_create_idempotency(workspace_id=context.workspace.id, identity=identity)
        if replay:
            return _replay(receipt=receipt, context=context, record=record)
        if context.product.version != expected_version:
            raise OptimisticConcurrencyError
        if context.product.state != ProductState.ACTIVE or context.project.archived_at is not None:
            raise AssociationStateConflict
        if ProjectAssociation.objects.filter(
            workspace_id=context.workspace.id,
            provider_installation_id=installation,
            source_project_id=project_id,
            state="ACTIVE",
        ).exists():
            raise AssociationConflict
        event_id = uuid.uuid4()
        association = ProjectAssociation.objects.create(
            workspace_id=context.workspace.id,
            provider_installation_id=context.installation_id,
            source_project_id=context.project.id,
            product_id=context.product.id,
            initiated_by=context.user.id,
            command_receipt_id=event_id,
            source_version=context.project.updated_at.isoformat(),
        )
        return _complete(
            receipt=receipt,
            record=record,
            association=association,
            event_id=event_id,
            event_type="curve.project_association.associated",
            response_status=201,
        )

    return execute_association_action(
        request=request,
        workspace_slug=workspace_slug,
        action=ASSOCIATE,
        product_id=product_id,
        source_project_id=project_id,
        provider_installation_id=installation,
        command_subject=subject,
        callback=callback,
        no_effect_exceptions=_NO_EFFECT,
    )


def end_association(*, request, workspace_slug, association_id, payload, expected_version, raw_idempotency_key):
    if type(payload) is dict and "expected_product_version" not in payload:
        raise AssociationPreconditionRequired("expected_product_version")
    _closed(payload, {"expected_product_version", "reason"})
    product_version = _version(payload["expected_product_version"], "expected_product_version")
    _version(expected_version)
    _idempotency(raw_idempotency_key)
    reason = payload["reason"]
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
        raise AssociationValidationError("reason")
    subject = {
        "command_type": "END",
        "association_id": str(association_id),
        "expected_version": expected_version,
        "expected_product_version": product_version,
        "reason": reason,
    }

    def callback(receipt, context):
        identity = _command_identity(
            receipt,
            command_scope=f"{END}:{association_id}",
            raw_idempotency_key=raw_idempotency_key,
            canonical_request=canonical_json_bytes(
                {
                    **subject,
                    "provider_installation_id": str(context.installation_id),
                }
            ),
        )
        record, _, replay = _load_or_create_idempotency(workspace_id=context.workspace.id, identity=identity)
        if replay:
            return _replay(receipt=receipt, context=context, record=record)
        association = context.association
        if association.version != expected_version or context.product.version != product_version:
            raise OptimisticConcurrencyError
        if association.state != "ACTIVE":
            raise AssociationStateConflict
        assert_association_can_end(workspace_id=context.workspace.id, association_id=association.id)
        association.state, association.version = "ENDED", association.version + 1
        association.ended_at, association.ended_by = timezone.now(), context.user.id
        association.end_reason, association.end_receipt_id = reason, uuid.uuid4()
        association.save(update_fields=["state", "version", "ended_at", "ended_by", "end_reason", "end_receipt_id"])
        return _complete(
            receipt=receipt,
            record=record,
            association=association,
            event_id=association.end_receipt_id,
            event_type="curve.project_association.ended",
            response_status=200,
        )

    return execute_association_action(
        request=request,
        workspace_slug=workspace_slug,
        action=END,
        association_id=association_id,
        command_subject=subject,
        callback=callback,
        no_effect_exceptions=_NO_EFFECT,
    )


def read_association(*, request, workspace_slug, association_id):
    def callback(receipt, context):
        append_association_audit(receipt, target_ref=association_ref(context.association), outcome=AuditOutcome.ALLOWED)
        return AssociationCommandResult(serialize_association(context.association), 200)

    return execute_association_action(
        request=request,
        workspace_slug=workspace_slug,
        action=READ,
        association_id=association_id,
        command_subject={"association_id": str(association_id)},
        callback=callback,
    )
