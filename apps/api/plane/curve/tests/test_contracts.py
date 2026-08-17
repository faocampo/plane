import hashlib
import json
import uuid
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource

from plane.curve.models import AuditEvent, DomainEvent, IdempotencyRecord, InboxMessage, OutboxEvent
from plane.curve.serialization import (
    serialize_audit_event,
    serialize_domain_event,
    serialize_idempotency_record,
    serialize_inbox_message,
    serialize_operation,
    serialize_outbox_event,
)
from plane.curve.services import create_operation


pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]

ACTOR = {"actor_type": "HUMAN", "actor_id": "federico"}
SCHEMA_DIGESTS = {
    "audit-event.schema.json": "36fcb1f4023cc26619f5e20bf78670e83b2bf4bb48112fdaca1481daa84157f1",
    "common.schema.json": "b00c8c420f7e78f20adea2b3a097d74a4e97e73c0f2cc71ad9ac5c4933e31583",
    "event-envelope.schema.json": "de28a9654520b2f27d307b246a48f4d6b847e924d53e1d95513c47c29c5166ed",
    "idempotency-record.schema.json": "9c40ad05af41e89d1fa8890550f03591c106070337c2cf5ff091aedd74210801",
    "inbox-message.schema.json": "e1b06e1cb5ea157e2249014229dceac3c1ea0f07bda393a2832ba886dcd84527",
    "operation-event-v1.schema.json": "fdba17d38e5e930b9abca6ceae47a7dd7b33c4bdd88b5e740e684c89548315d0",
    "operation.schema.json": "887c0d1e9b667f61db66834efdcafc72f581e71641a66e0bfa4006661bbb9aff",
    "outbox-event.schema.json": "fd5db47b56f359eb7333e06c0c7ec1f9f90b00a6b4b07f791f10d0177cc79711",
}


@pytest.fixture(scope="module")
def schema_contracts():
    schema_directory = Path(__file__).parents[1] / "contracts" / "schemas"
    schemas = {path.name: json.loads(path.read_text()) for path in schema_directory.glob("*.schema.json")}
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas.values())
    return {
        name: Draft202012Validator(
            schema,
            registry=registry,
            format_checker=FormatChecker(),
        )
        for name, schema in schemas.items()
    }


def create_contract_operation(workspace_id):
    return create_operation(
        workspace_id=workspace_id,
        principal_scope="HUMAN:federico",
        command_scope=f"CREATE_FOUNDATION_PROBE:{workspace_id}",
        raw_idempotency_key="contract-test-key",
        canonical_request=b'{"command":"CREATE_FOUNDATION_PROBE"}',
        operation_type="FOUNDATION_PROBE",
        command_type="CREATE_FOUNDATION_PROBE",
        target={
            "resource_type": "WORKSPACE",
            "resource_id": str(workspace_id),
            "resource_version": 1,
        },
        actor=ACTOR,
        correlation_id="curve-contract-test",
    ).operation


def test_schema_snapshot_digests_bind_the_pinned_curve_revision():
    schema_directory = Path(__file__).parents[1] / "contracts" / "schemas"
    observed = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in schema_directory.glob("*.schema.json")
    }
    assert observed == SCHEMA_DIGESTS


def test_persisted_records_serialize_against_pinned_json_schemas(schema_contracts):
    workspace_id = uuid.uuid4()
    operation = create_contract_operation(workspace_id)
    event = DomainEvent.objects.get(workspace_id=workspace_id)
    outbox = OutboxEvent.objects.get(workspace_id=workspace_id)
    replay = IdempotencyRecord.objects.get(workspace_id=workspace_id)
    audit = AuditEvent.objects.get(workspace_id=workspace_id)
    inbox = InboxMessage.objects.create(
        workspace_id=workspace_id,
        consumer_id="curve-contract-consumer",
        event_id=event.id,
    )

    documents = {
        "operation.schema.json": serialize_operation(operation),
        "event-envelope.schema.json": serialize_domain_event(event),
        "operation-event-v1.schema.json": event.payload,
        "outbox-event.schema.json": serialize_outbox_event(outbox),
        "inbox-message.schema.json": serialize_inbox_message(inbox),
        "idempotency-record.schema.json": serialize_idempotency_record(replay),
        "audit-event.schema.json": serialize_audit_event(audit),
    }
    for schema_name, document in documents.items():
        schema_contracts[schema_name].validate(document)


@pytest.mark.parametrize(
    ("schema_name", "status_field", "status", "required_field"),
    [
        ("operation.schema.json", "status", "SUCCEEDED", "completed_at"),
        ("outbox-event.schema.json", "state", "CLAIMED", "claimed_until"),
        ("inbox-message.schema.json", "state", "PROCESSED", "processed_at"),
        (
            "idempotency-record.schema.json",
            "state",
            "COMPLETED",
            "response_resource_ref",
        ),
    ],
)
def test_schema_rejects_missing_state_required_fields(
    schema_contracts,
    schema_name,
    status_field,
    status,
    required_field,
):
    workspace_id = uuid.uuid4()
    operation = create_contract_operation(workspace_id)
    event = DomainEvent.objects.get(workspace_id=workspace_id)
    outbox = OutboxEvent.objects.get(workspace_id=workspace_id)
    replay = IdempotencyRecord.objects.get(workspace_id=workspace_id)
    inbox = InboxMessage.objects.create(
        workspace_id=workspace_id,
        consumer_id="curve-negative-contract-consumer",
        event_id=event.id,
    )
    documents = {
        "operation.schema.json": serialize_operation(operation),
        "outbox-event.schema.json": serialize_outbox_event(outbox),
        "inbox-message.schema.json": serialize_inbox_message(inbox),
        "idempotency-record.schema.json": serialize_idempotency_record(replay),
    }
    invalid = {**documents[schema_name], status_field: status}
    invalid.pop(required_field, None)

    with pytest.raises(ValidationError):
        schema_contracts[schema_name].validate(invalid)
