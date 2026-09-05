# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import IntegrityError, transaction
from django.utils import timezone

from plane.curve.models import (
    AuditOutcome,
    DataClassification,
    DomainEvent,
    IdempotencyRecord,
    IdempotencyState,
    OutboxEvent,
    Product,
    ProductState,
)
from plane.curve.product_guards import (
    ProductHasNonTerminalInitiative,
    ProductInitiativeGuardUnavailable,
    assert_product_can_archive,
)
from plane.curve.product_policy import append_product_mutation_audit, execute_product_mutation
from plane.curve.product_serialization import serialize_product
from plane.curve.services import (
    CommandAlreadyInProgress,
    IdempotencyConflict,
    OptimisticConcurrencyError,
    ReplayResourceUnavailable,
    _create_idempotency_record,
    _lock_audit_sequence,
    canonical_json_bytes,
    idempotency_key_digest,
    operation_response_digest,
    sha256_digest,
)
from plane.db.models import WorkspaceMember


PRODUCT_EVENT_SCHEMA = "https://curve.example.invalid/contracts/schemas/product-event-v1.schema.json"
PRODUCT_OUTBOX_DESTINATION = "CURVE_PRODUCT_LOCAL_V1"
PRODUCT_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")
PRODUCT_DESCRIPTION_MAX_LENGTH = 10_000


class ProductCommandError(Exception):
    code = "PRODUCT_COMMAND_ERROR"
    field = None


class ProductValidationError(ProductCommandError):
    code = "PRODUCT_REQUEST_INVALID"

    def __init__(self, *, field=None):
        self.field = field


class ProductKeyConflict(ProductCommandError):
    code = "PRODUCT_KEY_CONFLICT"


class ProductStateConflict(ProductCommandError):
    code = "PRODUCT_STATE_CONFLICT"


class ProductNoChanges(ProductCommandError):
    code = "PRODUCT_NO_CHANGES"


class ProductTargetOwnerInactive(ProductCommandError):
    code = "PRODUCT_TARGET_OWNER_INACTIVE"


@dataclass(frozen=True, slots=True)
class ProductCommandResult:
    product: Product
    replayed: bool
    response_status: int
    response_digest: str
    response_resource_ref: dict


def product_resource_ref(product: Product) -> dict:
    return {
        "resource_type": "PRODUCT",
        "resource_id": str(product.id),
        "resource_version": product.version,
    }


def _validate_keys(payload, allowed, *, required=()):
    if not isinstance(payload, dict) or set(payload) - set(allowed) or not set(required).issubset(payload):
        raise ProductValidationError


def _validate_name(value):
    if not isinstance(value, str) or not value or len(value) > 255:
        raise ProductValidationError(field="name")
    return value


def _validate_description(value):
    if value is not None and (not isinstance(value, str) or len(value) > PRODUCT_DESCRIPTION_MAX_LENGTH):
        raise ProductValidationError(field="description")
    return value


def _validate_timezone(value):
    if not isinstance(value, str) or not value or len(value) > 255:
        raise ProductValidationError(field="timezone")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ProductValidationError(field="timezone") from error
    return value


def _validate_key(value):
    if not isinstance(value, str) or PRODUCT_KEY_PATTERN.fullmatch(value) is None:
        raise ProductValidationError(field="key")
    return value


def _validate_expected_version(value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ProductValidationError(field="If-Match")
    return value


def _validate_idempotency_key(value):
    if not isinstance(value, str) or not value or len(value) > 500:
        raise ProductValidationError(field="Idempotency-Key")
    return value


def _command_identity(receipt, *, command_scope, raw_idempotency_key, canonical_request):
    _validate_idempotency_key(raw_idempotency_key)
    return {
        "principal_scope": f"HUMAN:{receipt.actor['actor_id']}",
        "command_scope": command_scope,
        "key_digest": idempotency_key_digest(raw_idempotency_key),
        "request_digest": sha256_digest(canonical_request),
        "expires_at": timezone.now() + timedelta(days=1),
    }


def _load_or_create_idempotency(*, workspace_id, identity):
    record = (
        IdempotencyRecord.objects.select_for_update()
        .filter(
            workspace_id=workspace_id,
            principal_scope=identity["principal_scope"],
            command_scope=identity["command_scope"],
            key_digest=identity["key_digest"],
        )
        .first()
    )
    created = False
    if record is None:
        record, created = _create_idempotency_record(workspace_id=workspace_id, **identity)
        if record is None:
            record = IdempotencyRecord.objects.select_for_update().get(
                workspace_id=workspace_id,
                principal_scope=identity["principal_scope"],
                command_scope=identity["command_scope"],
                key_digest=identity["key_digest"],
            )
    if record.request_digest != identity["request_digest"]:
        raise IdempotencyConflict
    if record.state in IdempotencyRecord.TERMINAL_STATES:
        return record, False, True
    if not created:
        raise CommandAlreadyInProgress
    return record, True, False


def _resolve_replay(*, workspace_id, record):
    ref = record.response_resource_ref
    if not ref or ref.get("resource_type") != "PRODUCT":
        raise ReplayResourceUnavailable
    product = Product.objects.find_by_id(
        workspace_id=workspace_id,
        record_id=ref.get("resource_id"),
        for_update=True,
    )
    if product is None:
        raise ReplayResourceUnavailable
    return ProductCommandResult(
        product=product,
        replayed=True,
        response_status=record.response_status,
        response_digest=record.response_digest,
        response_resource_ref=record.response_resource_ref,
    )


def _append_product_event(*, product, event_type, actor, correlation_id, key_digest, details):
    occurred_at = timezone.now()
    payload = {
        "schema_version": "1.0",
        "workspace_id": str(product.workspace_id),
        "product_id": str(product.id),
        "product_version": product.version,
        "event_type": event_type,
        "actor": actor,
        "occurred_at": occurred_at.isoformat(),
        **details,
    }
    event = DomainEvent.objects.create(
        workspace_id=product.workspace_id,
        event_type=f"curve.product.{event_type.lower()}",
        aggregate_type="PRODUCT",
        aggregate_id=product.id,
        aggregate_version=product.version,
        sequence=product.version,
        actor=actor,
        effective_principal=actor,
        correlation_id=correlation_id,
        idempotency_key_digest=key_digest,
        classification=DataClassification.INTERNAL,
        payload_schema=PRODUCT_EVENT_SCHEMA,
        payload=payload,
        occurred_at=occurred_at,
    )
    OutboxEvent.objects.create(
        workspace_id=product.workspace_id,
        event_id=event.id,
        destination=PRODUCT_OUTBOX_DESTINATION,
    )


def _complete_command(*, receipt, record, product, response_status, key_digest, before_digest=None):
    ref = product_resource_ref(product)
    response_digest = operation_response_digest(response_status=response_status, resource_ref=ref)
    append_product_mutation_audit(
        receipt,
        action=receipt.action,
        target_ref=ref,
        outcome=AuditOutcome.SUCCEEDED,
        before_digest=before_digest,
        after_digest=response_digest,
        key_digest=key_digest,
    )
    record.state = IdempotencyState.COMPLETED
    record.response_status = response_status
    record.response_digest = response_digest
    record.response_resource_ref = ref
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
    return ProductCommandResult(
        product=product,
        replayed=False,
        response_status=response_status,
        response_digest=response_digest,
        response_resource_ref=ref,
    )


def _replay_with_audit(*, receipt, record):
    result = _resolve_replay(workspace_id=receipt.workspace_id, record=record)
    append_product_mutation_audit(
        receipt,
        action=f"{receipt.action}.IDEMPOTENT_REPLAY",
        target_ref=product_resource_ref(result.product),
        outcome=AuditOutcome.NO_EFFECT,
        key_digest=record.key_digest,
    )
    return result


def _before_digest(product):
    return sha256_digest(canonical_json_bytes(serialize_product(product)))


PRODUCT_NO_EFFECT_EXCEPTIONS = (
    ProductCommandError,
    IdempotencyConflict,
    CommandAlreadyInProgress,
    OptimisticConcurrencyError,
    ReplayResourceUnavailable,
    ProductHasNonTerminalInitiative,
    ProductInitiativeGuardUnavailable,
    IntegrityError,
)


def create_product(*, request, workspace_slug, payload, raw_idempotency_key):
    def callback(receipt, workspace, _product):
        with transaction.atomic():
            _validate_keys(payload, {"key", "name", "description", "timezone"}, required={"key", "name", "timezone"})
            key = _validate_key(payload["key"])
            name = _validate_name(payload["name"])
            description = _validate_description(payload.get("description"))
            timezone_name = _validate_timezone(payload["timezone"])
            canonical_request = canonical_json_bytes(
                {
                    "command_type": "CREATE_PRODUCT",
                    "key": key,
                    "name": name,
                    "description": description,
                    "timezone": timezone_name,
                }
            )
            identity = _command_identity(
                receipt,
                command_scope="CURVE.PRODUCT.CREATE",
                raw_idempotency_key=raw_idempotency_key,
                canonical_request=canonical_request,
            )
            lock_id = uuid.uuid5(uuid.NAMESPACE_URL, f"curve-product:{workspace.id}:{key}")
            _lock_audit_sequence(workspace.id, "PRODUCT_KEY", lock_id)
            record, _, replay = _load_or_create_idempotency(workspace_id=workspace.id, identity=identity)
            if replay:
                return _replay_with_audit(receipt=receipt, record=record)
            if Product.objects.filter(workspace_id=workspace.id, key=key).exists():
                raise ProductKeyConflict
            actor = dict(receipt.actor)
            product = Product.objects.create(
                workspace_id=workspace.id,
                key=key,
                name=name,
                description=description,
                timezone=timezone_name,
                owner_user_id=uuid.UUID(receipt.actor["actor_id"]),
                created_by=actor,
                updated_by=actor,
            )
            _append_product_event(
                product=product,
                event_type="PRODUCT_CREATED",
                actor=actor,
                correlation_id=receipt.correlation_id,
                key_digest=identity["key_digest"],
                details={
                    "key": product.key,
                    "current_timezone": product.timezone,
                    "current_owner_user_id": str(product.owner_user_id),
                    "current_state": product.state,
                },
            )
            return _complete_command(
                receipt=receipt,
                record=record,
                product=product,
                response_status=201,
                key_digest=identity["key_digest"],
            )

    return execute_product_mutation(
        request=request,
        workspace_slug=workspace_slug,
        action="CURVE.PRODUCT.CREATE",
        callback=callback,
        no_effect_exceptions=PRODUCT_NO_EFFECT_EXCEPTIONS,
    )


def update_product_metadata(*, request, workspace_slug, product_id, expected_version, payload, raw_idempotency_key):
    def callback(receipt, _workspace, product):
        with transaction.atomic():
            _validate_expected_version(expected_version)
            _validate_keys(payload, {"name", "description", "timezone"})
            if not payload:
                raise ProductValidationError
            values = {}
            if "name" in payload:
                values["name"] = _validate_name(payload["name"])
            if "description" in payload:
                values["description"] = _validate_description(payload["description"])
            if "timezone" in payload:
                values["timezone"] = _validate_timezone(payload["timezone"])
            canonical_request = canonical_json_bytes(
                {
                    "command_type": "UPDATE_PRODUCT_METADATA",
                    "product_id": str(product_id),
                    "expected_version": expected_version,
                    **values,
                }
            )
            identity = _command_identity(
                receipt,
                command_scope=f"CURVE.PRODUCT.UPDATE_METADATA:{product_id}",
                raw_idempotency_key=raw_idempotency_key,
                canonical_request=canonical_request,
            )
            record, _, replay = _load_or_create_idempotency(workspace_id=receipt.workspace_id, identity=identity)
            if replay:
                return _replay_with_audit(receipt=receipt, record=record)
            if product.version != expected_version:
                raise OptimisticConcurrencyError
            changed_fields = [
                field
                for field in ("name", "description", "timezone")
                if field in values and getattr(product, field) != values[field]
            ]
            if not changed_fields:
                raise ProductNoChanges
            before_timezone = product.timezone
            before_digest = _before_digest(product)
            for field in changed_fields:
                setattr(product, field, values[field])
            product.version += 1
            product.updated_by = dict(receipt.actor)
            product.save(update_fields=[*changed_fields, "version", "updated_by", "updated_at"])
            details = {"changed_fields": changed_fields}
            if "timezone" in changed_fields:
                details.update(previous_timezone=before_timezone, current_timezone=product.timezone)
            _append_product_event(
                product=product,
                event_type="PRODUCT_METADATA_UPDATED",
                actor=dict(receipt.actor),
                correlation_id=receipt.correlation_id,
                key_digest=identity["key_digest"],
                details=details,
            )
            return _complete_command(
                receipt=receipt,
                record=record,
                product=product,
                response_status=200,
                key_digest=identity["key_digest"],
                before_digest=before_digest,
            )

    return execute_product_mutation(
        request=request,
        workspace_slug=workspace_slug,
        action="CURVE.PRODUCT.UPDATE_METADATA",
        product_id=product_id,
        callback=callback,
        no_effect_exceptions=PRODUCT_NO_EFFECT_EXCEPTIONS,
    )


def reassign_product_owner(*, request, workspace_slug, product_id, expected_version, payload, raw_idempotency_key):
    def callback(receipt, workspace, product):
        with transaction.atomic():
            _validate_expected_version(expected_version)
            _validate_keys(payload, {"owner_user_id"}, required={"owner_user_id"})
            try:
                owner_user_id = uuid.UUID(str(payload["owner_user_id"]))
            except (TypeError, ValueError) as error:
                raise ProductValidationError(field="owner_user_id") from error
            canonical_request = canonical_json_bytes(
                {
                    "command_type": "REASSIGN_PRODUCT_OWNER",
                    "product_id": str(product_id),
                    "expected_version": expected_version,
                    "owner_user_id": str(owner_user_id),
                }
            )
            identity = _command_identity(
                receipt,
                command_scope=f"CURVE.PRODUCT.REASSIGN_OWNER:{product_id}",
                raw_idempotency_key=raw_idempotency_key,
                canonical_request=canonical_request,
            )
            record, _, replay = _load_or_create_idempotency(workspace_id=workspace.id, identity=identity)
            if replay:
                return _replay_with_audit(receipt=receipt, record=record)
            if product.version != expected_version:
                raise OptimisticConcurrencyError
            if not WorkspaceMember.objects.filter(
                workspace_id=workspace.id,
                member_id=owner_user_id,
                is_active=True,
            ).exists():
                raise ProductTargetOwnerInactive
            if product.owner_user_id == owner_user_id:
                raise ProductNoChanges
            previous_owner = product.owner_user_id
            before_digest = _before_digest(product)
            product.owner_user_id = owner_user_id
            product.version += 1
            product.updated_by = dict(receipt.actor)
            product.save(update_fields=["owner_user_id", "version", "updated_by", "updated_at"])
            _append_product_event(
                product=product,
                event_type="PRODUCT_OWNER_REASSIGNED",
                actor=dict(receipt.actor),
                correlation_id=receipt.correlation_id,
                key_digest=identity["key_digest"],
                details={
                    "changed_fields": ["owner"],
                    "previous_owner_user_id": str(previous_owner),
                    "current_owner_user_id": str(product.owner_user_id),
                },
            )
            return _complete_command(
                receipt=receipt,
                record=record,
                product=product,
                response_status=200,
                key_digest=identity["key_digest"],
                before_digest=before_digest,
            )

    return execute_product_mutation(
        request=request,
        workspace_slug=workspace_slug,
        action="CURVE.PRODUCT.REASSIGN_OWNER",
        product_id=product_id,
        callback=callback,
        no_effect_exceptions=PRODUCT_NO_EFFECT_EXCEPTIONS,
    )


def _change_product_state(*, request, workspace_slug, product_id, expected_version, raw_idempotency_key, target_state):
    action_suffix = "ARCHIVE" if target_state == ProductState.ARCHIVED else "RESTORE"
    event_type = "PRODUCT_ARCHIVED" if target_state == ProductState.ARCHIVED else "PRODUCT_RESTORED"
    required_state = ProductState.ACTIVE if target_state == ProductState.ARCHIVED else ProductState.ARCHIVED

    def callback(receipt, workspace, product):
        with transaction.atomic():
            _validate_expected_version(expected_version)
            canonical_request = canonical_json_bytes(
                {
                    "command_type": f"{action_suffix}_PRODUCT",
                    "product_id": str(product_id),
                    "expected_version": expected_version,
                }
            )
            identity = _command_identity(
                receipt,
                command_scope=f"CURVE.PRODUCT.{action_suffix}:{product_id}",
                raw_idempotency_key=raw_idempotency_key,
                canonical_request=canonical_request,
            )
            record, _, replay = _load_or_create_idempotency(workspace_id=workspace.id, identity=identity)
            if replay:
                return _replay_with_audit(receipt=receipt, record=record)
            if product.version != expected_version:
                raise OptimisticConcurrencyError
            if product.state != required_state:
                raise ProductStateConflict
            if target_state == ProductState.ARCHIVED:
                assert_product_can_archive(workspace_id=workspace.id, product_id=product.id)
            previous_state = product.state
            before_digest = _before_digest(product)
            actor = dict(receipt.actor)
            product.state = target_state
            product.version += 1
            product.updated_by = actor
            if target_state == ProductState.ARCHIVED:
                product.archived_at = timezone.now()
                product.archived_by = actor
            else:
                product.archived_at = None
                product.archived_by = None
            product.save(
                update_fields=[
                    "state",
                    "version",
                    "updated_by",
                    "archived_at",
                    "archived_by",
                    "updated_at",
                ]
            )
            _append_product_event(
                product=product,
                event_type=event_type,
                actor=actor,
                correlation_id=receipt.correlation_id,
                key_digest=identity["key_digest"],
                details={
                    "changed_fields": ["state"],
                    "previous_state": previous_state,
                    "current_state": target_state,
                },
            )
            return _complete_command(
                receipt=receipt,
                record=record,
                product=product,
                response_status=200,
                key_digest=identity["key_digest"],
                before_digest=before_digest,
            )

    return execute_product_mutation(
        request=request,
        workspace_slug=workspace_slug,
        action=f"CURVE.PRODUCT.{action_suffix}",
        product_id=product_id,
        callback=callback,
        no_effect_exceptions=PRODUCT_NO_EFFECT_EXCEPTIONS,
    )


def archive_product(*, request, workspace_slug, product_id, expected_version, raw_idempotency_key):
    return _change_product_state(
        request=request,
        workspace_slug=workspace_slug,
        product_id=product_id,
        expected_version=expected_version,
        raw_idempotency_key=raw_idempotency_key,
        target_state=ProductState.ARCHIVED,
    )


def restore_product(*, request, workspace_slug, product_id, expected_version, raw_idempotency_key):
    return _change_product_state(
        request=request,
        workspace_slug=workspace_slug,
        product_id=product_id,
        expected_version=expected_version,
        raw_idempotency_key=raw_idempotency_key,
        target_state=ProductState.ACTIVE,
    )
