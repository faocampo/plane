# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import json
import uuid
from datetime import datetime, timezone
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
    serialize_provider_capability,
    serialize_provider_connection,
    serialize_sse_event,
)
from plane.db.models import User, Workspace, WorkspaceMember


pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]

SCHEMA_DIGESTS = {
    "audit-event.schema.json": "36fcb1f4023cc26619f5e20bf78670e83b2bf4bb48112fdaca1481daa84157f1",
    "common.schema.json": "b00c8c420f7e78f20adea2b3a097d74a4e97e73c0f2cc71ad9ac5c4933e31583",
    "core-policy-manifest-v2.schema.json": "05e77c1f3db002cfc4d26c743d031c71661cf7106f8ac9c27b14a5aacaff38b9",
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
    "policy-decision.schema.json": "6463d429124ee71df9ee57885dd332b703f86e35bbf65db161c3327723650799",
    "policy-evaluation.schema.json": "75622a18bbbdaa69795beee16254106f12aab2aa150e1619f237d3bf67d724f8",
    "provider-capability.schema.json": "30d1388ed0367c194d05c88247d18563d2e2813bb80bdbe9a19605d8fd1228e7",
    "provider-connection-event-v1.schema.json": "8270ac5bb8cfb7474bbb3fb31f91be3787412dcea0dc58e1bf9ed427c3a99d43",
    "provider-connection.schema.json": "8485a48282cfe14f95bd4a3e64eb5de4353f6b6d22fab73c985c4763e1a5cdde",
    "provider-reconciliation-event-v1.schema.json": "d2b32ffba961eba6faa4b17d2aa718ac8c98c1ea67ec53cc4cacf54436569147",
    "provider-registry-manifest.schema.json": "df09e3a13953ce37ebd2555ecc53bdd133baf172d575a9ae95609ffcba4b3729",
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


def test_provider_contract_manifests_match_the_pinned_schemas(schema_contracts):
    contract_directory = Path(__file__).parents[1] / "contracts"
    policy_manifest = json.loads((contract_directory / "policy" / "core-policy-v2.json").read_text())
    registry_manifest = json.loads((contract_directory / "providers" / "m0-s9a-provider-registry-v1.json").read_text())

    schema_contracts["core-policy-manifest-v2.schema.json"].validate(policy_manifest)
    schema_contracts["provider-registry-manifest.schema.json"].validate(registry_manifest)


@pytest.mark.parametrize(
    ("schema_name", "valid_name", "invalid_name"),
    [
        (
            "provider-connection.schema.json",
            "provider-connection.valid.json",
            "provider-connection.invalid.json",
        ),
        (
            "provider-capability.schema.json",
            "provider-capability.valid.json",
            "provider-capability.invalid.json",
        ),
        (
            "provider-registry-manifest.schema.json",
            "provider-registry-manifest.valid.json",
            "provider-registry-manifest.invalid.json",
        ),
        (
            "provider-connection-event-v1.schema.json",
            "provider-connection-event-v1.valid.json",
            "provider-connection-event-v1.invalid.json",
        ),
        (
            "provider-reconciliation-event-v1.schema.json",
            "provider-reconciliation-event-v1.valid.json",
            "provider-reconciliation-event-v1.invalid.json",
        ),
        (
            "core-policy-manifest-v2.schema.json",
            "core-policy-manifest-v2.valid.json",
            "core-policy-manifest-v2.invalid.json",
        ),
    ],
)
def test_provider_and_policy_examples_enforce_the_pinned_schemas(
    schema_contracts,
    schema_name,
    valid_name,
    invalid_name,
):
    example_directory = Path(__file__).parents[1] / "contracts" / "schemas" / "examples"
    valid = json.loads((example_directory / valid_name).read_text())
    invalid = json.loads((example_directory / invalid_name).read_text())
    validator = schema_contracts[schema_name]

    validator.validate(valid)
    with pytest.raises(ValidationError):
        validator.validate(invalid)


@pytest.mark.parametrize(
    ("schema_name", "valid_name", "invalid_name"),
    [
        (
            "policy-decision.schema.json",
            "policy-decision-provider-registration-v2.valid.json",
            "policy-decision-provider-registration-v3.invalid.json",
        ),
        (
            "provider-connection.schema.json",
            "provider-connection-active.valid.json",
            "provider-connection-active-null.invalid.json",
        ),
    ],
)
def test_provider_semantic_fixtures_enforce_version_and_lifecycle_rules(
    schema_contracts,
    schema_name,
    valid_name,
    invalid_name,
):
    fixture_directory = Path(__file__).parents[1] / "contracts" / "schemas" / "semantic-fixtures"
    valid = json.loads((fixture_directory / valid_name).read_text())
    invalid = json.loads((fixture_directory / invalid_name).read_text())
    validator = schema_contracts[schema_name]

    validator.validate(valid)
    with pytest.raises(ValidationError):
        validator.validate(invalid)


def test_revoked_provider_connection_rejects_a_next_reconciliation(schema_contracts):
    fixture_path = (
        Path(__file__).parents[1]
        / "contracts"
        / "schemas"
        / "semantic-fixtures"
        / "provider-connection-revoked-next.invalid.json"
    )

    with pytest.raises(ValidationError):
        schema_contracts["provider-connection.schema.json"].validate(json.loads(fixture_path.read_text()))


def test_registered_provider_event_fixture_requires_configuration_digest(schema_contracts):
    fixture_path = (
        Path(__file__).parents[1]
        / "contracts"
        / "schemas"
        / "semantic-fixtures"
        / "provider-connection-event-registered.valid.json"
    )
    document = json.loads(fixture_path.read_text())
    schema_contracts["provider-connection-event-v1.schema.json"].validate(document)
    assert document["configuration_digest"].startswith("sha256:")


def test_provider_safe_projections_validate_and_omit_absent_connection_references(schema_contracts):
    workspace_id = uuid.uuid4()
    connection_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    observed_at = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    validated_at = datetime(2026, 8, 22, 12, 0, 1, tzinfo=timezone.utc)
    next_reconcile_at = datetime(2026, 8, 22, 12, 15, 1, tzinfo=timezone.utc)
    capability = SimpleNamespace(
        schema_version="2.0",
        id=capability_id,
        workspace_id=workspace_id,
        connection_id=connection_id,
        connection_version=2,
        capability_version=1,
        provider_type="FAKE_LOCAL",
        adapter_key="curve.fake-local",
        adapter_version="1.0.0",
        protocol_versions=["curve.fake-local/v1"],
        capabilities=[{"name": "synthetic.status.read", "risk": "READ", "enabled": True}],
        allowed_classifications=["INTERNAL"],
        observed_at=observed_at,
        validated_at=validated_at,
        expires_at=None,
    )
    connection = SimpleNamespace(
        schema_version="2.0",
        id=connection_id,
        workspace_id=workspace_id,
        aggregate_version=2,
        provider_type="FAKE_LOCAL",
        adapter_key="curve.fake-local",
        adapter_version="1.0.0",
        environment="LOCAL",
        display_name="Synthetic local provider",
        external_tenant_ref=None,
        configuration_ref=None,
        configuration_digest="sha256:" + "b" * 64,
        secret_reference=None,
        current_capability_id=capability_id,
        current_capability=capability,
        allowed_classifications=["INTERNAL"],
        status="ACTIVE",
        validated_at=validated_at,
        validation_result_ref={
            "resource_type": "OPERATION",
            "resource_id": str(uuid.uuid4()),
            "resource_version": 2,
        },
        last_reconciled_at=validated_at,
        next_reconcile_at=next_reconcile_at,
        last_error=None,
        created_at=observed_at,
        created_by={"actor_type": "HUMAN", "actor_id": "platform-admin-1"},
        updated_at=validated_at,
        updated_by={"actor_type": "SERVICE", "actor_id": "provider-registry"},
    )

    connection_document = serialize_provider_connection(connection)
    capability_document = serialize_provider_capability(capability)

    schema_contracts["provider-connection.schema.json"].validate(connection_document)
    schema_contracts["provider-capability.schema.json"].validate(capability_document)
    assert connection_document["capability_document_ref"] == {
        "resource_type": "PROVIDER_CAPABILITY",
        "resource_id": str(capability_id),
        "resource_version": 1,
    }
    assert {
        "external_tenant_ref",
        "configuration_ref",
        "secret_reference",
        "last_error",
    }.isdisjoint(connection_document)
    assert "expires_at" in capability_document
    assert capability_document["expires_at"] is None


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
