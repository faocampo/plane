# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import importlib
import uuid

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, migrations, models, transaction
from django.utils import timezone

from plane.curve.models import (
    DataClassification,
    ImmutableRecordError,
    PolicyDecision,
    PolicyEffect,
    ProviderCapability,
    ProviderCapabilityRisk,
    ProviderConnection,
    ProviderConnectionStatus,
    ProviderEnvironment,
    ProviderType,
)


pytestmark = [pytest.mark.unit, pytest.mark.django_db]

ACTOR = {"actor_type": "HUMAN", "actor_id": "federico"}
SERVICE_ACTOR = {"actor_type": "SERVICE", "actor_id": "curve-api"}
DIGEST = f"sha256:{'a' * 64}"
OTHER_DIGEST = f"sha256:{'b' * 64}"


def resource_ref(resource_type, resource_id=None, resource_version=1):
    return {
        "resource_type": resource_type,
        "resource_id": str(resource_id or uuid.uuid4()),
        "resource_version": resource_version,
    }


def connection_values(workspace_id=None, **overrides):
    values = {
        "workspace_id": workspace_id or uuid.uuid4(),
        "provider_type": ProviderType.FAKE_LOCAL,
        "adapter_key": "curve.fake-local",
        "adapter_version": "1.0.0",
        "environment": ProviderEnvironment.LOCAL,
        "display_name": "Synthetic local provider",
        "configuration_digest": DIGEST,
        "allowed_classifications": [DataClassification.INTERNAL],
        "created_by": ACTOR,
        "updated_by": ACTOR,
    }
    values.update(overrides)
    return values


def capability_values(provider_connection, **overrides):
    now = timezone.now()
    values = {
        "workspace_id": provider_connection.workspace_id,
        "connection": provider_connection,
        "connection_version": provider_connection.aggregate_version + 1,
        "capability_version": 1,
        "provider_type": provider_connection.provider_type,
        "adapter_key": provider_connection.adapter_key,
        "adapter_version": provider_connection.adapter_version,
        "protocol_versions": ["curve.fake-local/v1"],
        "capabilities": [
            {
                "name": "synthetic.status.read",
                "risk": ProviderCapabilityRisk.READ,
                "enabled": True,
            }
        ],
        "allowed_classifications": [DataClassification.INTERNAL],
        "observed_at": now,
        "validated_at": now,
    }
    values.update(overrides)
    return values


def policy_decision_values(policy_version, **overrides):
    now = timezone.now()
    values = {
        "workspace_id": uuid.uuid4(),
        "sequence": 1,
        "action": "CURVE.PROVIDER_CONNECTION.REGISTER",
        "resource_type": "WORKSPACE",
        "resource_id": uuid.uuid4(),
        "resource_version": 1,
        "subject": ACTOR,
        "effective_principal": ACTOR,
        "effect": PolicyEffect.ALLOW,
        "reason_codes": ["POLICY_ALLOWED"],
        "policy_version": policy_version,
        "policy_manifest_digest": DIGEST,
        "input_digest": OTHER_DIGEST,
        "normalized_classification": DataClassification.INTERNAL,
        "permitted_projection": ["WORKSPACE_ID"],
        "correlation_id": "curve-provider-policy-test",
        "evaluated_at": now,
        "recorded_at": now,
        "recorded_by": SERVICE_ACTOR,
    }
    values.update(overrides)
    return values


def assert_constraint_rejects(create_or_update):
    with pytest.raises(IntegrityError), transaction.atomic():
        create_or_update()


def activate_connection(provider_connection, provider_capability):
    now = timezone.now()
    provider_connection.aggregate_version += 1
    provider_connection.current_capability = provider_capability
    provider_connection.status = ProviderConnectionStatus.ACTIVE
    provider_connection.validated_at = now
    provider_connection.validation_result_ref = resource_ref("OPERATION", resource_version=2)
    provider_connection.last_reconciled_at = now
    provider_connection.next_reconcile_at = now + timezone.timedelta(seconds=900)
    provider_connection.save()
    return provider_connection


def test_provider_connection_repository_requires_workspace_and_hides_foreign_ids():
    workspace_id = uuid.uuid4()
    provider_connection = ProviderConnection.objects.create(**connection_values(workspace_id=workspace_id))

    assert (
        ProviderConnection.objects.find_by_id(
            workspace_id=workspace_id,
            record_id=provider_connection.id,
        )
        == provider_connection
    )
    assert (
        ProviderConnection.objects.find_by_id(
            workspace_id=uuid.uuid4(),
            record_id=provider_connection.id,
        )
        is None
    )
    assert ProviderConnection.objects.find_by_id(workspace_id=workspace_id, record_id=uuid.uuid4()) is None
    with pytest.raises(ValueError, match="workspace_id is required"):
        ProviderConnection.objects.find_by_id(workspace_id=None, record_id=provider_connection.id)


def test_provider_connection_identity_is_unique_inside_workspace_only():
    workspace_id = uuid.uuid4()
    ProviderConnection.objects.create(**connection_values(workspace_id=workspace_id))

    assert_constraint_rejects(lambda: ProviderConnection.objects.create(**connection_values(workspace_id=workspace_id)))
    ProviderConnection.objects.create(**connection_values(workspace_id=uuid.uuid4()))


@pytest.mark.parametrize(
    "overrides",
    [
        {"configuration_digest": "raw-digest"},
        {"provider_type": ProviderType.ONYX},
        {"environment": ProviderEnvironment.STAGING},
        {"adapter_key": "dynamic.provider"},
        {"configuration_ref": resource_ref("OBJECT")},
        {"secret_reference": "secret/ref"},
        {"allowed_classifications": [DataClassification.CONFIDENTIAL]},
    ],
)
def test_provider_connection_fake_local_database_constraints_fail_closed(overrides):
    assert_constraint_rejects(lambda: ProviderConnection.objects.create(**connection_values(**overrides)))


@pytest.mark.parametrize(
    ("status", "updates"),
    [
        (ProviderConnectionStatus.ACTIVE, {}),
        (ProviderConnectionStatus.DEGRADED, {}),
        (
            ProviderConnectionStatus.DISABLED,
            {"next_reconcile_at": timezone.now() + timezone.timedelta(seconds=900)},
        ),
        (
            ProviderConnectionStatus.REVOKED,
            {"next_reconcile_at": timezone.now() + timezone.timedelta(seconds=900)},
        ),
    ],
)
def test_provider_connection_state_required_fields_fail_closed(status, updates):
    provider_connection = ProviderConnection.objects.create(**connection_values())
    assert_constraint_rejects(
        lambda: ProviderConnection.objects.filter(id=provider_connection.id).update(status=status, **updates)
    )


def test_provider_capability_is_append_only_and_workspace_scoped():
    provider_connection = ProviderConnection.objects.create(**connection_values())
    capability = ProviderCapability.objects.create(**capability_values(provider_connection))

    assert (
        ProviderCapability.objects.find_by_id(
            workspace_id=provider_connection.workspace_id,
            record_id=capability.id,
        )
        == capability
    )
    assert ProviderCapability.objects.find_by_id(workspace_id=uuid.uuid4(), record_id=capability.id) is None

    with pytest.raises(ImmutableRecordError, match="append-only"):
        capability.save()
    with pytest.raises(ImmutableRecordError, match="append-only"):
        ProviderCapability.objects.filter(id=capability.id).update(capability_version=2)
    with pytest.raises(ImmutableRecordError, match="append-only"):
        capability.delete()


def test_provider_querysets_reject_bulk_workspace_reference_bypasses():
    connection = ProviderConnection.objects.create(**connection_values())
    capability = ProviderCapability.objects.create(**capability_values(connection))

    with pytest.raises(ImmutableRecordError, match="bulk creation"):
        ProviderConnection.objects.bulk_create([ProviderConnection(**connection_values())])
    with pytest.raises(ImmutableRecordError, match="locked instance"):
        ProviderConnection.objects.bulk_update([connection], ["workspace_id"])
    with pytest.raises(ImmutableRecordError, match="locked instance"):
        ProviderConnection.objects.filter(id=connection.id).update(current_capability_id=capability.id)
    with pytest.raises(ImmutableRecordError, match="workspace-scoped repository"):
        ProviderCapability.objects.bulk_create([ProviderCapability(**capability_values(connection))])
    with pytest.raises(ImmutableRecordError, match="append-only"):
        ProviderCapability.objects.bulk_update([capability], ["capability_version"])
    with pytest.raises(ImmutableRecordError, match="append-only"):
        ProviderCapability.objects.filter(id=capability.id).delete()


def test_provider_capability_version_is_unique_per_workspace_connection():
    provider_connection = ProviderConnection.objects.create(**connection_values())
    ProviderCapability.objects.create(**capability_values(provider_connection))

    assert_constraint_rejects(lambda: ProviderCapability.objects.create(**capability_values(provider_connection)))


def test_provider_capability_rejects_cross_workspace_or_adapter_mismatch():
    provider_connection = ProviderConnection.objects.create(**connection_values())

    with pytest.raises(ValidationError, match="connection workspace"):
        ProviderCapability.objects.create(**capability_values(provider_connection, workspace_id=uuid.uuid4()))
    with pytest.raises(ValidationError, match="adapter coordinates"):
        ProviderCapability.objects.create(**capability_values(provider_connection, adapter_version="2.0.0"))


@pytest.mark.parametrize(
    "capabilities",
    [
        [],
        [{"name": "synthetic.write", "risk": ProviderCapabilityRisk.WORKFLOW_WRITE, "enabled": True}],
        [{"name": "synthetic.read", "risk": ProviderCapabilityRisk.READ, "enabled": "yes"}],
        [
            {
                "name": "synthetic.read",
                "risk": ProviderCapabilityRisk.READ,
                "enabled": True,
                "unknown": True,
            }
        ],
    ],
)
def test_provider_capability_document_validation_fails_closed(capabilities):
    provider_connection = ProviderConnection.objects.create(**connection_values())
    with pytest.raises(ValidationError):
        ProviderCapability.objects.create(**capability_values(provider_connection, capabilities=capabilities))


def test_current_capability_must_belong_to_same_workspace_scoped_connection():
    provider_connection = ProviderConnection.objects.create(**connection_values())
    foreign_connection = ProviderConnection.objects.create(**connection_values(workspace_id=uuid.uuid4()))
    foreign_capability = ProviderCapability.objects.create(**capability_values(foreign_connection))

    provider_connection.current_capability = foreign_capability
    with pytest.raises(ValidationError, match="workspace-scoped connection"):
        provider_connection.save()


def test_active_connection_accepts_complete_capability_evidence():
    provider_connection = ProviderConnection.objects.create(**connection_values())
    provider_capability = ProviderCapability.objects.create(**capability_values(provider_connection))

    activate_connection(provider_connection, provider_capability)
    provider_connection.refresh_from_db()

    assert provider_connection.status == ProviderConnectionStatus.ACTIVE
    assert provider_connection.current_capability_id == provider_capability.id
    assert provider_connection.next_reconcile_at is not None


def test_policy_decision_constraint_accepts_versions_one_and_two_only():
    version_one = PolicyDecision.objects.create(**policy_decision_values(policy_version=1))
    version_two = PolicyDecision.objects.create(**policy_decision_values(policy_version=2))

    assert version_one.policy_version == 1
    assert version_two.policy_version == 2
    assert_constraint_rejects(lambda: PolicyDecision.objects.create(**policy_decision_values(policy_version=3)))


def test_provider_migration_has_exact_predecessor_models_and_policy_window():
    migration_module = importlib.import_module("plane.curve.migrations.0005_providerconnection_providercapability")
    migration = migration_module.Migration

    assert migration.dependencies == [("curve", "0004_policydecision_recorded_at_default")]
    created_models = {
        operation.name for operation in migration.operations if isinstance(operation, migrations.CreateModel)
    }
    assert created_models == {"ProviderConnection", "ProviderCapability"}

    removed_identity = [
        operation
        for operation in migration.operations
        if isinstance(operation, migrations.RemoveConstraint)
        and operation.model_name == "policydecision"
        and operation.name == "curve_policy_identity_ck"
    ]
    added_identity = [
        operation
        for operation in migration.operations
        if isinstance(operation, migrations.AddConstraint)
        and operation.model_name == "policydecision"
        and operation.constraint.name == "curve_policy_identity_ck"
    ]
    assert len(removed_identity) == len(added_identity) == 1
    assert added_identity[0].constraint.condition == models.Q(
        policy_key="CURVE_CORE_POLICY",
        policy_version__in=[1, 2],
    )
