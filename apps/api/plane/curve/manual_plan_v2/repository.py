# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Receipt-bound draft persistence using the incumbent transaction/event kernel."""

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from .contracts import (
    ACTION,
    EVENT_SCHEMA,
    EVENT_TYPE,
    OUTBOX_DESTINATION,
    RESOURCE_TYPE,
    build_revision,
    event_payload,
    require,
    resource_ref,
    verify_revision,
)
from .models import ImmutableDraftError, ManualPlanDraftV2, ManualPlanRevisionV2
from .validation import canonical_json, digest

_WRITE = ContextVar("manual_plan_v2_exact_write", default=None)


@dataclass(frozen=True)
class DraftResult:
    data: dict
    initiative_version: int
    replayed: bool = False

    @property
    def status_code(self):
        return 200 if self.replayed else 201


def _values(record):
    return {field.attname: deepcopy(getattr(record, field.attname)) for field in record._meta.local_fields}


def _require_atomic():
    if not transaction.get_connection().in_atomic_block:
        raise ImmutableDraftError("A manual-plan transaction is required")


@contextmanager
def _write_records(receipt, head, revision):
    from .policy import assert_active_receipt

    _require_atomic()
    assert_active_receipt(receipt)
    require(
        revision.workspace_id == head.workspace_id == receipt.workspace_id
        and revision.initiative_id == head.initiative_id == receipt.initiative_id
        and revision.product_id == head.product_id == receipt.product_id
        and revision.draft_id == head.id
        and revision.id == head.current_revision_id
        and revision.version == head.version
        and revision.created_by == receipt.actor_id
        and revision.policy_decision_id == receipt.decision_id
        and revision.input_identity_digest == receipt.input_identity_digest
        and revision.validation_receipt_digest == receipt.validation_receipt_digest,
    )
    token = _WRITE.set((receipt, {(type(item), item.id): _values(item) for item in (head, revision)}))
    try:
        yield
    finally:
        _WRITE.reset(token)


def assert_draft_write(record):
    from .policy import assert_active_receipt

    _require_atomic()
    active = _WRITE.get()
    if active is None:
        raise ImmutableDraftError("An exact active manual-plan receipt is required")
    receipt, expected = active
    assert_active_receipt(receipt)
    if expected.get((type(record), record.id)) != _values(record):
        raise ImmutableDraftError("The manual-plan receipt does not authorize this record")


def load_head(initiative):
    _require_atomic()
    # Corrupt workspace/product coordinates must not turn into apparent absence.
    heads = list(ManualPlanDraftV2.objects.select_for_update().filter(initiative_id=initiative.id)[:2])
    require(len(heads) <= 1)
    if not heads:
        require(not ManualPlanRevisionV2.objects.filter(initiative_id=initiative.id).exists())
        return None, None
    head = heads[0]
    require(head.workspace_id == initiative.workspace_id and head.product_id == initiative.product_id)
    revision = load_revision(initiative, head, head.current_revision_id)
    require(revision.version == head.version)
    return head, revision


def load_revision(initiative, head, revision_id):
    _require_atomic()
    revision = ManualPlanRevisionV2.objects.select_for_update().filter(id=revision_id).first()
    require(revision is not None)
    require(
        revision.workspace_id == initiative.workspace_id == head.workspace_id
        and revision.initiative_id == initiative.id == head.initiative_id
        and revision.product_id == initiative.product_id == head.product_id
        and revision.draft_id == head.id
        and revision.initiative_version <= initiative.version,
    )
    verify_revision(revision)
    if revision.version == 1:
        require(revision.predecessor_id is None)
    else:
        previous = ManualPlanRevisionV2.objects.select_for_update().filter(id=revision.predecessor_id).first()
        require(
            previous is not None
            and previous.draft_id == head.id
            and previous.workspace_id == initiative.workspace_id
            and previous.initiative_id == initiative.id
            and previous.product_id == initiative.product_id
            and previous.version + 1 == revision.version
            and previous.initiative_version < revision.initiative_version
            and previous.recorded_at <= revision.recorded_at,
        )
        verify_revision(previous)
    return revision


def replay_revision(*, initiative, head, record):
    """Integrity only; the caller must reauthorize this ORIGINAL input identity."""
    from plane.curve.models import DomainEvent
    from plane.curve.services import operation_response_digest

    reference = record.response_resource_ref
    require(
        record.state == "COMPLETED"
        and record.response_status == 201
        and head is not None
        and type(reference) is dict
        and set(reference) == {"resource_type", "resource_id", "resource_version"}
        and reference["resource_type"] == RESOURCE_TYPE,
    )
    revision = load_revision(initiative, head, reference["resource_id"])
    require(reference == resource_ref(revision))
    require(record.response_digest == operation_response_digest(response_status=201, resource_ref=reference))
    event = DomainEvent.objects.filter(workspace_id=initiative.workspace_id, id=revision.command_receipt_id).first()
    require(
        event is not None
        and event.event_type == EVENT_TYPE
        and event.aggregate_id == head.id
        and event.aggregate_version == revision.version
        and event.payload == event_payload(revision)
        and event.idempotency_key_digest == record.key_digest,
    )
    return revision


def _revision_model(data, *, identity, validation_receipt, policy_decision_id, event_id):
    ids = {
        key: uuid.UUID(data[key])
        for key in (
            "id",
            "workspace_id",
            "product_id",
            "initiative_id",
            "draft_id",
            "created_by",
        )
    }
    return ManualPlanRevisionV2(
        **ids,
        version=data["revision"],
        initiative_version=data["initiative_version"],
        predecessor_id=uuid.UUID(data["predecessor_id"]) if data["predecessor_id"] else None,
        digest=data["digest"],
        payload=deepcopy(data),
        original_input_identity=deepcopy(identity),
        input_identity_digest=identity["digest"],
        validation_receipt=deepcopy(validation_receipt),
        validation_receipt_digest=validation_receipt["digest"],
        policy_decision_id=policy_decision_id,
        command_receipt_id=event_id,
        recorded_at=datetime.fromisoformat(data["recorded_at"].replace("Z", "+00:00")),
    )


def publish_new_revision(*, receipt, initiative, command, identity, validation_receipt, idempotency_record):
    """Publish the graph in the caller's transaction, never in an implicit commit.

    Final current authority and protected-file fences remain mandatory after this
    method and before that outer transaction may commit. No provider dispatch.
    """
    from plane.curve.models import DomainEvent, OutboxEvent
    from plane.curve.services import _append_audit_event, operation_response_digest
    from .policy import assert_active_receipt

    _require_atomic()
    assert_active_receipt(receipt)
    require(command.request_digest == receipt.request_digest)
    require(
        idempotency_record.workspace_id == initiative.workspace_id
        and idempotency_record.principal_scope == f"HUMAN:{receipt.actor_id}"
        and idempotency_record.command_scope == f"{ACTION}:{initiative.id}"
        and idempotency_record.request_digest == command.request_digest
        and idempotency_record.state == "IN_PROGRESS",
        "COMMAND_CONFLICT",
    )
    head, previous = load_head(initiative)
    draft_id = head.id if head else uuid.uuid4()
    now = timezone.now()
    data = build_revision(
        initiative=initiative,
        actor_id=receipt.actor_id,
        draft_id=draft_id,
        revision_id=uuid.uuid4(),
        previous=previous,
        command=command,
        identity=identity,
        receipt=validation_receipt,
        recorded_at=now,
    )
    event_id = uuid.uuid4()
    revision = _revision_model(
        data,
        identity=identity,
        validation_receipt=validation_receipt,
        policy_decision_id=receipt.decision_id,
        event_id=event_id,
    )
    new_head = head is None
    head = head or ManualPlanDraftV2(
        id=draft_id, workspace_id=initiative.workspace_id, product_id=initiative.product_id, initiative_id=initiative.id
    )
    head.version, head.current_revision_id = revision.version, revision.id
    with _write_records(receipt, head, revision):
        revision.save(force_insert=True)
        head.save(force_insert=new_head, force_update=not new_head)
    actor = dict(actor_type="HUMAN", actor_id=str(receipt.actor_id))
    initiative.version = revision.initiative_version
    initiative.updated_by = actor
    initiative.save(update_fields=["version", "updated_by", "updated_at"])
    DomainEvent.objects.create(
        id=event_id,
        workspace_id=initiative.workspace_id,
        initiative_id=initiative.id,
        event_type=EVENT_TYPE,
        aggregate_type="MANUAL_PLAN_DRAFT_V2",
        aggregate_id=head.id,
        aggregate_version=revision.version,
        sequence=revision.version,
        actor=actor,
        effective_principal=actor,
        correlation_id=receipt.correlation_id,
        idempotency_key_digest=idempotency_record.key_digest,
        classification="INTERNAL",
        payload_schema=EVENT_SCHEMA,
        payload=event_payload(revision),
        occurred_at=now,
    )
    OutboxEvent.objects.create(workspace_id=initiative.workspace_id, event_id=event_id, destination=OUTBOX_DESTINATION)
    reference = resource_ref(revision)
    response_digest = operation_response_digest(response_status=201, resource_ref=reference)
    _append_audit_event(
        workspace_id=initiative.workspace_id,
        action=ACTION,
        target_ref=reference,
        outcome="SUCCEEDED",
        actor=actor,
        effective_principal=actor,
        correlation_id=receipt.correlation_id,
        key_digest=idempotency_record.key_digest,
        after_digest=response_digest,
        policy_decision_ref=dict(
            resource_type="POLICY_DECISION", resource_id=str(receipt.decision_id), resource_version=1
        ),
    )
    idempotency_record.state = "COMPLETED"
    idempotency_record.response_status = 201
    idempotency_record.response_resource_ref = reference
    idempotency_record.response_digest = response_digest
    idempotency_record.completed_at = timezone.now()
    idempotency_record.save(
        update_fields=["state", "response_status", "response_resource_ref", "response_digest", "completed_at"]
    )
    return DraftResult(data, initiative.version)


def command_identity(command, actor_id):
    """Identity is independent of mutable head/current authority generations."""
    from datetime import timedelta
    from plane.curve.services import idempotency_key_digest

    return dict(
        principal_scope=f"HUMAN:{actor_id}",
        command_scope=f"{ACTION}:{command.initiative_id}",
        key_digest=idempotency_key_digest(command.key),
        request_digest=command.request_digest,
        expires_at=timezone.now() + timedelta(days=1),
    )


def request_digest_from_revision(revision):
    """Reconstruct the original closed command, never the current head's pins."""
    data = verify_revision(revision)
    payload = dict(
        schema_version="curve.manual-plan-draft.save/v2-candidate",
        policy_edition=data["policy_edition"],
        expected_draft_revision=revision.version - 1,
        **{key: data[key] for key in ("approved_subject_ref", "definition_ref", "manual_profile_ref")},
    )
    return digest(
        canonical_json(
            dict(
                payload=payload,
                initiative_id=str(revision.initiative_id),
                expected_initiative_version=revision.initiative_version - 1,
            )
        )
    )
