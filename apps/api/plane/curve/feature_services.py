# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Feature create/update command candidate, pending additive native qualification."""

from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID

from django.db import IntegrityError
from django.utils import timezone

from plane.curve.feature_events import build_feature_event
from plane.curve.feature_input import FeatureInputError, normalize_feature_command
from plane.curve.feature_material import FeatureMaterialError
from plane.curve.feature_policy import append_audit, assert_receipt, execute_feature_mutation
from plane.curve.models import AuditOutcome, DomainEvent, Feature, IdempotencyRecord, IdempotencyState, OutboxEvent
from plane.curve.policy_services import CurvePolicyResourceNotFound
from plane.curve.product_services import _command_identity, _load_or_create_idempotency, ProductValidationError
from plane.curve.services import (
    CommandAlreadyInProgress,
    IdempotencyConflict,
    OptimisticConcurrencyError,
    ReplayResourceUnavailable,
    canonical_json_bytes,
    operation_response_digest,
)


class FeatureCommandError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedFeatureCommand:
    identity: dict
    feature: object | None
    replay_record: object | None


@dataclass(frozen=True, slots=True)
class FeatureCommandResult:
    resource_ref: dict
    response_status: int
    response_digest: str
    replayed: bool


def _ref(feature):
    return {"resource_type": "FEATURE", "resource_id": str(feature.id), "resource_version": feature.version}


def _snapshot(feature):
    return {**_ref(feature), "name": feature.name, "description": deepcopy(feature.description)}


def _load_feature(facts, feature_id):
    row = (
        Feature.objects.select_for_update()
        .filter(
            workspace_id=facts.workspace_id,
            product_id=facts.product_id,
            id=feature_id,
            tombstoned_at__isnull=True,
        )
        .first()
    )
    if row is None:
        raise CurvePolicyResourceNotFound
    if row.schema_version != "1.0":
        raise FeatureCommandError("FEATURE_FORMAT_UNAVAILABLE")
    normalize_feature_command("UPDATE_FEATURE", {"name": row.name, "description": row.description}, row.version)
    return row


def _validate_retained_result(record, command, feature_id):
    ref = record.response_resource_ref
    status = 201 if command.action == "CREATE_FEATURE" else 200
    version = 1 if command.action == "CREATE_FEATURE" else command.expected_version + 1
    if (
        record.state != IdempotencyState.COMPLETED
        or type(ref) is not dict
        or set(ref) != {"resource_type", "resource_id", "resource_version"}
        or ref["resource_type"] != "FEATURE"
        or type(ref["resource_version"]) is not int
        or ref["resource_version"] != version
        or not 1 <= version <= 9223372036854775807
        or record.response_status != status
        or record.response_digest != operation_response_digest(response_status=status, resource_ref=ref)
    ):
        raise ReplayResourceUnavailable
    try:
        identity = UUID(ref["resource_id"])
    except (ValueError, TypeError, AttributeError) as error:
        raise ReplayResourceUnavailable from error
    if str(identity) != ref["resource_id"] or (feature_id is not None and identity != feature_id):
        raise ReplayResourceUnavailable
    return identity


def _event(receipt, feature, before, key_digest):
    assert_receipt(receipt)
    at = timezone.now()
    payload = build_feature_event(
        action=receipt.action,
        workspace_id=receipt.workspace_id,
        product_id=receipt.product_id,
        before=before,
        after=_snapshot(feature),
        actor=dict(receipt.actor),
        occurred_at=at.isoformat(),
    )
    event = DomainEvent.objects.create(
        workspace_id=receipt.workspace_id,
        event_type=f"curve.feature.{receipt.action.lower()}",
        aggregate_type="FEATURE",
        aggregate_id=feature.id,
        aggregate_version=feature.version,
        sequence=feature.version,
        actor=dict(receipt.actor),
        effective_principal=dict(receipt.actor),
        correlation_id=receipt.correlation_id,
        idempotency_key_digest=key_digest,
        classification=receipt.classification,
        payload_schema="https://curve.example.invalid/contracts/candidates/feature-command-event-v1.schema.json",
        payload=payload,
        occurred_at=at,
    )
    OutboxEvent.objects.create(
        workspace_id=receipt.workspace_id, event_id=event.id, destination="CURVE_FEATURE_LOCAL_V1"
    )


def execute_feature_command(
    *, request, workspace_slug, product_id, action, payload, raw_idempotency_key, feature_id=None, expected_version=None
):
    command = normalize_feature_command(action, payload, expected_version)
    if (action == "UPDATE_FEATURE") != (feature_id is not None):
        raise FeatureCommandError("FEATURE_TARGET_INVALID")
    try:
        product_id = UUID(str(product_id))
        feature_id = UUID(str(feature_id)) if feature_id is not None else None
    except (ValueError, TypeError, AttributeError) as error:
        raise CurvePolicyResourceNotFound from error

    def prepare(facts):
        canonical = canonical_json_bytes(
            {
                "action": command.action,
                "workspace_id": str(facts.workspace_id),
                "product_id": str(product_id),
                "feature_id": str(feature_id) if feature_id is not None else None,
                "expected_version": command.expected_version,
                "payload": command.as_payload(),
            }
        )
        identity = _command_identity(
            SimpleNamespace(actor={"actor_type": "HUMAN", "actor_id": str(facts.actor_id)}),
            command_scope=f"CURVE.FEATURE.{command.action}:{product_id}:{feature_id or product_id}",
            raw_idempotency_key=raw_idempotency_key,
            canonical_request=canonical,
        )
        retained = (
            IdempotencyRecord.objects.select_for_update()
            .filter(
                workspace_id=facts.workspace_id,
                principal_scope=identity["principal_scope"],
                command_scope=identity["command_scope"],
                key_digest=identity["key_digest"],
            )
            .first()
        )
        target = _load_feature(facts, feature_id) if feature_id is not None else None
        if retained is not None:
            if retained.request_digest != identity["request_digest"]:
                raise IdempotencyConflict
            if retained.state not in IdempotencyRecord.TERMINAL_STATES:
                raise CommandAlreadyInProgress
            result_id = _validate_retained_result(retained, command, feature_id)
            target = target or _load_feature(facts, result_id)
            if target.version < retained.response_resource_ref["resource_version"]:
                raise ReplayResourceUnavailable
        return PreparedFeatureCommand(identity, target, retained)

    def callback(receipt, prepared):
        assert_receipt(receipt)
        record, _, replay = _load_or_create_idempotency(workspace_id=receipt.workspace_id, identity=prepared.identity)
        if replay:
            if prepared.replay_record is None or prepared.replay_record.id != record.id:
                raise ReplayResourceUnavailable
            _validate_retained_result(record, command, feature_id)
            ref = deepcopy(record.response_resource_ref)
            append_audit(
                receipt, target_ref=ref, outcome=AuditOutcome.NO_EFFECT, key_digest=record.key_digest, replay=True
            )
            return FeatureCommandResult(ref, record.response_status, record.response_digest, True)
        if prepared.replay_record is not None:
            raise ReplayResourceUnavailable
        feature = prepared.feature
        before = None
        values = command.as_payload()
        if action == "CREATE_FEATURE":
            feature = Feature.objects.create(
                workspace_id=receipt.workspace_id,
                product_id=receipt.product_id,
                created_by=dict(receipt.actor),
                updated_by=dict(receipt.actor),
                **values,
            )
        else:
            if feature is None or feature.version != command.expected_version:
                raise OptimisticConcurrencyError
            if feature.version >= 9223372036854775807:
                raise FeatureCommandError("FEATURE_VERSION_EXHAUSTED")
            before = _snapshot(feature)
            feature.name, feature.description = values["name"], values["description"]
            feature.version += 1
            feature.updated_by = dict(receipt.actor)
            feature.save(update_fields=["name", "description", "version", "updated_by", "updated_at"])
        _event(receipt, feature, before, record.key_digest)
        ref = _ref(feature)
        status = 201 if action == "CREATE_FEATURE" else 200
        response_digest = operation_response_digest(response_status=status, resource_ref=ref)
        append_audit(
            receipt,
            target_ref=ref,
            outcome=AuditOutcome.SUCCEEDED,
            key_digest=record.key_digest,
            after_digest=response_digest,
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status, record.response_digest, record.response_resource_ref = status, response_digest, ref
        record.completed_at = timezone.now()
        record.save(
            update_fields=["state", "response_status", "response_digest", "response_resource_ref", "completed_at"]
        )
        return FeatureCommandResult(ref, status, response_digest, False)

    return execute_feature_mutation(
        request=request,
        workspace_slug=workspace_slug,
        product_id=product_id,
        feature_id=feature_id,
        command=command,
        prepare=prepare,
        callback=callback,
        no_effect_exceptions=(
            FeatureInputError,
            FeatureMaterialError,
            FeatureCommandError,
            ProductValidationError,
            IdempotencyConflict,
            CommandAlreadyInProgress,
            OptimisticConcurrencyError,
            ReplayResourceUnavailable,
            IntegrityError,
        ),
    )
