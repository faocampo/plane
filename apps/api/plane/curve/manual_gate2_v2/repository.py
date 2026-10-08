# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Receipt-bound ledger persistence; existing native task rows fence first acquisition."""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
import uuid

from django.db import transaction
from django.utils import timezone

from plane.curve.manual_plan_v2.validation import metadata_digest
from .contracts import (
    DESTINATION,
    EDITION,
    require,
    record_ref,
    project_record,
    verify_record,
    validate,
)
from .models import (
    Gate2WriteDenied,
    ManualGate2ControlV2,
    ManualGate2RecordV2,
    ManualTaskClaimV2,
    ManualTaskClaimHistoryV2,
)
from .policy import assert_active
from . import domain as g

_WRITE = ContextVar("exact_manual_gate2_write", default=None)


def _values(record):
    return {f.attname: deepcopy(getattr(record, f.attname)) for f in record._meta.local_fields}


@contextmanager
def exact_write(receipt, records):
    assert_active(receipt)
    expected = {(type(row), row.id): _values(row) for row in records}
    require(len(expected) == len(records) and all(row.workspace_id == receipt.workspace_id for row in records))
    token = _WRITE.set((receipt, expected))
    try:
        yield
    finally:
        _WRITE.reset(token)


def assert_exact_write(record):
    active = _WRITE.get()
    if active is None or not transaction.get_connection().in_atomic_block:
        raise Gate2WriteDenied("Exact active Gate 2 write required")
    receipt, records = active
    assert_active(receipt)
    if records.get((type(record), record.id)) != _values(record):
        raise Gate2WriteDenied("Record does not match the authorized Gate 2 graph")


def load_record(initiative, identifier):
    row = ManualGate2RecordV2.objects.select_for_update().filter(id=identifier).first()
    require(
        row is not None
        and row.workspace_id == initiative.workspace_id
        and row.initiative_id == initiative.id
        and row.product_id == initiative.product_id
    )
    verify_record(row)
    return row


def load_control(initiative):
    heads = list(ManualGate2ControlV2.objects.select_for_update().filter(initiative_id=initiative.id)[:2])
    require(len(heads) <= 1)
    if not heads:
        require(not ManualGate2RecordV2.objects.filter(initiative_id=initiative.id).exists())
        return None
    head = heads[0]
    require(head.workspace_id == initiative.workspace_id and head.product_id == initiative.product_id)
    current = load_record(initiative, head.current_record_id)
    require(current.control_id == head.id and current.version == head.version and current.subject_id == head.subject_id)
    require(ManualGate2RecordV2.objects.filter(control_id=head.id).count() == head.version)
    return head


def lock_claims(initiative, subject):
    from plane.db.models import Issue

    tasks = subject.tasks
    require(tasks and all(t.workspace_id == str(initiative.workspace_id) for t in tasks))
    ids = [t.issue_id for t in tasks]
    issues = list(
        Issue.issue_objects.select_for_update(of=("self",))
        .filter(workspace_id=initiative.workspace_id, id__in=ids)
        .order_by("id")
    )
    require(len(issues) == len(ids))
    rows = list(
        ManualTaskClaimV2.objects.select_for_update()
        .filter(
            workspace_id=initiative.workspace_id,
            installation_id__in={t.installation_id for t in tasks},
            issue_id__in=ids,
        )
        .order_by("installation_id", "issue_id")
    )
    keys = {g.TaskKey(str(row.workspace_id), str(row.installation_id), str(row.issue_id)): row for row in rows}
    require(set(keys) <= set(tasks) and len(keys) == len(rows))
    for row in rows:
        history = ManualTaskClaimHistoryV2.objects.select_for_update().filter(id=row.current_history_id).first()
        require(
            history is not None
            and history.claim_id == row.id
            and history.record_id == row.current_record_id
            and history.workspace_id == row.workspace_id
            and history.initiative_id == row.initiative_id
            and history.generation == row.generation
            and history.state == row.state
        )
        original = ManualGate2RecordV2.objects.select_for_update().filter(id=row.subject_id).first()
        require(
            original is not None
            and original.action == "PREPARE"
            and original.subject_id == original.id
            and original.workspace_id == row.workspace_id
            and original.initiative_id == row.initiative_id
        )
        verify_record(original)
    return keys


def ledger_from_claims(claims):
    records = {row.subject_id: ManualGate2RecordV2.objects.get(id=row.subject_id) for row in claims.values()}
    return g.Ledger(
        tuple(
            g.Claim(
                task,
                row.generation,
                str(row.initiative_id),
                records[row.subject_id].subject_digest,
                row.state,
            )
            for task, row in sorted(claims.items())
        )
    )


def command_identity(command, actor):
    from plane.curve.services import idempotency_key_digest

    return dict(
        principal_scope=f"HUMAN:{actor}",
        command_scope=f"CURVE.MANUAL_GATE2.{command.action}_V2:{command.initiative_id}",
        key_digest=idempotency_key_digest(command.key),
        request_digest=command.request_digest,
        expires_at=timezone.now() + timedelta(days=1),
    )


@dataclass(frozen=True)
class Result:
    data: dict
    initiative_version: int
    replayed: bool = False

    @property
    def status_code(self):
        return 200 if self.replayed else 201


def append_graph(
    *,
    receipt,
    authority,
    command,
    control,
    subject_row,
    subject,
    state,
    claim_rows,
    selected_claims,
    observations,
    reconciliation_id,
    idem,
    fence,
):
    from plane.curve.models import DomainEvent, OutboxEvent
    from plane.curve.services import _append_audit_event, operation_response_digest

    assert_active(receipt)
    initiative = authority.context.initiative
    require(initiative.version == command.expected_version, "PRECONDITION_FAILED", 412)
    now = timezone.now()
    identifier, event_id = uuid.uuid4(), uuid.uuid4()
    old_record = control.current_record_id if control is not None else None
    if control is None:
        control = ManualGate2ControlV2(
            workspace_id=initiative.workspace_id,
            product_id=initiative.product_id,
            initiative_id=initiative.id,
            version=0,
        )
    version = control.version + 1
    subject_id = identifier if command.action == "PREPARE" else subject_row.id
    output_claims, history_rows, writes = [], [], []
    for selected in selected_claims:
        row = claim_rows.get(selected.task)
        if row is None:
            row = ManualTaskClaimV2(
                workspace_id=initiative.workspace_id,
                installation_id=selected.task.installation_id,
                issue_id=selected.task.issue_id,
            )
        history_id = uuid.uuid4()
        row.initiative_id, row.subject_id = initiative.id, subject_id
        row.generation, row.state = selected.generation, selected.state
        row.current_record_id, row.current_history_id = identifier, history_id
        projection = dict(
            claim_id=str(row.id),
            history_id=str(history_id),
            installation_id=str(row.installation_id),
            issue_id=str(row.issue_id),
            initiative_id=str(row.initiative_id),
            subject_id=str(row.subject_id),
            generation=row.generation,
            state=row.state,
            record_id=str(identifier),
        )
        output_claims.append(projection)
        history_rows.append(
            ManualTaskClaimHistoryV2(
                id=history_id,
                workspace_id=initiative.workspace_id,
                claim_id=row.id,
                record_id=identifier,
                initiative_id=initiative.id,
                generation=row.generation,
                state=row.state,
                payload=projection,
            )
        )
        writes.append(row)
    payload = dict(
        schema_version="curve.manual-gate2.record/v2-candidate",
        policy_edition=EDITION,
        id=str(identifier),
        workspace_id=str(initiative.workspace_id),
        product_id=str(initiative.product_id),
        initiative_id=str(initiative.id),
        sequence=version,
        initiative_version=initiative.version + 1,
        predecessor_id=None if old_record is None else str(old_record),
        action=command.action,
        actor_id=str(receipt.actor_id),
        subject_id=str(subject_id),
        subject_digest=subject.digest,
        draft_revision_id=command.payload["draft_revision_id"],
        subject_metadata=subject.data if command.action == "PREPARE" else None,
        rationale_ref=command.payload["rationale_ref"],
        reconciliation_id=None if reconciliation_id is None else str(reconciliation_id),
        observations=observations,
        claims=output_claims,
        native_fence_digest=fence,
        request_digest=command.request_digest,
        policy_decision_id=str(receipt.decision_id),
        command_receipt_id=str(event_id),
        recorded_at=now.isoformat(timespec="microseconds").replace("+00:00", "Z"),
    )
    payload["digest"] = metadata_digest(payload)
    validate("record", payload)
    record = ManualGate2RecordV2(
        id=identifier,
        workspace_id=initiative.workspace_id,
        product_id=initiative.product_id,
        initiative_id=initiative.id,
        control_id=control.id,
        version=version,
        initiative_version=initiative.version + 1,
        predecessor_id=old_record,
        action=command.action,
        subject_id=subject_id,
        subject_digest=subject.digest,
        draft_revision_id=command.payload["draft_revision_id"],
        digest=payload["digest"],
        payload=payload,
        request_payload=command.payload,
        request_digest=command.request_digest,
        policy_decision_id=receipt.decision_id,
        command_receipt_id=event_id,
        created_by=receipt.actor_id,
        recorded_at=now,
    )
    control.version, control.current_record_id, control.subject_id, control.state = (
        version,
        identifier,
        subject_id,
        state,
    )
    if command.action == "APPROVE":
        require(control.approved_record_id is None)
        control.approved_record_id = identifier
    with exact_write(receipt, [record, control, *writes, *history_rows]):
        record.save(force_insert=True)
        control.save()
        for row in writes:
            row.save()
        for row in history_rows:
            row.save(force_insert=True)
    actor = dict(actor_type="HUMAN", actor_id=str(receipt.actor_id))
    initiative.version += 1
    initiative.updated_by = actor
    initiative.save(update_fields=["version", "updated_by", "updated_at"])
    event_payload = dict(
        schema_version="curve.manual-gate2.event/v2-candidate",
        record_id=str(identifier),
        record_digest=record.digest,
        subject_digest=subject.digest,
        action=command.action,
        policy_decision_id=str(receipt.decision_id),
        execution_authorized=False,
        completion_credit=False,
    )
    DomainEvent.objects.create(
        id=event_id,
        workspace_id=initiative.workspace_id,
        event_type="CURVE.MANUAL_GATE2_RECORDED_V2",
        schema_version="1.0",
        initiative_id=initiative.id,
        workflow_version_id=initiative.workflow_version_id,
        aggregate_type="MANUAL_GATE2_CONTROL_V2",
        aggregate_id=control.id,
        aggregate_version=version,
        sequence=version,
        actor=actor,
        effective_principal=actor,
        correlation_id=receipt.correlation_id,
        idempotency_key_digest=idem.key_digest,
        classification="INTERNAL",
        payload_schema="https://curve.example.invalid/candidates/manual-gate2-v2/event.schema.json",
        payload=event_payload,
        occurred_at=now,
    )
    OutboxEvent.objects.create(workspace_id=initiative.workspace_id, event_id=event_id, destination=DESTINATION)
    reference = record_ref(record)
    response_digest = operation_response_digest(response_status=201, resource_ref=reference)
    _append_audit_event(
        workspace_id=initiative.workspace_id,
        action=receipt.action,
        target_ref=reference,
        outcome="SUCCEEDED",
        actor=actor,
        effective_principal=actor,
        correlation_id=receipt.correlation_id,
        key_digest=idem.key_digest,
        after_digest=response_digest,
        policy_decision_ref=dict(
            resource_type="POLICY_DECISION",
            resource_id=str(receipt.decision_id),
            resource_version=1,
        ),
    )
    idem.state, idem.response_status, idem.response_resource_ref = (
        "COMPLETED",
        201,
        reference,
    )
    idem.response_digest, idem.completed_at = response_digest, timezone.now()
    idem.save(
        update_fields=[
            "state",
            "response_status",
            "response_resource_ref",
            "response_digest",
            "completed_at",
        ]
    )
    return Result(project_record(record), initiative.version), control
