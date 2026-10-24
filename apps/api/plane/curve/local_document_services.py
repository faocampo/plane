# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Two-phase upload with current native authorization and atomic metadata effects."""

from dataclasses import dataclass
from datetime import timedelta
from io import BytesIO

from django.db import transaction
from django.utils import timezone

from .local_document_authority import require_local_document_authority
from .local_document_models import LocalPrdSource
from .local_document_policy import record_upload_authorization
from .local_document_record import create_local_document_record
from .local_document_store import LocalDocumentStore, read_local_upload
from .models import DomainEvent, IdempotencyRecord, IdempotencyState, OutboxEvent
from .prd_commands import PrdCommandError
from .product_services import _load_or_create_idempotency, _validate_idempotency_key
from .services import (
    _append_audit_event,
    canonical_json_bytes,
    idempotency_key_digest,
    operation_response_digest,
    sha256_digest,
    IdempotencyConflict,
)


@dataclass(frozen=True)
class LocalUploadResult:
    data: dict
    initiative_version: int
    replayed: bool


def _require(condition, code="LOCAL_PRD_UNAVAILABLE", status=404):
    if not condition:
        raise PrdCommandError(code, status)


def _ref(source):
    return dict(resource_type="LOCAL_PRD_SOURCE", resource_id=str(source.id), resource_version=source.version)


def _audit(authority, decision, source, key_digest, *, replay):
    actor = dict(actor_type="HUMAN", actor_id=str(authority.context.actor_id))
    _append_audit_event(
        workspace_id=source.workspace_id,
        action="CURVE.LOCAL_PRD.UPLOAD",
        target_ref=_ref(source),
        outcome="NO_EFFECT" if replay else "SUCCEEDED",
        actor=actor,
        effective_principal=actor,
        correlation_id=decision.correlation_id,
        after_digest=source.digest,
        key_digest=key_digest,
        policy_decision_ref=dict(resource_type="POLICY_DECISION", resource_id=str(decision.id), resource_version=1),
    )


def _replay(authority, decision, idem, request_digest):
    if idem.request_digest != request_digest:
        raise IdempotencyConflict
    ref = idem.response_resource_ref
    _require(
        idem.state == "COMPLETED"
        and idem.response_status == 201
        and type(ref) is dict
        and ref.get("resource_type") == "LOCAL_PRD_SOURCE"
    )
    source = LocalPrdSource.objects.filter(
        workspace_id=authority.context.workspace.id,
        initiative_id=authority.context.initiative.id,
        id=ref.get("resource_id"),
    ).first()
    _require(source is not None and ref == _ref(source))
    source.validate_metadata()
    _require(idem.response_digest == operation_response_digest(response_status=201, resource_ref=ref))
    _audit(authority, decision, source, idem.key_digest, replay=True)
    return LocalUploadResult(source.as_record(), authority.context.initiative.version, True)


def upload_local_document(
    *,
    request,
    workspace_slug,
    initiative_id,
    expected_version,
    expected_source_version,
    raw_idempotency_key,
    filename,
    stream,
    store,
):
    _require(not transaction.get_connection().in_atomic_block, "LOCAL_PRD_TRANSACTION_REQUIRED", 503)
    _require(type(store) is LocalDocumentStore, "LOCAL_PRD_STORAGE_UNAVAILABLE", 503)
    _require(
        type(expected_source_version) is int and 0 <= expected_source_version < 9007199254740991,
        "LOCAL_PRD_VERSION_REQUIRED",
        428,
    )
    _validate_idempotency_key(raw_idempotency_key)
    with transaction.atomic():
        require_local_document_authority(
            request=request,
            workspace_slug=workspace_slug,
            initiative_id=initiative_id,
            action="UPLOAD",
            expected_version=expected_version,
        )
    # Read at most the approved bound after authorization, before any file write.
    body, media_type = read_local_upload(filename=filename, stream=stream)
    request_digest = sha256_digest(
        canonical_json_bytes(
            dict(
                schema_version="curve.local-prd-upload/v1-candidate",
                initiative_id=str(initiative_id),
                expected_version=expected_version,
                expected_source_version=expected_source_version,
                media_type=media_type,
                content_digest=sha256_digest(body),
            )
        )
    )
    identity = dict(
        principal_scope=f"HUMAN:{request.user.id}",
        command_scope=f"CURVE.LOCAL_PRD.UPLOAD:{initiative_id}",
        key_digest=idempotency_key_digest(raw_idempotency_key),
        request_digest=request_digest,
        expires_at=timezone.now() + timedelta(days=1),
    )
    with transaction.atomic():
        before, decision = record_upload_authorization(
            request=request,
            workspace_slug=workspace_slug,
            initiative_id=initiative_id,
            expected_version=expected_version,
            request_digest=request_digest,
        )
        existing = (
            IdempotencyRecord.objects.select_for_update()
            .filter(
                workspace_id=before.context.workspace.id,
                **{key: identity[key] for key in ("principal_scope", "command_scope", "key_digest")},
            )
            .first()
        )
        if existing is not None:
            return _replay(before, decision, existing, request_digest)
        _require(
            (before.current_source.version if before.current_source else 0) == expected_source_version,
            "LOCAL_PRD_SOURCE_CHANGED",
            409,
        )
        previous = before.current_source.as_record() if before.current_source else None
    # Protected bytes are prepared outside locks. On an uncertain database outcome
    # retain prepared objects; a recovery/retention job must prove non-reference
    # before erasure. A transport error must never delete committed document bytes.
    workspace_id = str(before.context.workspace.id)
    original = store.put(workspace_id=workspace_id, filename=filename, stream=BytesIO(body))
    snapshot = store.put_snapshot(workspace_id=workspace_id, source=original)
    value = create_local_document_record(
        store=store,
        workspace_id=workspace_id,
        initiative_id=str(initiative_id),
        actor_id=str(request.user.id),
        uploaded_at=timezone.now().isoformat(timespec="microseconds").replace("+00:00", "Z"),
        snapshot=snapshot,
        predecessor=previous,
    )
    with transaction.atomic():
        current, decision = record_upload_authorization(
            request=request,
            workspace_slug=workspace_slug,
            initiative_id=initiative_id,
            expected_version=expected_version,
            request_digest=request_digest,
        )
        idem, _, replay = _load_or_create_idempotency(workspace_id=current.context.workspace.id, identity=identity)
        if replay:
            return _replay(current, decision, idem, request_digest)
        _require(current.fence == before.fence, "LOCAL_PRD_SOURCE_CHANGED", 409)
        source = LocalPrdSource.from_record(value)
        source.save()
        actor = dict(actor_type="HUMAN", actor_id=str(current.context.actor_id))
        event = DomainEvent.objects.create(
            workspace_id=source.workspace_id,
            event_type="CURVE.LOCAL_PRD.UPLOADED_V1",
            aggregate_type="LOCAL_PRD_SOURCE",
            aggregate_id=source.id,
            aggregate_version=source.version,
            sequence=1,
            actor=actor,
            effective_principal=actor,
            correlation_id=decision.correlation_id,
            idempotency_key_digest=identity["key_digest"],
            classification="INTERNAL",
            payload_schema="https://curve.example.invalid/contracts/local-prd-uploaded-v1",
            payload=dict(
                schema_version="curve.local-prd-uploaded/v1-candidate",
                source_id=str(source.id),
                source_digest=source.digest,
                initiative_id=str(initiative_id),
                policy_decision_id=str(decision.id),
            ),
            occurred_at=timezone.now(),
        )
        OutboxEvent.objects.create(
            workspace_id=source.workspace_id, event_id=event.id, destination="CURVE_LOCAL_PRD_SOURCE_V1"
        )
        _audit(current, decision, source, identity["key_digest"], replay=False)
        idem.state = IdempotencyState.COMPLETED
        idem.response_status = 201
        idem.response_resource_ref = _ref(source)
        idem.response_digest = operation_response_digest(response_status=201, resource_ref=_ref(source))
        idem.completed_at = timezone.now()
        idem.save(
            update_fields=["state", "response_status", "response_resource_ref", "response_digest", "completed_at"]
        )
        return LocalUploadResult(source.as_record(), current.context.initiative.version, False)
