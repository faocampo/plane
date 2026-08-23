# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource

from plane.curve.models import (
    AuditEvent,
    DomainEvent,
    IdempotencyRecord,
    InboxMessage,
    OutboxEvent,
    PolicyDecision,
)
from plane.curve.policy_services import start_foundation_probe
from plane.curve.serialization import (
    serialize_audit_event,
    serialize_domain_event,
    serialize_idempotency_record,
    serialize_inbox_message,
    serialize_operation,
    serialize_operation_summary,
    serialize_outbox_event,
    serialize_policy_decision,
    serialize_sse_event,
)
from plane.db.models import User, Workspace, WorkspaceMember


pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]

SCHEMA_DIGESTS = {
    "audit-event.schema.json": "36fcb1f4023cc26619f5e20bf78670e83b2bf4bb48112fdaca1481daa84157f1",
    "common.schema.json": "b00c8c420f7e78f20adea2b3a097d74a4e97e73c0f2cc71ad9ac5c4933e31583",
    "core-policy-manifest.schema.json": "bdc10bd52e9189a6d1994248bb791b07c5011eeb1c3ffc668ba44bf8d523f46f",
    "event-envelope.schema.json": "de28a9654520b2f27d307b246a48f4d6b847e924d53e1d95513c47c29c5166ed",
    "idempotency-record.schema.json": "9c40ad05af41e89d1fa8890550f03591c106070337c2cf5ff091aedd74210801",
    "inbox-message.schema.json": "e1b06e1cb5ea157e2249014229dceac3c1ea0f07bda393a2832ba886dcd84527",
    "operation-event-v1.schema.json": "fdba17d38e5e930b9abca6ceae47a7dd7b33c4bdd88b5e740e684c89548315d0",
    "operation-event-v2.schema.json": "3d3b67fa2939b93517f061d852f4562087db87728b66893dd05823b44881fa73",
    "operation-summary.schema.json": "3a237b4f66a90b92545446989da0678b0e82f0f19aa2a9a4bf159740dfa80bb1",
    "operation.schema.json": "887c0d1e9b667f61db66834efdcafc72f581e71641a66e0bfa4006661bbb9aff",
    "observability-binding.schema.json": "0dccea5ef9c8897fa5c4d66d3e9c586cf63531943ee423e474d071dad76c4d85",
    "outbox-event.schema.json": "fd5db47b56f359eb7333e06c0c7ec1f9f90b00a6b4b07f791f10d0177cc79711",
    "policy-decision.schema.json": "5faa121136c59420da7fb1582985c3d445b6486e1e52a77c8d6ff853634f4bd8",
    "policy-evaluation.schema.json": "75622a18bbbdaa69795beee16254106f12aab2aa150e1619f237d3bf67d724f8",
    "sse-event.schema.json": "58270829c666d40307c168c7e7852e3b23e5a37548ad85a10948bc9d4d548c80",
    "telemetry-manifest.schema.json": "b25c1d758fa995370a01996b811770bdbd335374bda7ea88a790359d4c126942",
    "temporal-orchestration.schema.json": "9e5d72eea70d542dad9d15f372f0b90f5e68a0654735c3a7d2cd900df8b7fb47",
}


@pytest.fixture(autouse=True)
def _curve_policy_settings(settings):
    settings.CURVE_ENABLED = True
    settings.CURVE_ENABLED_WORKSPACE_SLUGS = frozenset({"alpha"})
    settings.CURVE_ENVIRONMENT = "LOCAL"
    settings.CURVE_POLICY_RECORDER_ACTOR_ID = "curve-api-test"


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
    user = User.objects.create(
        email="curve-contract@example.com",
        username="curve-contract@example.com",
    )
    workspace = Workspace.objects.create(
        id=workspace_id,
        name="Alpha",
        slug="alpha",
        owner=user,
    )
    WorkspaceMember.objects.create(
        workspace=workspace,
        member=user,
        role=20,
        is_active=True,
    )
    return start_foundation_probe(
        request=SimpleNamespace(user=user),
        workspace_slug="alpha",
        raw_idempotency_key="contract-test-key",
        canonical_request=b'{"command":"CREATE_FOUNDATION_PROBE"}',
        command_type="CREATE_FOUNDATION_PROBE",
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
    decision = PolicyDecision.objects.get(workspace_id=workspace_id)
    inbox = InboxMessage.objects.create(
        workspace_id=workspace_id,
        consumer_id="curve-contract-consumer",
        event_id=event.id,
    )

    documents = {
        "operation.schema.json": serialize_operation(operation),
        "operation-summary.schema.json": serialize_operation_summary(operation),
        "sse-event.schema.json": serialize_sse_event(event),
        "event-envelope.schema.json": serialize_domain_event(event),
        event.payload_schema.rsplit("/", 1)[-1]: event.payload,
        "outbox-event.schema.json": serialize_outbox_event(outbox),
        "inbox-message.schema.json": serialize_inbox_message(inbox),
        "idempotency-record.schema.json": serialize_idempotency_record(replay),
        "audit-event.schema.json": serialize_audit_event(audit),
        "policy-decision.schema.json": serialize_policy_decision(decision),
    }
    for schema_name, document in documents.items():
        schema_contracts[schema_name].validate(document)


def test_telemetry_manifest_matches_the_pinned_schema(schema_contracts):
    contract_directory = Path(__file__).parents[1] / "contracts"
    manifest = json.loads((contract_directory / "observability" / "m0-s5-telemetry-v1.json").read_text())

    schema_contracts["telemetry-manifest.schema.json"].validate(manifest)


def test_local_observability_binding_rejects_external_alert_delivery(schema_contracts):
    contract_directory = Path(__file__).parents[1] / "contracts"
    binding = json.loads((contract_directory / "observability" / "obs-bind-001-local-v1.json").read_text())
    invalid = json.loads(
        (
            contract_directory
            / "schemas"
            / "semantic-fixtures"
            / "observability-binding-external-delivery.invalid.json"
        ).read_text()
    )
    validator = schema_contracts["observability-binding.schema.json"]

    validator.validate(binding)
    with pytest.raises(ValidationError):
        validator.validate(invalid)


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
