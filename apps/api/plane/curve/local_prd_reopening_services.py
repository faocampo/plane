# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Atomic owner command: retained approval, reopened state, event, audit and retry."""

from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from .local_prd_reopening import create_reopening
from .local_prd_reopening_models import LocalPrdReopening
from .local_prd_reopening_authority import require_local_reopening_authority, record_reopening_authorization
from .local_prd_review_services import LocalReviewResult
from .models import IdempotencyState, DomainEvent, OutboxEvent
from .prd_commands import PrdCommandError
from .product_services import _load_or_create_idempotency, _validate_idempotency_key
from .services import (
    _append_audit_event,
    canonical_json_bytes,
    sha256_digest,
    idempotency_key_digest,
    operation_response_digest,
    IdempotencyConflict,
)


def _reference(record):
    return dict(
        resource_type="LOCAL_PRD_REOPENING", resource_id=str(record.id), resource_version=record.initiative_version
    )


def _audit(current, policy, record, identity, replay):
    actor = dict(actor_type="HUMAN", actor_id=str(current.document.context.actor_id))
    _append_audit_event(
        workspace_id=record.workspace_id,
        action="CURVE.LOCAL_PRD.REOPEN",
        target_ref=_reference(record),
        outcome="NO_EFFECT" if replay else "SUCCEEDED",
        actor=actor,
        effective_principal=actor,
        correlation_id=policy.correlation_id,
        after_digest=record.digest,
        key_digest=identity["key_digest"],
        policy_decision_ref=dict(resource_type="POLICY_DECISION", resource_id=str(policy.id), resource_version=1),
    )


def execute_local_reopening(
    *,
    request,
    workspace_slug,
    initiative_id,
    expected_version,
    source_id,
    source_digest,
    submission_id,
    submission_digest,
    decision_id,
    decision_digest,
    raw_idempotency_key,
):
    if transaction.get_connection().in_atomic_block:
        raise PrdCommandError("LOCAL_REOPENING_TRANSACTION_REQUIRED", 503)
    if type(expected_version) is not int or not 0 < expected_version < 9007199254740991:
        raise PrdCommandError("LOCAL_REOPENING_VERSION_REQUIRED", 428)
    _validate_idempotency_key(raw_idempotency_key)
    subject = dict(
        expected_version=expected_version,
        source_id=source_id,
        source_digest=source_digest,
        submission_id=submission_id,
        submission_digest=submission_digest,
        decision_id=decision_id,
        decision_digest=decision_digest,
    )
    request_digest = sha256_digest(
        canonical_json_bytes(
            dict(
                schema_version="curve.local-prd-reopening-command/v1-candidate",
                action="REOPEN",
                initiative_id=str(initiative_id),
                **subject,
            )
        )
    )
    identity = dict(
        principal_scope=f"HUMAN:{request.user.id}",
        command_scope=f"CURVE.LOCAL_PRD.REOPEN:{initiative_id}",
        key_digest=idempotency_key_digest(raw_idempotency_key),
        request_digest=request_digest,
        expires_at=timezone.now() + timedelta(days=1),
    )
    common = dict(
        request=request, workspace_slug=workspace_slug, initiative_id=initiative_id, request_digest=request_digest
    )
    with transaction.atomic():
        readable = require_local_reopening_authority(
            request=request, workspace_slug=workspace_slug, initiative_id=initiative_id, replay=True
        )
        idem, _, replay = _load_or_create_idempotency(
            workspace_id=readable.document.context.workspace.id, identity=identity
        )
        if replay:
            if idem.request_digest != identity["request_digest"]:
                raise IdempotencyConflict
            current, policy = record_reopening_authorization(**common, replay=True)
            ref = idem.response_resource_ref
            if idem.state != "COMPLETED" or idem.response_status != 201 or type(ref) is not dict:
                raise PrdCommandError("LOCAL_REOPENING_UNAVAILABLE", 404)
            record = LocalPrdReopening.objects.filter(
                workspace_id=current.document.context.workspace.id,
                initiative_id=initiative_id,
                id=ref.get("resource_id"),
            ).first()
            if (
                record is None
                or _reference(record) != ref
                or idem.response_digest != operation_response_digest(response_status=201, resource_ref=ref)
            ):
                raise PrdCommandError("LOCAL_REOPENING_UNAVAILABLE", 404)
            record.validate_metadata()
            _audit(current, policy, record, identity, True)
            return LocalReviewResult(record.as_record(), current.document.context.initiative.version, True)
        current, policy = record_reopening_authorization(**common, **subject)
        init = current.document.context.initiative
        actor = dict(actor_type="HUMAN", actor_id=str(current.document.context.actor_id))
        record = LocalPrdReopening.from_record(
            create_reopening(
                submission=current.submission.as_record(),
                decision=current.decision.as_record(),
                initiative_version=init.version,
                reopened_by=actor["actor_id"],
                reopened_at=timezone.now().isoformat(timespec="microseconds").replace("+00:00", "Z"),
            ),
            current.submission,
            current.decision,
        )
        record.save()
        init.state = "ALIGNING"
        init.version += 1
        init.updated_by = actor
        init.save(update_fields=["state", "version", "updated_by", "updated_at"])
        event = DomainEvent.objects.create(
            workspace_id=init.workspace_id,
            event_type="CURVE.LOCAL_PRD.REOPEN_V1",
            aggregate_type="INITIATIVE",
            aggregate_id=init.id,
            aggregate_version=init.version,
            sequence=init.version,
            actor=actor,
            effective_principal=actor,
            correlation_id=policy.correlation_id,
            idempotency_key_digest=identity["key_digest"],
            classification="INTERNAL",
            payload_schema="https://curve.example.invalid/contracts/local-prd-reopening-event-v1",
            payload=dict(
                schema_version="curve.local-prd-reopening-event/v1-candidate",
                action="REOPEN",
                record_ref=_reference(record),
                record_digest=record.digest,
                initiative_version=init.version,
                policy_decision_id=str(policy.id),
            ),
            occurred_at=timezone.now(),
        )
        OutboxEvent.objects.create(
            workspace_id=init.workspace_id, event_id=event.id, destination="CURVE_LOCAL_PRD_REOPENING_V1"
        )
        _audit(current, policy, record, identity, False)
        idem.state = IdempotencyState.COMPLETED
        idem.response_status = 201
        idem.response_resource_ref = _reference(record)
        idem.response_digest = operation_response_digest(response_status=201, resource_ref=_reference(record))
        idem.completed_at = timezone.now()
        idem.save(
            update_fields=["state", "response_status", "response_resource_ref", "response_digest", "completed_at"]
        )
        return LocalReviewResult(record.as_record(), init.version, False)
