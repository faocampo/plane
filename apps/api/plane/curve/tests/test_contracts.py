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
    "audit-event.schema.json": "26f8e2d2d6f53b689710f826400c9e1ef559cee7d536ff48bea25a6567fb54fd",
    "common.schema.json": "54b32643ee06d5458934c033a890b639d6c8f8a75346743ba8ef054320bfc3de",
    "core-policy-manifest-v2.schema.json": "a53c68d10a84de64885363e7e236c88d0f07faf3d253678986e6ccd3ebd90f5d",
    "core-policy-manifest.schema.json": "16c0b832107b830c3a1628a49798598dd7d5e316639a46be9b1bc7538eb63d80",
    "event-envelope.schema.json": "80314014208963a0b0c03c11de3ecc9a8c2ba97dc116a6b0e5ac115df1d89fa8",
    "gate-assignment.schema.json": "5b614728e2666698e188eaf325f47f000befa056cc514bd743e12e4807070e97",
    "idempotency-record.schema.json": "96be790daccbf72023c82abd820ed5706899a5d8563790038f9823019853e9d8",
    "inbox-message.schema.json": "6281e36861ae48fa39b0bdccf29b3fe26e46a1a31e2a182400bcc60d2bf85b1f",
    "initiative-create-request.schema.json": "a19b13b4aa44bc10cf997c0b280705a38f11d0e69c89d497099344a9d309cacd",
    "initiative-event-v1.schema.json": "762b6f12f6f4b88671e7fb8b1c97cee997a836c8174b5f56f96bc0482e64d8c3",
    "initiative-transition-request.schema.json": "a73aaf0ba546b45da08f9b767263b9ef91329448d3037d5958950adf19bca496",
    "initiative-update-request.schema.json": "ecaed1c01f41d77236402620be24f51446ff9df29d8b3d4c937292783fa2dace",
    "initiative.schema.json": "433a464415669ffb640f15665dc068e94837e0aeefa4928bbaaa1910b84f52d5",
    "operation-event-v1.schema.json": "b71330d5989bb27e62ae9a11ad9d4a1ef3a284f76d2c7ecbaf82c09eb2f8e668",
    "operation-event-v2.schema.json": "23b801c35ad96d8132489b2cf996c24cb892c367e1e06b75b44ec0d3830a8341",
    "operation-summary.schema.json": "6e33c190d6a17633b446485cd1f872ce5b051ddf049e5f615eb37927170ad50b",
    "operation.schema.json": "7c97d0208134f72ae012d844fd69090f9634ae3fb0a4eb2d018b9f85980c48c6",
    "observability-binding.schema.json": "6ce1ba05369b0c8670776bdd27186a7fe25892518bdb2b70ee2db791eb010044",
    "outbox-event.schema.json": "a2aac7224830a70e8fe0b9188f25edea9f59a91315a4f79bcf1fd2cb585a8cb0",
    "policy-decision.schema.json": "2bcedf0aa19d6a84a7b8af45db9e64136da18be883c2b9cc8115ea5919650cad",
    "policy-evaluation.schema.json": "826610d5af15c28b265aa5882b50c23cf94874158a739473c4ac9937219374c7",
    "product-core-decision.schema.json": "119ed1ccddf121437a8d3a835befc9c20e6068b3b256cd4db2ae32fbc2ad5adb",
    "product-create-request.schema.json": "9432ac7d2096d20a0ab48c1ad0d81a2a9d892c0f8285c6b80039f56633a92f3c",
    "product-event-v1.schema.json": "242abb8745dfccf25bd1812fda965a97e472d9dcc6c51417a62d3e527d1c520d",
    "product-policy-manifest.schema.json": "6a5684d00b1573f9a67bb4b6491fcdd6eccb79f1db6d757923e09affba12160e",
    "product-reassign-owner-request.schema.json": "25f33f8f0c2341789ef13aa97d15784b8066b4dd40654986316a8acd53ff8749",
    "product-update-request.schema.json": "67e083d9c99d3cbf76e5eee403a07cc793cce0443e2d79937a7b2a350ad8865f",
    "product.schema.json": "ec4c08fe6c3ac71201ec80f7a5554f9c2161436a32687c5547c50735b1626a47",
    "provider-capability.schema.json": "586cdf823d73dff8b6999218c84c0d22c0a6163c5104ee9d7e4be305ca6cd5b3",
    "provider-connection-event-v1.schema.json": "0e537e74f38dca891ff1f9c5ee299c70853d1907a2f44821d3fdcaf4afbb0639",
    "provider-connection.schema.json": "a583c88673202aa00c773e45f2d604d201fa1ebde1cf1ad8028f9a9406ad72ea",
    "provider-reconciliation-event-v1.schema.json": "4717fdb93e1284514100bbf11f57463d4e34864f21bcc719986e87159d851ad1",
    "provider-registry-manifest.schema.json": "e3d00a8c9453a4a26e3f83e1c3ddbba3299afde9963d061439e58bba86356dac",
    "sse-event.schema.json": "edf29556d2933d23fb2362cad5b8844fe3db4ce903066dfa3c9aba7d84df7087",
    "telemetry-manifest.schema.json": "0eab64dc8ad956fa6b9eff291748f0713f45f7f8f649c0c4ebd0207174f41254",
    "temporal-orchestration.schema.json": "009c06c7499eda05f49e91de336a69a013b0a7776b4a54ed55779ac837707c7f",
}

M1_01B_SCHEMA_DIGESTS = {
    "initiative-create-request-v1.1.schema.json": "f4104a87c93c05491bb7980b85f42887bcc6fc9e4fc82e05d912bcb67faf9bcf",
    "initiative-update-request-v1.1.schema.json": "ac033e1e1b133968d22920a2da8d85b9fc19208a513ba3c6332dca771815e7cc",
    "initiative-v1.1.schema.json": "69d011127f796326c0eb08e8698002e99063fbc4d0a4830fa74ce36a5e7fc9b6",
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
    all_observed = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in schema_directory.glob("*.schema.json")
    }
    observed = {name: all_observed[name] for name in SCHEMA_DIGESTS}
    m1_01b_observed = {name: all_observed[name] for name in M1_01B_SCHEMA_DIGESTS}

    assert observed == SCHEMA_DIGESTS
    assert m1_01b_observed == M1_01B_SCHEMA_DIGESTS
    assert set(all_observed) == set(SCHEMA_DIGESTS) | set(M1_01B_SCHEMA_DIGESTS)


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
        (
            "product-core-decision.schema.json",
            "product-core-decision.valid.json",
            "product-core-decision.invalid.json",
        ),
        (
            "product-create-request.schema.json",
            "product-create-request.valid.json",
            "product-create-request.invalid.json",
        ),
        (
            "product-event-v1.schema.json",
            "product-event-v1.valid.json",
            "product-event-v1.invalid.json",
        ),
        (
            "product-policy-manifest.schema.json",
            "product-policy-manifest.valid.json",
            "product-policy-manifest.invalid.json",
        ),
        (
            "product-reassign-owner-request.schema.json",
            "product-reassign-owner-request.valid.json",
            "product-reassign-owner-request.invalid.json",
        ),
        (
            "product-update-request.schema.json",
            "product-update-request.valid.json",
            "product-update-request.invalid.json",
        ),
        (
            "product.schema.json",
            "product.valid.json",
            "product.invalid.json",
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
