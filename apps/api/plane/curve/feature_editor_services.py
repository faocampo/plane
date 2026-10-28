# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Versioned Feature editor commands; native qualification is a separate gate."""

from dataclasses import dataclass
import uuid

from django.db import connection, IntegrityError
from django.utils import timezone

from plane.curve.feature_editor_events import build_editor_event
from plane.curve.feature_editor_input import (
    FeatureEditorInputError,
    normalize_editor_command,
)
from plane.curve.feature_editor_policy import (
    append_audit,
    assert_receipt,
    execute_editor_mutation,
    scoped_grant,
)
from plane.curve.models import (
    AuditOutcome,
    DataClassification,
    DomainEvent,
    IdempotencyState,
    OutboxEvent,
)
from plane.curve.product_services import (
    _command_identity,
    _load_or_create_idempotency,
    ProductValidationError,
)
from plane.curve.services import (
    CommandAlreadyInProgress,
    IdempotencyConflict,
    OptimisticConcurrencyError,
    ReplayResourceUnavailable,
    canonical_json_bytes,
    operation_response_digest,
)


class FeatureEditorCommandError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class FeatureEditorCommandResult:
    resource_ref: dict
    response_status: int
    response_digest: str
    replayed: bool


def _ref(grant):
    return {
        "resource_type": "FEATURE_EDITOR_GRANT",
        "resource_id": str(grant["id"]),
        "resource_version": grant["version"],
    }


def _snapshot(grant):
    return {
        **_ref(grant),
        "member_id": str(grant["member_id"]),
        "membership_id": str(grant["membership_id"]),
        "membership_generation": grant["membership_generation"],
        "granted_by": str(grant["granted_by"]),
        "granted_at": grant["granted_at"].isoformat(),
        "revoked_by": str(grant["revoked_by"]) if grant["revoked_by"] is not None else None,
        "revoked_at": grant["revoked_at"].isoformat() if grant["revoked_at"] is not None else None,
    }


def _event(receipt, grant, before, key_digest, at):
    assert_receipt(receipt)
    payload = build_editor_event(
        action=receipt.action,
        workspace_id=receipt.workspace_id,
        product_id=receipt.product_id,
        before=before,
        after=_snapshot(grant),
        actor=dict(receipt.actor),
        occurred_at=at.isoformat(),
    )
    event = DomainEvent.objects.create(
        workspace_id=receipt.workspace_id,
        event_type=f"curve.feature_editor.{receipt.action.lower()}",
        aggregate_type="FEATURE_EDITOR_GRANT",
        aggregate_id=grant["id"],
        aggregate_version=grant["version"],
        sequence=grant["version"],
        actor=dict(receipt.actor),
        effective_principal=dict(receipt.actor),
        correlation_id=receipt.correlation_id,
        idempotency_key_digest=key_digest,
        classification=DataClassification.INTERNAL,
        payload_schema="https://curve.example.invalid/contracts/candidates/feature-editor-event-v1.schema.json",
        payload=payload,
        occurred_at=at,
    )
    OutboxEvent.objects.create(
        workspace_id=receipt.workspace_id,
        event_id=event.id,
        destination="CURVE_FEATURE_EDITOR_LOCAL_V1",
    )


def _replay(receipt, record):
    assert_receipt(receipt)
    ref = record.response_resource_ref
    expected_status = 201 if receipt.action == "GRANT_FEATURE_EDITOR" else 200
    expected_version = 1 if receipt.action == "GRANT_FEATURE_EDITOR" else 2
    if (
        record.state != IdempotencyState.COMPLETED
        or not isinstance(ref, dict)
        or set(ref) != {"resource_type", "resource_id", "resource_version"}
        or ref["resource_type"] != "FEATURE_EDITOR_GRANT"
        or type(ref["resource_version"]) is not int
        or ref["resource_version"] != expected_version
        or record.response_status != expected_status
        or record.response_digest != operation_response_digest(response_status=expected_status, resource_ref=ref)
    ):
        raise ReplayResourceUnavailable
    try:
        grant_id = uuid.UUID(ref["resource_id"])
    except (ValueError, TypeError, AttributeError) as error:
        raise ReplayResourceUnavailable from error
    grant = scoped_grant(
        workspace_id=receipt.workspace_id,
        product_id=receipt.product_id,
        grant_id=grant_id,
        lock=True,
    )
    if grant is None:
        raise ReplayResourceUnavailable
    if receipt.action == "GRANT_FEATURE_EDITOR":
        # A retained original result must never revive a revoked grant or a grant
        # from an earlier membership lifetime. A new grant needs a new command.
        if (
            grant["revoked_at"] is not None
            or grant["version"] != 1
            or grant["member_id"] != receipt.target_member_id
            or grant["membership_id"] != receipt.target_membership_id
            or grant["membership_generation"] != receipt.target_membership_generation
        ):
            raise ReplayResourceUnavailable
    elif grant["id"] != receipt.grant_id or grant["version"] != 2 or grant["revoked_at"] is None:
        raise ReplayResourceUnavailable
    append_audit(
        receipt,
        target_ref=ref,
        outcome=AuditOutcome.NO_EFFECT,
        key_digest=record.key_digest,
        replay=True,
    )
    return FeatureEditorCommandResult(dict(ref), record.response_status, record.response_digest, True)


def execute_feature_editor_command(
    *,
    request,
    workspace_slug,
    product_id,
    action,
    payload,
    raw_idempotency_key,
    grant_id=None,
    expected_version=None,
):
    command = normalize_editor_command(action, payload, expected_version)

    def callback(receipt, product, existing):
        assert_receipt(receipt)
        canonical = canonical_json_bytes(
            {
                "action": command.action,
                "workspace_id": str(receipt.workspace_id),
                "product_id": str(product.id),
                "grant_id": str(receipt.grant_id) if receipt.grant_id else None,
                "expected_version": command.expected_version,
                "payload": dict(command.payload),
            }
        )
        identity = _command_identity(
            receipt,
            command_scope=f"CURVE.FEATURE_EDITOR.{action}:{product.id}:{receipt.grant_id or product.id}",
            raw_idempotency_key=raw_idempotency_key,
            canonical_request=canonical,
        )
        record, _, replay = _load_or_create_idempotency(workspace_id=receipt.workspace_id, identity=identity)
        if replay:
            return _replay(receipt, record)
        at = timezone.now()
        before = None
        if action == "GRANT_FEATURE_EDITOR":
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT EXISTS(SELECT 1 FROM curve_feature_editor_grant WHERE workspace_id=%s AND product_id=%s "
                    "AND member_id=%s AND membership_id=%s AND membership_generation=%s AND revoked_at IS NULL)",
                    [
                        receipt.workspace_id,
                        product.id,
                        receipt.target_member_id,
                        receipt.target_membership_id,
                        receipt.target_membership_generation,
                    ],
                )
                if cursor.fetchone()[0]:
                    raise FeatureEditorCommandError("FEATURE_EDITOR_ALREADY_GRANTED")
                result_id = uuid.uuid4()
                cursor.execute(
                    "INSERT INTO curve_feature_editor_grant "
                    "(id,version,workspace_id,product_id,member_id,membership_id,"
                    "membership_generation,granted_by,granted_at) "
                    "VALUES (%s,1,%s,%s,%s,%s,%s,%s,%s)",
                    [
                        result_id,
                        receipt.workspace_id,
                        product.id,
                        receipt.target_member_id,
                        receipt.target_membership_id,
                        receipt.target_membership_generation,
                        receipt.actor["actor_id"],
                        at,
                    ],
                )
        else:
            if existing is None or existing["version"] != command.expected_version:
                raise OptimisticConcurrencyError
            if existing["revoked_at"] is not None:
                raise FeatureEditorCommandError("FEATURE_EDITOR_ALREADY_REVOKED")
            before = _snapshot(existing)
            result_id = existing["id"]
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE curve_feature_editor_grant SET version=2, revoked_by=%s, revoked_at=%s "
                    "WHERE workspace_id=%s AND product_id=%s AND id=%s AND version=%s AND revoked_at IS NULL",
                    [
                        receipt.actor["actor_id"],
                        at,
                        receipt.workspace_id,
                        product.id,
                        result_id,
                        command.expected_version,
                    ],
                )
                if cursor.rowcount != 1:
                    raise OptimisticConcurrencyError
        result = scoped_grant(
            workspace_id=receipt.workspace_id,
            product_id=product.id,
            grant_id=result_id,
            lock=True,
        )
        if result is None:
            raise RuntimeError("FEATURE_EDITOR_RESULT_UNAVAILABLE")
        _event(receipt, result, before, identity["key_digest"], at)
        ref = _ref(result)
        status = 201 if action == "GRANT_FEATURE_EDITOR" else 200
        digest = operation_response_digest(response_status=status, resource_ref=ref)
        append_audit(
            receipt,
            target_ref=ref,
            outcome=AuditOutcome.SUCCEEDED,
            key_digest=record.key_digest,
            after_digest=digest,
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status, record.response_digest, record.response_resource_ref = (
            status,
            digest,
            ref,
        )
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
        return FeatureEditorCommandResult(ref, status, digest, False)

    return execute_editor_mutation(
        request=request,
        workspace_slug=workspace_slug,
        product_id=product_id,
        action=action,
        target_member_id=command.payload["member_id"] if action == "GRANT_FEATURE_EDITOR" else None,
        grant_id=grant_id,
        callback=callback,
        no_effect_exceptions=(
            FeatureEditorInputError,
            FeatureEditorCommandError,
            ProductValidationError,
            IdempotencyConflict,
            CommandAlreadyInProgress,
            OptimisticConcurrencyError,
            ReplayResourceUnavailable,
            IntegrityError,
        ),
    )
