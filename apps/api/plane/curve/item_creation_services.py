# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Joint creation candidate; unavailable until additive native qualification."""

from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

from django.utils import timezone

from plane.curve.item_creation_input import ItemCreationInputError, normalize_item_creation
from plane.curve.item_creation_policy import append_audit, assert_receipt, execute_item_creation_mutation
from plane.curve.item_creation_results import pair_reference, validate_retained_creation
from plane.curve.initiative_services import InitiativeKeywordConflict, _append_event
from plane.curve.models import (
    AuditOutcome,
    DomainEvent,
    GateAssignment,
    IdempotencyRecord,
    IdempotencyState,
    Initiative,
    OutboxEvent,
    RoadmapItem,
)
from plane.curve.policy_services import CurvePolicyResourceNotFound
from plane.curve.product_services import _command_identity, _load_or_create_idempotency, ProductValidationError
from plane.curve.services import (
    CommandAlreadyInProgress,
    IdempotencyConflict,
    OptimisticConcurrencyError,
    ReplayResourceUnavailable,
    _lock_audit_sequence,
    canonical_json_bytes,
    operation_response_digest,
)


class ItemPlacementConflict(ValueError):
    code = "ROADMAP_ITEM_PLACEMENT_CONFLICT"


@dataclass(frozen=True, slots=True)
class PreparedItemCreation:
    identity: dict
    item: object | None
    replay_record: object | None


@dataclass(frozen=True, slots=True)
class ItemCreationResult:
    resource_ref: dict
    response_status: int
    response_digest: str
    replayed: bool


def _retained_pair(facts, record):
    item_id, initiative_id = validate_retained_creation(record)
    item = (
        RoadmapItem.objects.select_for_update()
        .filter(
            workspace_id=facts.workspace_id,
            product_id=facts.product_id,
            roadmap_id=facts.roadmap_id,
            id=item_id,
            defining_initiative_id=initiative_id,
            tombstoned_at__isnull=True,
        )
        .first()
    )
    initiative = (
        Initiative.objects.select_for_update()
        .filter(
            workspace_id=facts.workspace_id,
            product_id=facts.product_id,
            id=initiative_id,
            roadmap_item_id=item_id,
            mode="ROADMAP",
        )
        .first()
    )
    if item is None or initiative is None or item.schema_version != "1.0" or initiative.schema_version != "1.2":
        raise ReplayResourceUnavailable
    if item.version < 1 or initiative.version < 1:
        raise ReplayResourceUnavailable
    return item


def execute_item_creation(
    *, request, workspace_slug, product_id, roadmap_id, payload, expected_version, raw_idempotency_key
):
    command = normalize_item_creation(payload, expected_version)
    try:
        product_id, roadmap_id = UUID(str(product_id)), UUID(str(roadmap_id))
    except (ValueError, TypeError, AttributeError) as error:
        raise CurvePolicyResourceNotFound from error

    def prepare(facts):
        identity = _command_identity(
            SimpleNamespace(actor={"actor_type": "HUMAN", "actor_id": str(facts.actor.user_id)}),
            command_scope=f"CURVE.ITEM.CREATE_ROADMAP_ITEM_INITIATIVE:{product_id}:{roadmap_id}",
            raw_idempotency_key=raw_idempotency_key,
            canonical_request=canonical_json_bytes(
                {
                    "action": "CREATE_ROADMAP_ITEM_INITIATIVE",
                    "workspace_id": str(facts.workspace_id),
                    "product_id": str(product_id),
                    "roadmap_id": str(roadmap_id),
                    "expected_version": command.expected_version,
                    "payload": command.as_payload(),
                }
            ),
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
        item = None
        if retained is not None:
            if retained.request_digest != identity["request_digest"]:
                raise IdempotencyConflict
            if retained.state not in IdempotencyRecord.TERMINAL_STATES:
                raise CommandAlreadyInProgress
            item = _retained_pair(facts, retained)
        return PreparedItemCreation(identity, item, retained)

    def callback(receipt, prepared):
        assert_receipt(receipt)
        values = command.as_payload()
        draft = values.pop("initiative")
        lock_id = uuid5(NAMESPACE_URL, f"curve-initiative:{receipt.workspace_id}:{draft['keyword'].lower()}")
        _lock_audit_sequence(receipt.workspace_id, "INITIATIVE_KEYWORD", lock_id)
        record, _, replay = _load_or_create_idempotency(workspace_id=receipt.workspace_id, identity=prepared.identity)
        if replay:
            if prepared.replay_record is None or prepared.replay_record.id != record.id:
                raise ReplayResourceUnavailable
            validate_retained_creation(record)
            ref = deepcopy(record.response_resource_ref)
            append_audit(
                receipt, target_ref=ref, outcome=AuditOutcome.NO_EFFECT, key_digest=record.key_digest, replay=True
            )
            return ItemCreationResult(ref, record.response_status, record.response_digest, True)
        if prepared.replay_record is not None:
            raise ReplayResourceUnavailable
        if receipt.roadmap_version != command.expected_version:
            raise OptimisticConcurrencyError
        if Initiative.objects.filter(workspace_id=receipt.workspace_id, keyword__iexact=draft["keyword"]).exists():
            raise InitiativeKeywordConflict
        if RoadmapItem.objects.filter(
            workspace_id=receipt.workspace_id, milestone_id=values["milestone_id"], feature_id=values["feature_id"]
        ).exists():
            raise ItemPlacementConflict
        actor = dict(receipt.actor)
        item_id, initiative_id = uuid4(), uuid4()
        assignments = draft.pop("gate_assignments")
        initiative = Initiative.objects.create(
            id=initiative_id,
            workspace_id=receipt.workspace_id,
            product_id=receipt.product_id,
            schema_version="1.2",
            mode="ROADMAP",
            roadmap_item_id=item_id,
            state="DRAFT",
            workflow_version_id=None,
            creator_user_id=UUID(actor["actor_id"]),
            created_by=actor,
            updated_by=actor,
            **draft,
        )
        item = RoadmapItem.objects.create(
            id=item_id,
            workspace_id=receipt.workspace_id,
            product_id=receipt.product_id,
            roadmap_id=receipt.roadmap_id,
            defining_initiative_id=initiative_id,
            owner_user_id=receipt.roadmap_owner_id,
            status="PROPOSED",
            declared_progress=0,
            progress_note="",
            approved_prd_version_id=None,
            created_by=actor,
            updated_by=actor,
            **values,
        )
        for assignment in assignments:
            GateAssignment.objects.create(workspace_id=receipt.workspace_id, initiative=initiative, **assignment)
        _append_event(
            initiative=initiative,
            event_type="INITIATIVE_CREATED",
            actor=actor,
            correlation_id=receipt.correlation_id,
            key_digest=record.key_digest,
            previous_state=None,
        )
        ref = pair_reference(item_id=item.id, initiative_id=initiative.id)
        _append_item_event(receipt, item, ref, record.key_digest)
        digest = operation_response_digest(response_status=201, resource_ref=ref)
        append_audit(
            receipt, target_ref=ref, outcome=AuditOutcome.SUCCEEDED, key_digest=record.key_digest, after_digest=digest
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status, record.response_digest, record.response_resource_ref = 201, digest, ref
        record.completed_at = timezone.now()
        record.save(
            update_fields=["state", "response_status", "response_digest", "response_resource_ref", "completed_at"]
        )
        return ItemCreationResult(ref, 201, digest, False)

    return execute_item_creation_mutation(
        request=request,
        workspace_slug=workspace_slug,
        product_id=product_id,
        roadmap_id=roadmap_id,
        command=command,
        prepare=prepare,
        callback=callback,
        no_effect_exceptions=(
            ItemCreationInputError,
            ProductValidationError,
            CommandAlreadyInProgress,
            IdempotencyConflict,
            OptimisticConcurrencyError,
            ReplayResourceUnavailable,
            InitiativeKeywordConflict,
            ItemPlacementConflict,
        ),
    )


def _append_item_event(receipt, item, ref, key_digest):
    from plane.curve.item_creation_events import build_item_creation_event

    assert_receipt(receipt)
    at = timezone.now()
    payload = build_item_creation_event(
        workspace_id=receipt.workspace_id,
        product_id=receipt.product_id,
        roadmap_id=receipt.roadmap_id,
        milestone_id=item.milestone_id,
        feature_id=item.feature_id,
        owner_id=item.owner_user_id,
        result=ref,
        actor=dict(receipt.actor),
        occurred_at=at.isoformat(),
    )
    event = DomainEvent.objects.create(
        workspace_id=receipt.workspace_id,
        event_type="curve.roadmap_item.created",
        aggregate_type="ROADMAP_ITEM",
        aggregate_id=item.id,
        aggregate_version=1,
        sequence=1,
        actor=dict(receipt.actor),
        effective_principal=dict(receipt.actor),
        correlation_id=receipt.correlation_id,
        idempotency_key_digest=key_digest,
        classification=receipt.classification,
        payload_schema="https://curve.example.invalid/contracts/candidates/item-creation-event-v1.schema.json",
        payload=payload,
        occurred_at=at,
    )
    OutboxEvent.objects.create(workspace_id=receipt.workspace_id, event_id=event.id, destination="CURVE_ITEM_LOCAL_V1")
