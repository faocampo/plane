# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
import uuid
from pathlib import Path

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from plane.curve.models import (
    AuditEvent,
    AuditOutcome,
    DomainEvent,
    IdempotencyRecord,
    IdempotencyState,
    ImmutableRecordError,
    InboxMessage,
    InboxState,
    Operation,
    OperationStatus,
    OperationType,
    OutboxEvent,
    OutboxState,
    PolicyDecision,
    PolicyEffect,
    WorkspaceScopedModel,
)


pytestmark = [pytest.mark.unit, pytest.mark.django_db]

ACTOR = {"actor_type": "HUMAN", "actor_id": "reviewer-alpha"}
DIGEST = f"sha256:{'a' * 64}"
OTHER_DIGEST = f"sha256:{'b' * 64}"
SAFE_ERROR = {"code": "TEST_FAILURE", "retryable": False}


def resource_ref(resource_type="OPERATION", resource_id=None, resource_version=1):
    return {
        "resource_type": resource_type,
        "resource_id": str(resource_id or uuid.uuid4()),
        "resource_version": resource_version,
    }


def operation_values(workspace_id=None, **overrides):
    values = {
        "workspace_id": workspace_id or uuid.uuid4(),
        "operation_type": OperationType.FOUNDATION_PROBE,
        "status": OperationStatus.PENDING,
        "command_type": "CREATE_FOUNDATION_PROBE",
        "target": resource_ref("WORKSPACE"),
        "idempotency_key_digest": DIGEST,
        "created_by": ACTOR,
        "updated_by": ACTOR,
        "correlation_id": "curve-test-correlation",
    }
    values.update(overrides)
    return values


def domain_event_values(workspace_id=None, aggregate_id=None, sequence=1, **overrides):
    values = {
        "workspace_id": workspace_id or uuid.uuid4(),
        "event_type": "curve.operation.created",
        "aggregate_type": "OPERATION",
        "aggregate_id": aggregate_id or uuid.uuid4(),
        "aggregate_version": sequence,
        "sequence": sequence,
        "actor": ACTOR,
        "correlation_id": "curve-test-correlation",
        "payload_schema": "https://curve.example.invalid/contracts/schemas/operation-event-v1.schema.json",
        "payload": {"status": "PENDING"},
    }
    values.update(overrides)
    return values


def audit_event_values(workspace_id=None, target_id=None, sequence=1, **overrides):
    target_id = target_id or uuid.uuid4()
    values = {
        "workspace_id": workspace_id or uuid.uuid4(),
        "sequence": sequence,
        "action": "CURVE.OPERATION.CREATE",
        "target_type": "OPERATION",
        "target_id": target_id,
        "target_ref": resource_ref("OPERATION", target_id),
        "outcome": AuditOutcome.SUCCEEDED,
        "actor": ACTOR,
        "correlation_id": "curve-test-correlation",
    }
    values.update(overrides)
    return values


def idempotency_values(workspace_id=None, **overrides):
    values = {
        "workspace_id": workspace_id or uuid.uuid4(),
        "principal_scope": "HUMAN:reviewer-alpha",
        "command_scope": "CREATE_FOUNDATION_PROBE:workspace",
        "key_digest": DIGEST,
        "request_digest": OTHER_DIGEST,
        "expires_at": timezone.now() + timezone.timedelta(days=1),
    }
    values.update(overrides)
    return values


def policy_decision_values(workspace_id=None, resource_id=None, sequence=1, **overrides):
    values = {
        "workspace_id": workspace_id or uuid.uuid4(),
        "sequence": sequence,
        "action": "CURVE.SHELL.VIEW",
        "resource_type": "WORKSPACE",
        "resource_id": resource_id or uuid.uuid4(),
        "resource_version": 1,
        "subject": ACTOR,
        "effective_principal": ACTOR,
        "effect": PolicyEffect.ALLOW,
        "reason_codes": ["POLICY_ALLOWED"],
        "policy_manifest_digest": DIGEST,
        "input_digest": OTHER_DIGEST,
        "normalized_classification": "INTERNAL",
        "permitted_projection": ["WORKSPACE_ID"],
        "correlation_id": "curve-policy-test",
        "evaluated_at": timezone.now(),
        "recorded_by": {"actor_type": "SERVICE", "actor_id": "curve-api"},
    }
    values.update(overrides)
    return values


def assert_constraint_rejects(create_record):
    with pytest.raises(IntegrityError), transaction.atomic():
        create_record()


def test_workspace_scoped_model_is_abstract_and_creates_no_table():
    assert WorkspaceScopedModel._meta.abstract is True
    assert WorkspaceScopedModel._meta.db_table not in {
        "db_workspace",
        "db_workspacemember",
    }


def test_workspace_scoped_model_has_normative_common_fields():
    assert {field.name for field in WorkspaceScopedModel._meta.fields} == {
        "id",
        "workspace_id",
        "aggregate_version",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
        "tombstoned_at",
        "tombstoned_by",
        "tombstone_reason",
    }


def test_public_context_has_no_transferred_human_authority():
    manifest_path = Path(__file__).parents[1] / "contracts" / "m0-s2-context.json"
    manifest = json.loads(manifest_path.read_text())

    assert manifest["schema_version"] == "curve-public-reference/v1"
    assert manifest["status"] == "PUBLIC_REFERENCE"
    assert manifest["execution_authority"] == "NONE"
    assert manifest["legacy_approval_transfer"] == "PROHIBITED"
    assert "human_owner" not in manifest and "approval_evidence" not in manifest


def test_m003_public_context_cannot_authorize_dispatch():
    manifest_path = Path(__file__).parents[1] / "contracts" / "m0-03-context.json"
    manifest = json.loads(manifest_path.read_text())

    assert manifest["publication_edition"] == "curve-plane-public-contracts-v1"
    assert manifest["execution_authority"] == "NONE"
    assert manifest["legacy_approval_transfer"] == "PROHIBITED"
    assert "dispatch" not in manifest


@pytest.mark.parametrize("status", [OperationStatus.SUCCEEDED, OperationStatus.FAILED, OperationStatus.CANCELLED])
def test_terminal_operation_requires_completed_at(status):
    values = operation_values(status=status)
    if status == OperationStatus.FAILED:
        values["error"] = SAFE_ERROR
    assert_constraint_rejects(lambda: Operation.objects.create(**values))


def test_failed_operation_requires_safe_error():
    assert_constraint_rejects(
        lambda: Operation.objects.create(**operation_values(status=OperationStatus.FAILED, completed_at=timezone.now()))
    )


@pytest.mark.parametrize(
    ("state", "extra"),
    [
        (OutboxState.CLAIMED, {}),
        (OutboxState.RETRY_SCHEDULED, {"last_error": SAFE_ERROR}),
        (OutboxState.DELIVERED, {}),
        (OutboxState.DEAD_LETTER, {}),
    ],
)
def test_outbox_state_requires_its_lifecycle_fields(state, extra):
    assert_constraint_rejects(
        lambda: OutboxEvent.objects.create(
            workspace_id=uuid.uuid4(),
            event_id=uuid.uuid4(),
            destination="TEMPORAL_LOCAL",
            state=state,
            **extra,
        )
    )


@pytest.mark.parametrize(
    ("state", "extra"),
    [
        (InboxState.PROCESSED, {"result_digest": DIGEST}),
        (InboxState.FAILED_TERMINAL, {"last_error": SAFE_ERROR}),
    ],
)
def test_inbox_terminal_state_requires_processed_at(state, extra):
    assert_constraint_rejects(
        lambda: InboxMessage.objects.create(
            workspace_id=uuid.uuid4(),
            consumer_id="curve-test-consumer",
            event_id=uuid.uuid4(),
            state=state,
            **extra,
        )
    )


def test_idempotency_terminal_state_requires_replayable_database_resource():
    assert_constraint_rejects(
        lambda: IdempotencyRecord.objects.create(
            **idempotency_values(
                state=IdempotencyState.COMPLETED,
                response_status=201,
                response_digest=DIGEST,
                completed_at=timezone.now(),
            )
        )
    )


def test_idempotency_model_has_digest_only_key_storage():
    field_names = {field.name for field in IdempotencyRecord._meta.fields}
    assert "key_digest" in field_names
    assert "key" not in field_names
    assert "response_resource_ref" in field_names
    assert "response_ref" not in field_names


def test_workspace_scoped_uniqueness_allows_same_domain_sequence_in_other_workspace():
    aggregate_id = uuid.uuid4()
    DomainEvent.objects.create(**domain_event_values(aggregate_id=aggregate_id))
    DomainEvent.objects.create(**domain_event_values(aggregate_id=aggregate_id))
    assert DomainEvent.objects.filter(aggregate_id=aggregate_id).count() == 2


def test_policy_decision_sequence_is_unique_per_workspace_resource():
    workspace_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    PolicyDecision.objects.create(**policy_decision_values(workspace_id=workspace_id, resource_id=resource_id))

    assert_constraint_rejects(
        lambda: PolicyDecision.objects.create(
            **policy_decision_values(workspace_id=workspace_id, resource_id=resource_id)
        )
    )
    PolicyDecision.objects.create(**policy_decision_values(workspace_id=uuid.uuid4(), resource_id=resource_id))


@pytest.mark.parametrize(
    "overrides",
    [
        {"sequence": 0},
        {"reason_codes": []},
        {"reason_codes": {"reason": "POLICY_ALLOWED"}},
        {"policy_manifest_digest": "raw-digest"},
        {"input_digest": "raw-digest"},
        {"recorded_by": {"actor_type": "HUMAN", "actor_id": "reviewer-alpha"}},
        {"effect": PolicyEffect.DENY, "reason_codes": ["FEATURE_DISABLED"]},
        {"permitted_projection": []},
        {"permitted_projection": {"projection": "WORKSPACE_ID"}},
    ],
)
def test_policy_decision_database_constraints_fail_closed(overrides):
    assert_constraint_rejects(lambda: PolicyDecision.objects.create(**policy_decision_values(**overrides)))


def test_domain_event_uniqueness_rejects_duplicate_workspace_aggregate_sequence():
    workspace_id = uuid.uuid4()
    aggregate_id = uuid.uuid4()
    DomainEvent.objects.create(**domain_event_values(workspace_id=workspace_id, aggregate_id=aggregate_id))
    assert_constraint_rejects(
        lambda: DomainEvent.objects.create(**domain_event_values(workspace_id=workspace_id, aggregate_id=aggregate_id))
    )


def test_outbox_inbox_idempotency_and_audit_uniqueness_are_workspace_scoped():
    workspace_id = uuid.uuid4()
    event_id = uuid.uuid4()
    target_id = uuid.uuid4()

    OutboxEvent.objects.create(
        workspace_id=workspace_id,
        event_id=event_id,
        destination="TEMPORAL_LOCAL",
    )
    assert_constraint_rejects(
        lambda: OutboxEvent.objects.create(
            workspace_id=workspace_id,
            event_id=event_id,
            destination="TEMPORAL_LOCAL",
        )
    )

    InboxMessage.objects.create(
        workspace_id=workspace_id,
        consumer_id="curve-test-consumer",
        event_id=event_id,
    )
    assert_constraint_rejects(
        lambda: InboxMessage.objects.create(
            workspace_id=workspace_id,
            consumer_id="curve-test-consumer",
            event_id=event_id,
        )
    )

    IdempotencyRecord.objects.create(**idempotency_values(workspace_id=workspace_id))
    assert_constraint_rejects(lambda: IdempotencyRecord.objects.create(**idempotency_values(workspace_id=workspace_id)))

    AuditEvent.objects.create(**audit_event_values(workspace_id=workspace_id, target_id=target_id))
    assert_constraint_rejects(
        lambda: AuditEvent.objects.create(**audit_event_values(workspace_id=workspace_id, target_id=target_id))
    )


@pytest.mark.parametrize("model_factory", [domain_event_values, audit_event_values, policy_decision_values])
def test_immutable_history_rejects_update_and_delete(model_factory):
    model = {
        domain_event_values: DomainEvent,
        audit_event_values: AuditEvent,
        policy_decision_values: PolicyDecision,
    }[model_factory]
    record = model.objects.create(**model_factory())

    with pytest.raises(ImmutableRecordError, match="append-only"):
        record.save()
    with pytest.raises(ImmutableRecordError, match="append-only"):
        record.delete()
    with pytest.raises(ImmutableRecordError, match="append-only"):
        model.objects.filter(pk=record.pk).update(sequence=2)
    with pytest.raises(ImmutableRecordError, match="append-only"):
        model.objects.filter(pk=record.pk).delete()


def test_terminal_idempotency_record_is_immutable():
    operation = Operation.objects.create(**operation_values())
    record = IdempotencyRecord.objects.create(
        **idempotency_values(
            state=IdempotencyState.COMPLETED,
            response_status=201,
            response_digest=DIGEST,
            response_resource_ref=resource_ref("OPERATION", operation.id),
            completed_at=timezone.now(),
        )
    )

    record.response_status = 200
    with pytest.raises(ImmutableRecordError, match="terminal"):
        record.save()
    with pytest.raises(ImmutableRecordError, match="locked instance"):
        IdempotencyRecord.objects.filter(pk=record.pk).update(response_status=200)
    with pytest.raises(ImmutableRecordError, match="governed retention"):
        record.delete()
    with pytest.raises(ImmutableRecordError, match="governed retention"):
        IdempotencyRecord.objects.filter(pk=record.pk).delete()
