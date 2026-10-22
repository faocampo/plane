# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Native local Product commands; protected I/O outside atomic command effects."""

from dataclasses import dataclass
from datetime import timedelta
from io import BytesIO
import re
import uuid
from django.db import transaction
from django.utils import timezone
from .local_document_capture import read_local_document_snapshot
from .local_document_store import LocalDocumentStore, StoredDocument
from .local_prd_review import create_decision, validate_feedback
from .local_prd_review_authority import create_document_submission
from .local_prd_review_authority import require_local_review_authority
from .local_prd_review_models import LocalPrdSubmission, LocalPrdDecision
from .local_prd_review_policy import record_review_authorization
from .models import IdempotencyRecord, IdempotencyState, DomainEvent, OutboxEvent
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


@dataclass(frozen=True)
class LocalReviewResult:
    data: dict
    initiative_version: int
    replayed: bool


def _require(condition, code="LOCAL_REVIEW_UNAVAILABLE", status=404):
    if not condition:
        raise PrdCommandError(code, status)


def _reference(record):
    return dict(
        resource_type="LOCAL_PRD_SUBMISSION" if isinstance(record, LocalPrdSubmission) else "LOCAL_PRD_DECISION",
        resource_id=str(record.id),
        resource_version=record.initiative_version,
    )


def _audit(authority, policy, record, identity, action, replay):
    actor = dict(actor_type="HUMAN", actor_id=str(authority.document.context.actor_id))
    _append_audit_event(
        workspace_id=record.workspace_id,
        action=f"CURVE.LOCAL_PRD.{action}",
        target_ref=_reference(record),
        outcome="NO_EFFECT" if replay else "SUCCEEDED",
        actor=actor,
        effective_principal=actor,
        correlation_id=policy.correlation_id,
        after_digest=record.digest,
        key_digest=identity["key_digest"],
        policy_decision_ref=dict(resource_type="POLICY_DECISION", resource_id=str(policy.id), resource_version=1),
    )


def _retained(authority, policy, idem, identity, action):
    if idem.request_digest != identity["request_digest"]:
        raise IdempotencyConflict
    _require(idem.state == "COMPLETED" and idem.response_status == 201)
    ref = idem.response_resource_ref
    _require(type(ref) is dict)
    model = LocalPrdSubmission if action == "SUBMIT" else LocalPrdDecision
    record = model.objects.filter(
        workspace_id=authority.document.context.workspace.id,
        initiative_id=authority.document.context.initiative.id,
        id=ref.get("resource_id"),
    ).first()
    _require(record is not None and _reference(record) == ref)
    record.validate_metadata()
    _require(idem.response_digest == operation_response_digest(response_status=201, resource_ref=ref))
    _audit(authority, policy, record, identity, action, True)
    return LocalReviewResult(record.as_record(), authority.document.context.initiative.version, True)


def execute_local_review(
    *,
    request,
    workspace_slug,
    initiative_id,
    action,
    expected_version,
    source_id,
    source_digest,
    raw_idempotency_key,
    store,
    submission_id=None,
    submission_digest=None,
    feedback=None,
):
    _require(not transaction.get_connection().in_atomic_block, "LOCAL_REVIEW_TRANSACTION_REQUIRED", 503)
    _require(type(store) is LocalDocumentStore, "LOCAL_REVIEW_STORAGE_UNAVAILABLE", 503)
    _require(action in {"SUBMIT", "APPROVE", "REQUEST_CHANGES"}, "LOCAL_REVIEW_COMMAND_INVALID", 422)
    _require(
        type(expected_version) is int and 0 < expected_version < 9007199254740991, "LOCAL_REVIEW_VERSION_REQUIRED", 428
    )
    for value in (source_id,) if action == "SUBMIT" else (source_id, submission_id):
        try:
            _require(type(value) is str and str(uuid.UUID(value)) == value, "LOCAL_REVIEW_COMMAND_INVALID", 422)
        except (ValueError, TypeError, AttributeError):
            raise PrdCommandError("LOCAL_REVIEW_COMMAND_INVALID", 422) from None
    for value in (source_digest,) if action == "SUBMIT" else (source_digest, submission_digest):
        _require(
            type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value), "LOCAL_REVIEW_COMMAND_INVALID", 422
        )
    _require(
        action != "SUBMIT" or (submission_id is None and submission_digest is None), "LOCAL_REVIEW_COMMAND_INVALID", 422
    )
    _require(action == "REQUEST_CHANGES" or feedback is None, "LOCAL_REVIEW_COMMAND_INVALID", 422)
    feedback_bytes = validate_feedback(feedback) if action == "REQUEST_CHANGES" else None
    _validate_idempotency_key(raw_idempotency_key)
    subject = dict(
        expected_version=expected_version,
        source_id=source_id,
        source_digest=source_digest,
        submission_id=submission_id,
        submission_digest=submission_digest,
    )
    request_digest = sha256_digest(
        canonical_json_bytes(
            dict(
                schema_version="curve.local-prd-command/v1-candidate",
                initiative_id=str(initiative_id),
                action=action,
                **subject,
                feedback_digest=sha256_digest(feedback_bytes) if feedback_bytes else None,
            )
        )
    )
    identity = dict(
        principal_scope=f"HUMAN:{request.user.id}",
        command_scope=f"CURVE.LOCAL_PRD.{action}:{initiative_id}",
        key_digest=idempotency_key_digest(raw_idempotency_key),
        request_digest=request_digest,
        expires_at=timezone.now() + timedelta(days=1),
    )
    common = dict(
        request=request,
        workspace_slug=workspace_slug,
        initiative_id=initiative_id,
        request_digest=request_digest,
        action=action,
    )
    with transaction.atomic():
        readable = require_local_review_authority(
            request=request, workspace_slug=workspace_slug, initiative_id=initiative_id, action="READ"
        )
        existing = (
            IdempotencyRecord.objects.select_for_update()
            .filter(
                workspace_id=readable.document.context.workspace.id,
                **{key: identity[key] for key in ("principal_scope", "command_scope", "key_digest")},
            )
            .first()
        )
        if existing is not None:
            authorized, policy = record_review_authorization(**common, replay=True)
            return _retained(authorized, policy, existing, identity, action)
        before, _ = record_review_authorization(**common, **subject)
        source = before.document.current_source.as_record()
    # Verify exact original and review snapshot after current native access, with
    # no database locks held. Preserve prepared feedback after uncertain outcomes.
    ref = source["snapshot"]
    read_local_document_snapshot(
        store=store,
        workspace_id=source["workspace_id"],
        reference=StoredDocument(
            source["workspace_id"], ref["object_id"], ref["digest"], ref["size_bytes"], ref["media_type"]
        ),
    )
    feedback_ref = None
    if feedback_bytes is not None:
        saved = store.put(workspace_id=source["workspace_id"], filename="feedback.txt", stream=BytesIO(feedback_bytes))
        feedback_ref = dict(
            object_id=saved.object_id,
            digest=saved.content_digest,
            size_bytes=saved.byte_length,
            media_type=saved.media_type,
        )
    with transaction.atomic():
        readable = require_local_review_authority(
            request=request, workspace_slug=workspace_slug, initiative_id=initiative_id, action="READ"
        )
        idem, _, replay = _load_or_create_idempotency(
            workspace_id=readable.document.context.workspace.id, identity=identity
        )
        if replay:
            authorized, policy = record_review_authorization(**common, replay=True)
            return _retained(authorized, policy, idem, identity, action)
        current, policy = record_review_authorization(**common, **subject)
        _require(current.fence == before.fence, "LOCAL_REVIEW_SUBJECT_CHANGED", 409)
        init = current.document.context.initiative
        instant = timezone.now().isoformat(timespec="microseconds").replace("+00:00", "Z")
        actor = dict(actor_type="HUMAN", actor_id=str(current.document.context.actor_id))
        if action == "SUBMIT":
            record = LocalPrdSubmission.from_record(
                create_document_submission(
                    current.document,
                    initiative_version=init.version,
                    submitted_by=actor["actor_id"],
                    submitted_at=instant,
                )
            )
            record.save()
            init.current_local_prd_submission_id = record.id
            init.controlling_local_prd_decision_id = None
            init.state = "PRD_REVIEW"
        else:
            record = LocalPrdDecision.from_record(
                create_decision(
                    submission=current.submission.as_record(),
                    initiative_version=init.version,
                    state="APPROVED" if action == "APPROVE" else "CHANGES_REQUESTED",
                    decided_by=actor["actor_id"],
                    decided_at=instant,
                    feedback=feedback_ref,
                ),
                current.submission,
            )
            record.save()
            init.controlling_local_prd_decision_id = record.id
            init.state = "PLANNING" if action == "APPROVE" else "ALIGNING"
        init.version += 1
        init.updated_by = actor
        init.save(
            update_fields=[
                "current_local_prd_submission_id",
                "controlling_local_prd_decision_id",
                "state",
                "version",
                "updated_by",
                "updated_at",
            ]
        )
        event = DomainEvent.objects.create(
            workspace_id=init.workspace_id,
            event_type=f"CURVE.LOCAL_PRD.{action}_V1",
            aggregate_type="INITIATIVE",
            aggregate_id=init.id,
            aggregate_version=init.version,
            sequence=init.version,
            actor=actor,
            effective_principal=actor,
            correlation_id=policy.correlation_id,
            idempotency_key_digest=identity["key_digest"],
            classification="INTERNAL",
            payload_schema="https://curve.example.invalid/contracts/local-prd-review-event-v1",
            payload=dict(
                schema_version="curve.local-prd-review-event/v1-candidate",
                action=action,
                record_ref=_reference(record),
                record_digest=record.digest,
                initiative_version=init.version,
                policy_decision_id=str(policy.id),
            ),
            occurred_at=timezone.now(),
        )
        OutboxEvent.objects.create(
            workspace_id=init.workspace_id, event_id=event.id, destination="CURVE_LOCAL_PRD_REVIEW_V1"
        )
        _audit(current, policy, record, identity, action, False)
        idem.state = IdempotencyState.COMPLETED
        idem.response_status = 201
        idem.response_resource_ref = _reference(record)
        idem.response_digest = operation_response_digest(response_status=201, resource_ref=_reference(record))
        idem.completed_at = timezone.now()
        idem.save(
            update_fields=["state", "response_status", "response_resource_ref", "response_digest", "completed_at"]
        )
        return LocalReviewResult(record.as_record(), init.version, False)
