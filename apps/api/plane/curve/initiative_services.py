# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import re
import uuid
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from plane.curve.initiative_policy import append_initiative_mutation_audit, execute_initiative_mutation
from plane.curve.initiative_serialization import serialize_initiative
from plane.curve.models import (
    AuditOutcome,
    DataClassification,
    DomainEvent,
    GateAssignment,
    GateType,
    IdempotencyState,
    Initiative,
    InitiativeBusinessIntent,
    InitiativeMode,
    InitiativeRiskTier,
    InitiativeState,
    OutboxEvent,
)
from plane.curve.product_guards import (
    ProductArchived,
    ProductGuardResourceNotFound,
    assert_product_accepts_new_initiative,
)
from plane.curve.product_services import (
    _command_identity,
    _load_or_create_idempotency,
    _validate_expected_version,
    _validate_keys,
)
from plane.curve.services import (
    CommandAlreadyInProgress,
    IdempotencyConflict,
    OptimisticConcurrencyError,
    ReplayResourceUnavailable,
    _lock_audit_sequence,
    canonical_json_bytes,
    operation_response_digest,
    sha256_digest,
)
from plane.db.models import WorkspaceMember


INITIATIVE_EVENT_SCHEMA = "https://curve.example.invalid/contracts/schemas/initiative-event-v1.schema.json"
INITIATIVE_OUTBOX_DESTINATION = "CURVE_INITIATIVE_LOCAL_V1"
MANUAL_FIRST_WORKFLOW_VERSION_ID = uuid.UUID("82000000-0000-4000-8000-000000000001")
KEYWORD_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,49}$")
DESCRIPTION_KEYS = frozenset({"schema_version", "format", "body"})
DESCRIPTION_MAX_LENGTH = 20_000
KEYWORD_UNIQUE_CONSTRAINT = "curve_init_workspace_keyword_uq"


class InitiativeCommandError(Exception):
    code = "INITIATIVE_COMMAND_ERROR"
    field = None


class InitiativeValidationError(InitiativeCommandError):
    code = "INITIATIVE_REQUEST_INVALID"

    def __init__(self, *, field=None):
        self.field = field


class InitiativeKeywordConflict(InitiativeCommandError):
    code = "INITIATIVE_KEYWORD_CONFLICT"


class RoadmapModeNotAvailable(InitiativeCommandError):
    code = "ROADMAP_MODE_NOT_AVAILABLE"


class InitiativeProductUnavailable(InitiativeCommandError):
    code = "INITIATIVE_PRODUCT_UNAVAILABLE"


class InitiativeProductInactive(InitiativeCommandError):
    code = "PRODUCT_INACTIVE"


class InitiativeGateAssignmentInvalid(InitiativeCommandError):
    code = "GATE_ASSIGNMENT_INVALID"


class InitiativeStateConflict(InitiativeCommandError):
    code = "INITIATIVE_STATE_CONFLICT"


class InitiativeNoChanges(InitiativeCommandError):
    code = "INITIATIVE_NO_CHANGES"


@dataclass(frozen=True, slots=True)
class InitiativeCommandResult:
    initiative: Initiative
    replayed: bool
    response_status: int
    response_digest: str
    response_resource_ref: dict


def initiative_resource_ref(initiative):
    return {
        "resource_type": "INITIATIVE",
        "resource_id": str(initiative.id),
        "resource_version": initiative.version,
    }


def _validate_keyword(value):
    if not isinstance(value, str) or KEYWORD_PATTERN.fullmatch(value) is None:
        raise InitiativeValidationError(field="keyword")
    return value


def _validate_title(value):
    if not isinstance(value, str) or not value or len(value) > 255:
        raise InitiativeValidationError(field="title")
    return value


def _validate_description(value):
    if not isinstance(value, dict) or set(value) != DESCRIPTION_KEYS:
        raise InitiativeValidationError(field="description")
    if value.get("schema_version") != "1.0" or value.get("format") != "MARKDOWN":
        raise InitiativeValidationError(field="description")
    body = value.get("body")
    if not isinstance(body, str) or not body or len(body) > DESCRIPTION_MAX_LENGTH:
        raise InitiativeValidationError(field="description")
    return value


def _validate_risk_tier(value):
    if value not in InitiativeRiskTier.values:
        raise InitiativeValidationError(field="risk_tier")
    return value


def _validate_business_intent(value, *, allow_unset=False):
    if allow_unset and value is None:
        return None
    if value not in InitiativeBusinessIntent.values:
        raise InitiativeValidationError(field="business_intent")
    return value


def _validate_uuid(value, *, field):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as error:
        raise InitiativeValidationError(field=field) from error


def _validate_reason_payload(payload):
    _validate_keys(payload, {"reason"}, required={"reason"})
    reason = payload["reason"]
    if not isinstance(reason, str) or not reason or len(reason) > 2000:
        raise InitiativeValidationError(field="reason")
    return reason


def _translate_keyword_integrity_error(error):
    diagnostic = getattr(getattr(error, "__cause__", None), "diag", None)
    if getattr(diagnostic, "constraint_name", None) == KEYWORD_UNIQUE_CONSTRAINT:
        raise InitiativeKeywordConflict from error
    raise error


def _normalize_assignments(*, workspace_id, assignments, risk_tier):
    if not isinstance(assignments, list) or len(assignments) != 3:
        raise InitiativeGateAssignmentInvalid
    normalized = []
    for assignment in assignments:
        if not isinstance(assignment, dict) or set(assignment) != {"gate_type", "approver_user_id"}:
            raise InitiativeGateAssignmentInvalid
        gate_type = assignment["gate_type"]
        if gate_type not in GateType.values:
            raise InitiativeGateAssignmentInvalid
        approver_id = _validate_uuid(assignment["approver_user_id"], field="approver_user_id")
        normalized.append((gate_type, approver_id))
    if {gate_type for gate_type, _ in normalized} != set(GateType.values):
        raise InitiativeGateAssignmentInvalid
    approver_ids = {approver_id for _, approver_id in normalized}
    active_count = WorkspaceMember.objects.filter(
        workspace_id=workspace_id,
        member_id__in=approver_ids,
        is_active=True,
    ).count()
    if active_count != len(approver_ids):
        raise InitiativeGateAssignmentInvalid
    if risk_tier in {InitiativeRiskTier.STANDARD, InitiativeRiskTier.HIGH} and len(approver_ids) != 3:
        raise InitiativeGateAssignmentInvalid
    return sorted(normalized, key=lambda value: value[0])


def _validate_current_assignments(initiative, *, risk_tier=None):
    assignments = list(initiative.gate_assignments.all())
    return _normalize_assignments(
        workspace_id=initiative.workspace_id,
        assignments=[
            {"gate_type": assignment.gate_type, "approver_user_id": str(assignment.approver_user_id)}
            for assignment in assignments
        ],
        risk_tier=risk_tier or initiative.risk_tier,
    )


def _resolve_product(*, workspace_id, product_id):
    try:
        return assert_product_accepts_new_initiative(workspace_id=workspace_id, product_id=product_id)
    except ProductGuardResourceNotFound as error:
        raise InitiativeProductUnavailable from error
    except ProductArchived as error:
        raise InitiativeProductInactive from error


def _resolve_replay(*, workspace_id, record):
    ref = record.response_resource_ref
    if not ref or ref.get("resource_type") != "INITIATIVE":
        raise ReplayResourceUnavailable
    initiative = Initiative.objects.find_by_id(
        workspace_id=workspace_id,
        record_id=ref.get("resource_id"),
        for_update=True,
    )
    if initiative is None:
        raise ReplayResourceUnavailable
    return InitiativeCommandResult(
        initiative=initiative,
        replayed=True,
        response_status=record.response_status,
        response_digest=record.response_digest,
        response_resource_ref=record.response_resource_ref,
    )


def _append_event(*, initiative, event_type, actor, correlation_id, key_digest, previous_state, details=None):
    occurred_at = timezone.now()
    payload = {
        "schema_version": "1.0",
        "workspace_id": str(initiative.workspace_id),
        "initiative_id": str(initiative.id),
        "initiative_version": initiative.version,
        "event_type": event_type,
        "actor": actor,
        "occurred_at": occurred_at.isoformat(),
        "previous_state": previous_state,
        "current_state": initiative.state,
        **(details or {}),
    }
    event = DomainEvent.objects.create(
        workspace_id=initiative.workspace_id,
        event_type=f"curve.initiative.{event_type.lower()}",
        aggregate_type="INITIATIVE",
        aggregate_id=initiative.id,
        aggregate_version=initiative.version,
        sequence=initiative.version,
        actor=actor,
        effective_principal=actor,
        correlation_id=correlation_id,
        idempotency_key_digest=key_digest,
        classification=DataClassification.INTERNAL,
        payload_schema=INITIATIVE_EVENT_SCHEMA,
        payload=payload,
        occurred_at=occurred_at,
    )
    OutboxEvent.objects.create(
        workspace_id=initiative.workspace_id,
        event_id=event.id,
        destination=INITIATIVE_OUTBOX_DESTINATION,
    )


def _before_digest(initiative):
    return sha256_digest(canonical_json_bytes(serialize_initiative(initiative)))


def _complete(*, receipt, record, initiative, response_status, key_digest, before_digest=None):
    ref = initiative_resource_ref(initiative)
    response_digest = operation_response_digest(response_status=response_status, resource_ref=ref)
    append_initiative_mutation_audit(
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
    record.save(update_fields=["state", "response_status", "response_digest", "response_resource_ref", "completed_at"])
    return InitiativeCommandResult(
        initiative=initiative,
        replayed=False,
        response_status=response_status,
        response_digest=response_digest,
        response_resource_ref=ref,
    )


def _replay_with_audit(*, receipt, record):
    result = _resolve_replay(workspace_id=receipt.workspace_id, record=record)
    append_initiative_mutation_audit(
        receipt,
        action=f"{receipt.action}.IDEMPOTENT_REPLAY",
        target_ref=initiative_resource_ref(result.initiative),
        outcome=AuditOutcome.NO_EFFECT,
        key_digest=record.key_digest,
    )
    return result


INITIATIVE_NO_EFFECT_EXCEPTIONS = (
    InitiativeCommandError,
    IdempotencyConflict,
    CommandAlreadyInProgress,
    OptimisticConcurrencyError,
    ReplayResourceUnavailable,
    IntegrityError,
)


def create_initiative(*, request, workspace_slug, payload, raw_idempotency_key):
    def callback(receipt, workspace, _initiative):
        with transaction.atomic():
            _validate_keys(
                payload,
                {
                    "product_id",
                    "mode",
                    "roadmap_item_id",
                    "keyword",
                    "title",
                    "description",
                    "risk_tier",
                    "business_intent",
                    "gate_assignments",
                },
                required={"product_id", "mode", "keyword", "title", "description", "risk_tier", "gate_assignments"},
            )
            product_id = _validate_uuid(payload["product_id"], field="product_id")
            if payload["mode"] == InitiativeMode.ROADMAP:
                raise RoadmapModeNotAvailable
            if payload["mode"] != InitiativeMode.STANDALONE or payload.get("roadmap_item_id") is not None:
                raise InitiativeValidationError(field="mode")
            keyword = _validate_keyword(payload["keyword"])
            title = _validate_title(payload["title"])
            description = _validate_description(payload["description"])
            risk_tier = _validate_risk_tier(payload["risk_tier"])
            business_intent = _validate_business_intent(payload.get("business_intent"), allow_unset=True)
            assignments = _normalize_assignments(
                workspace_id=workspace.id,
                assignments=payload["gate_assignments"],
                risk_tier=risk_tier,
            )
            _resolve_product(workspace_id=workspace.id, product_id=product_id)
            canonical_request = canonical_json_bytes(
                {
                    "command_type": "CREATE_INITIATIVE",
                    "product_id": str(product_id),
                    "mode": InitiativeMode.STANDALONE,
                    "keyword": keyword,
                    "title": title,
                    "description": description,
                    "risk_tier": risk_tier,
                    "business_intent": business_intent,
                    "gate_assignments": [
                        {"gate_type": gate_type, "approver_user_id": str(approver_id)}
                        for gate_type, approver_id in assignments
                    ],
                }
            )
            identity = _command_identity(
                receipt,
                command_scope="CURVE.INITIATIVE.CREATE",
                raw_idempotency_key=raw_idempotency_key,
                canonical_request=canonical_request,
            )
            lock_id = uuid.uuid5(uuid.NAMESPACE_URL, f"curve-initiative:{workspace.id}:{keyword.lower()}")
            _lock_audit_sequence(workspace.id, "INITIATIVE_KEYWORD", lock_id)
            record, _, replay = _load_or_create_idempotency(workspace_id=workspace.id, identity=identity)
            if replay:
                return _replay_with_audit(receipt=receipt, record=record)
            if Initiative.objects.filter(workspace_id=workspace.id, keyword__iexact=keyword).exists():
                raise InitiativeKeywordConflict
            actor = dict(receipt.actor)
            try:
                with transaction.atomic():
                    initiative = Initiative.objects.create(
                        workspace_id=workspace.id,
                        product_id=product_id,
                        mode=InitiativeMode.STANDALONE,
                        roadmap_item_id=None,
                        keyword=keyword,
                        title=title,
                        description=description,
                        risk_tier=risk_tier,
                        business_intent=business_intent,
                        state=InitiativeState.DRAFT,
                        workflow_version_id=None,
                        creator_user_id=uuid.UUID(receipt.actor["actor_id"]),
                        created_by=actor,
                        updated_by=actor,
                    )
            except IntegrityError as error:
                _translate_keyword_integrity_error(error)
            for gate_type, approver_id in assignments:
                GateAssignment.objects.create(
                    workspace_id=workspace.id,
                    initiative=initiative,
                    gate_type=gate_type,
                    approver_user_id=approver_id,
                )
            _append_event(
                initiative=initiative,
                event_type="INITIATIVE_CREATED",
                actor=actor,
                correlation_id=receipt.correlation_id,
                key_digest=identity["key_digest"],
                previous_state=None,
            )
            return _complete(
                receipt=receipt,
                record=record,
                initiative=initiative,
                response_status=201,
                key_digest=identity["key_digest"],
            )

    return execute_initiative_mutation(
        request=request,
        workspace_slug=workspace_slug,
        action="CURVE.INITIATIVE.CREATE",
        callback=callback,
        no_effect_exceptions=INITIATIVE_NO_EFFECT_EXCEPTIONS,
    )


def update_initiative_draft(*, request, workspace_slug, initiative_id, expected_version, payload, raw_idempotency_key):
    def callback(receipt, _workspace, initiative):
        with transaction.atomic():
            _validate_expected_version(expected_version)
            _validate_keys(payload, {"keyword", "title", "description", "risk_tier", "business_intent"})
            if not payload:
                raise InitiativeValidationError
            if initiative.state != InitiativeState.DRAFT or initiative.first_external_resource_at is not None:
                raise InitiativeStateConflict
            values = {}
            if "keyword" in payload:
                values["keyword"] = _validate_keyword(payload["keyword"])
            if "title" in payload:
                values["title"] = _validate_title(payload["title"])
            if "description" in payload:
                values["description"] = _validate_description(payload["description"])
            if "risk_tier" in payload:
                values["risk_tier"] = _validate_risk_tier(payload["risk_tier"])
                _validate_current_assignments(initiative, risk_tier=values["risk_tier"])
            if "business_intent" in payload:
                values["business_intent"] = _validate_business_intent(payload["business_intent"], allow_unset=True)
            canonical_request = canonical_json_bytes(
                {
                    "command_type": "UPDATE_INITIATIVE_DRAFT",
                    "initiative_id": str(initiative_id),
                    "expected_version": expected_version,
                    **values,
                }
            )
            identity = _command_identity(
                receipt,
                command_scope=f"CURVE.INITIATIVE.UPDATE_DRAFT:{initiative_id}",
                raw_idempotency_key=raw_idempotency_key,
                canonical_request=canonical_request,
            )
            record, _, replay = _load_or_create_idempotency(workspace_id=receipt.workspace_id, identity=identity)
            if replay:
                return _replay_with_audit(receipt=receipt, record=record)
            if initiative.version != expected_version:
                raise OptimisticConcurrencyError
            changed = [field for field, value in values.items() if getattr(initiative, field) != value]
            if not changed:
                raise InitiativeNoChanges
            if (
                "keyword" in changed
                and Initiative.objects.filter(
                    workspace_id=initiative.workspace_id,
                    keyword__iexact=values["keyword"],
                )
                .exclude(id=initiative.id)
                .exists()
            ):
                raise InitiativeKeywordConflict
            before = _before_digest(initiative)
            if "business_intent" in changed and initiative.schema_version != "1.1":
                initiative.schema_version = "1.1"
                changed.append("schema_version")
            for field in changed:
                if field in values:
                    setattr(initiative, field, values[field])
            initiative.version += 1
            initiative.updated_by = dict(receipt.actor)
            try:
                with transaction.atomic():
                    initiative.save(update_fields=[*changed, "version", "updated_by", "updated_at"])
            except IntegrityError as error:
                _translate_keyword_integrity_error(error)
            _append_event(
                initiative=initiative,
                event_type="INITIATIVE_DRAFT_UPDATED",
                actor=dict(receipt.actor),
                correlation_id=receipt.correlation_id,
                key_digest=identity["key_digest"],
                previous_state=InitiativeState.DRAFT,
                details={"changed_fields": changed},
            )
            return _complete(
                receipt=receipt,
                record=record,
                initiative=initiative,
                response_status=200,
                key_digest=identity["key_digest"],
                before_digest=before,
            )

    return execute_initiative_mutation(
        request=request,
        workspace_slug=workspace_slug,
        action="CURVE.INITIATIVE.UPDATE_DRAFT",
        initiative_id=initiative_id,
        callback=callback,
        no_effect_exceptions=INITIATIVE_NO_EFFECT_EXCEPTIONS,
    )


def _transition(
    *, request, workspace_slug, initiative_id, expected_version, raw_idempotency_key, command, payload=None
):
    action = f"CURVE.INITIATIVE.{command}"

    def callback(receipt, workspace, initiative):
        with transaction.atomic():
            _validate_expected_version(expected_version)
            reason = None
            if command in {"PAUSE", "RESUME", "CANCEL"}:
                reason = _validate_reason_payload(payload)
            elif payload not in ({}, None):
                raise InitiativeValidationError
            canonical_request = canonical_json_bytes(
                {
                    "command_type": f"{command}_INITIATIVE",
                    "initiative_id": str(initiative_id),
                    "expected_version": expected_version,
                    "reason": reason,
                }
            )
            identity = _command_identity(
                receipt,
                command_scope=f"{action}:{initiative_id}",
                raw_idempotency_key=raw_idempotency_key,
                canonical_request=canonical_request,
            )
            record, _, replay = _load_or_create_idempotency(workspace_id=workspace.id, identity=identity)
            if replay:
                return _replay_with_audit(receipt=receipt, record=record)
            if initiative.version != expected_version:
                raise OptimisticConcurrencyError
            previous_state = initiative.state
            before = _before_digest(initiative)
            if command == "ACCEPT_REFINEMENT":
                if initiative.state != InitiativeState.DRAFT:
                    raise InitiativeStateConflict
                if initiative.business_intent is None:
                    raise InitiativeValidationError(field="business_intent")
                _resolve_product(workspace_id=workspace.id, product_id=initiative.product_id)
                _validate_current_assignments(initiative)
                initiative.state = InitiativeState.ALIGNING
                initiative.workflow_version_id = MANUAL_FIRST_WORKFLOW_VERSION_ID
                event_type = "INITIATIVE_REFINEMENT_ACCEPTED"
                details = {"workflow_version_id": str(MANUAL_FIRST_WORKFLOW_VERSION_ID)}
            elif command == "PAUSE":
                if initiative.state not in {InitiativeState.DRAFT, InitiativeState.ALIGNING}:
                    raise InitiativeStateConflict
                initiative.state = InitiativeState.PAUSED
                initiative.paused_from_state = previous_state
                event_type = "INITIATIVE_PAUSED"
                details = {"reason": reason}
            elif command == "RESUME":
                if initiative.state != InitiativeState.PAUSED or initiative.paused_from_state not in {
                    InitiativeState.DRAFT,
                    InitiativeState.ALIGNING,
                }:
                    raise InitiativeStateConflict
                _validate_current_assignments(initiative)
                if initiative.paused_from_state == InitiativeState.ALIGNING:
                    _resolve_product(workspace_id=workspace.id, product_id=initiative.product_id)
                initiative.state = initiative.paused_from_state
                initiative.paused_from_state = None
                event_type = "INITIATIVE_RESUMED"
                details = {"reason": reason}
            elif command == "CANCEL":
                if initiative.state not in {InitiativeState.DRAFT, InitiativeState.ALIGNING, InitiativeState.PAUSED}:
                    raise InitiativeStateConflict
                initiative.state = InitiativeState.CANCELLED
                initiative.paused_from_state = None
                event_type = "INITIATIVE_CANCELLED"
                details = {"reason": reason}
            else:
                raise InitiativeValidationError
            initiative.version += 1
            initiative.updated_by = dict(receipt.actor)
            initiative.save(
                update_fields=[
                    "state",
                    "paused_from_state",
                    "workflow_version_id",
                    "version",
                    "updated_by",
                    "updated_at",
                ]
            )
            _append_event(
                initiative=initiative,
                event_type=event_type,
                actor=dict(receipt.actor),
                correlation_id=receipt.correlation_id,
                key_digest=identity["key_digest"],
                previous_state=previous_state,
                details=details,
            )
            return _complete(
                receipt=receipt,
                record=record,
                initiative=initiative,
                response_status=200,
                key_digest=identity["key_digest"],
                before_digest=before,
            )

    return execute_initiative_mutation(
        request=request,
        workspace_slug=workspace_slug,
        action=action,
        initiative_id=initiative_id,
        callback=callback,
        no_effect_exceptions=INITIATIVE_NO_EFFECT_EXCEPTIONS,
    )


def accept_initiative_refinement(**kwargs):
    return _transition(command="ACCEPT_REFINEMENT", payload=None, **kwargs)


def pause_initiative(**kwargs):
    return _transition(command="PAUSE", **kwargs)


def resume_initiative(**kwargs):
    return _transition(command="RESUME", **kwargs)


def cancel_initiative(**kwargs):
    return _transition(command="CANCEL", **kwargs)
