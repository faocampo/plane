# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import uuid

import pytest

from plane.curve.models import (
    AuditEvent,
    AuditOutcome,
    DataClassification,
    DomainEvent,
    IdempotencyRecord,
    IdempotencyState,
    InboxMessage,
    InboxState,
    Operation,
    OperationStatus,
    OutboxEvent,
    OutboxState,
    PolicyDecision,
    ProviderCapability,
    ProviderConnection,
    ProviderConnectionStatus,
)
from plane.curve.policy_services import CurvePolicyDenied
from plane.curve.provider_services import (
    PROVIDER_LOCAL_CLAIM_LEASE,
    PROVIDER_LOCAL_CONSUMER_ID,
    PROVIDER_LOCAL_DESTINATION,
    InvalidProviderTransition,
    ProviderRegistryDisabled,
    disable_provider_connection,
    drain_local_provider_events,
    enable_provider_connection,
    reconcile_provider_connection,
    register_fake_local_provider_connection,
    revoke_provider_connection,
)
from plane.curve.providers.event_contracts import (
    PROVIDER_CONNECTION_EVENT_SCHEMA,
    ProviderEventContractError,
    validate_provider_event_payload,
)
from plane.curve.providers import STATIC_PROVIDER_REGISTRY
from plane.curve.providers.fake_local import FakeLocalAdapter, FakeLocalScenario
from plane.curve.providers.registry import ProviderRegistryError, ProviderRegistryErrorCode
from plane.curve.providers.types import NormalizedProviderError, ProviderErrorCode
from plane.curve.services import (
    IdempotencyConflict,
    OptimisticConcurrencyError,
    claim_due_outbox,
    idempotency_key_digest,
    recover_expired_outbox_claims,
)
from plane.db.models import User, Workspace, WorkspaceMember
import plane.curve.provider_services as provider_services


pytestmark = [pytest.mark.unit, pytest.mark.django_db(transaction=True)]

FIXED_ACCEPTED_AT = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
ACTOR = {"actor_type": "SERVICE", "actor_id": "provider-test"}


@pytest.fixture(autouse=True)
def _provider_registry_settings(settings):
    settings.CURVE_ENABLED = True
    settings.CURVE_PROVIDER_REGISTRY_ENABLED = True
    settings.CURVE_ENABLED_WORKSPACE_SLUGS = frozenset({"alpha", "beta"})
    settings.CURVE_ENVIRONMENT = "LOCAL"
    settings.CURVE_POLICY_RECORDER_ACTOR_ID = "curve-api-test"


def _user(email: str) -> User:
    return User.objects.create(email=email, username=email)


def _workspace(
    *,
    slug: str = "alpha",
    role: int = 20,
    active: bool = True,
    email: str | None = None,
) -> tuple[Workspace, User]:
    user = _user(email or f"{slug}-provider-owner@example.com")
    workspace = Workspace.objects.create(
        name=slug.title(),
        slug=slug,
        owner=user,
    )
    WorkspaceMember.objects.create(
        workspace=workspace,
        member=user,
        role=role,
        is_active=active,
    )
    return workspace, user


def _request(user: User):
    return SimpleNamespace(
        user=user,
        roles=["PLATFORM_ADMINISTRATOR"],
        target_id="curve.untrusted@9.9.9",
    )


def _register(
    *,
    workspace_slug: str,
    user: User,
    raw_key: str = "provider-registration-key",
    display_name: str = "Synthetic local provider",
):
    return register_fake_local_provider_connection(
        request=_request(user),
        workspace_slug=workspace_slug,
        display_name=display_name,
        raw_idempotency_key=raw_key,
    )


class _FixedAdapterRegistry:
    def __init__(self, adapter) -> None:
        self._adapter = adapter

    def registration_for(self, *args, **kwargs):
        return STATIC_PROVIDER_REGISTRY.registration_for(*args, **kwargs)

    def resolve(self, *args, **kwargs):
        STATIC_PROVIDER_REGISTRY.registration_for(*args, **kwargs)
        return self._adapter

    def validate_observation(self, observation) -> None:
        STATIC_PROVIDER_REGISTRY.validate_observation(observation)


class _BrokenRegistry(_FixedAdapterRegistry):
    def resolve(self, *args, **kwargs):
        raise ProviderRegistryError(ProviderRegistryErrorCode.UNKNOWN_ADAPTER)


def _use_adapter(monkeypatch, *scenarios: FakeLocalScenario) -> FakeLocalAdapter:
    adapter = FakeLocalAdapter(tuple(scenarios))
    monkeypatch.setattr(
        provider_services,
        "STATIC_PROVIDER_REGISTRY",
        _FixedAdapterRegistry(adapter),
    )
    return adapter


def _reconcile(
    *,
    user: User,
    connection: ProviderConnection,
    expected_version: int,
    raw_key: str,
    accepted_at=FIXED_ACCEPTED_AT,
):
    return reconcile_provider_connection(
        request=_request(user),
        workspace_slug="alpha",
        connection_id=connection.id,
        expected_version=expected_version,
        raw_idempotency_key=raw_key,
        accepted_at_factory=lambda: accepted_at,
    )


def _local_event(
    *,
    workspace_id: uuid.UUID,
    event_type: str = "curve.provider_connection.registered",
) -> tuple[DomainEvent, OutboxEvent]:
    aggregate_id = uuid.uuid4()
    event = DomainEvent.objects.create(
        workspace_id=workspace_id,
        event_type=event_type,
        aggregate_type="PROVIDER_CONNECTION",
        aggregate_id=aggregate_id,
        aggregate_version=1,
        sequence=1,
        actor=ACTOR,
        effective_principal=ACTOR,
        correlation_id=f"provider-event-{aggregate_id}",
        classification=DataClassification.INTERNAL,
        payload_schema=PROVIDER_CONNECTION_EVENT_SCHEMA,
        payload={
            "workspace_id": str(workspace_id),
            "connection_id": str(aggregate_id),
            "connection_version": 1,
            "status": ProviderConnectionStatus.PENDING_VALIDATION,
            "configuration_digest": f"sha256:{'c' * 64}",
        },
    )
    outbox = OutboxEvent.objects.create(
        workspace_id=workspace_id,
        event_id=event.id,
        destination=PROVIDER_LOCAL_DESTINATION,
    )
    return event, outbox


def test_registration_is_atomic_delivered_and_replays_the_original_resource_ref():
    workspace, user = _workspace()

    created = _register(workspace_slug=workspace.slug, user=user)

    assert created.replayed is False
    assert created.response_status == 201
    assert created.response_resource_ref == {
        "resource_type": "PROVIDER_CONNECTION",
        "resource_id": str(created.connection.id),
        "resource_version": 1,
    }
    assert ProviderConnection.objects.filter(workspace_id=workspace.id).count() == 1
    assert (
        DomainEvent.objects.filter(
            workspace_id=workspace.id,
            event_type="curve.provider_connection.registered",
        ).count()
        == 1
    )
    outbox = OutboxEvent.objects.get(
        workspace_id=workspace.id,
        destination=PROVIDER_LOCAL_DESTINATION,
    )
    inbox = InboxMessage.objects.get(
        workspace_id=workspace.id,
        consumer_id=PROVIDER_LOCAL_CONSUMER_ID,
        event_id=outbox.event_id,
    )
    assert outbox.state == OutboxState.DELIVERED
    assert outbox.attempt_count == 1
    assert inbox.state == InboxState.PROCESSED
    record = IdempotencyRecord.objects.get(workspace_id=workspace.id)
    assert record.state == IdempotencyState.COMPLETED
    assert record.key_digest == idempotency_key_digest("provider-registration-key")
    assert "provider-registration-key" not in str(record.__dict__)
    assert (
        AuditEvent.objects.filter(
            workspace_id=workspace.id,
            action="CURVE.PROVIDER_CONNECTION.REGISTER",
            outcome=AuditOutcome.SUCCEEDED,
        ).count()
        == 1
    )

    replayed = _register(workspace_slug=workspace.slug, user=user)

    assert replayed.replayed is True
    assert replayed.response_resource_ref == created.response_resource_ref
    assert replayed.response_digest == created.response_digest
    assert ProviderConnection.objects.filter(workspace_id=workspace.id).count() == 1
    assert DomainEvent.objects.filter(workspace_id=workspace.id).count() == 1
    assert OutboxEvent.objects.filter(workspace_id=workspace.id).count() == 1
    assert (
        AuditEvent.objects.filter(
            workspace_id=workspace.id,
            action="CURVE.PROVIDER_CONNECTION.IDEMPOTENT_REPLAY",
            outcome=AuditOutcome.NO_EFFECT,
        ).count()
        == 1
    )


def test_registration_changed_digest_conflicts_without_a_second_domain_effect():
    workspace, user = _workspace()
    created = _register(workspace_slug=workspace.slug, user=user)
    before = {
        "connections": ProviderConnection.objects.filter(workspace_id=workspace.id).count(),
        "events": DomainEvent.objects.filter(workspace_id=workspace.id).count(),
        "outbox": OutboxEvent.objects.filter(workspace_id=workspace.id).count(),
        "inbox": InboxMessage.objects.filter(workspace_id=workspace.id).count(),
    }

    with pytest.raises(IdempotencyConflict):
        _register(
            workspace_slug=workspace.slug,
            user=user,
            display_name="Changed request digest",
        )

    assert ProviderConnection.objects.filter(workspace_id=workspace.id).count() == before["connections"]
    assert DomainEvent.objects.filter(workspace_id=workspace.id).count() == before["events"]
    assert OutboxEvent.objects.filter(workspace_id=workspace.id).count() == before["outbox"]
    assert InboxMessage.objects.filter(workspace_id=workspace.id).count() == before["inbox"]
    assert ProviderConnection.objects.get(id=created.connection.id).display_name == "Synthetic local provider"
    assert (
        AuditEvent.objects.filter(
            workspace_id=workspace.id,
            action="CURVE.PROVIDER_CONNECTION.IDEMPOTENCY_CONFLICT",
            outcome=AuditOutcome.NO_EFFECT,
        ).count()
        == 1
    )


def test_registration_rolls_back_every_record_when_domain_evidence_fails(monkeypatch):
    workspace, user = _workspace()

    def fail_event(*args, **kwargs):
        raise RuntimeError("synthetic evidence failure")

    monkeypatch.setattr(provider_services, "_append_provider_event", fail_event)

    with pytest.raises(RuntimeError, match="synthetic evidence failure"):
        _register(workspace_slug=workspace.slug, user=user)

    assert ProviderConnection.objects.filter(workspace_id=workspace.id).count() == 0
    assert IdempotencyRecord.objects.filter(workspace_id=workspace.id).count() == 0
    assert DomainEvent.objects.filter(workspace_id=workspace.id).count() == 0
    assert OutboxEvent.objects.filter(workspace_id=workspace.id).count() == 0
    assert AuditEvent.objects.filter(workspace_id=workspace.id).count() == 0
    assert PolicyDecision.objects.filter(workspace_id=workspace.id).count() == 0


@pytest.mark.parametrize("role", [15, 5])
def test_registration_denies_non_admin_roles_before_registration_effects(role):
    workspace, user = _workspace(role=role, email=f"role-{role}@example.com")

    with pytest.raises(CurvePolicyDenied):
        _register(workspace_slug=workspace.slug, user=user)

    assert ProviderConnection.objects.filter(workspace_id=workspace.id).count() == 0
    assert IdempotencyRecord.objects.filter(workspace_id=workspace.id).count() == 0
    assert DomainEvent.objects.filter(workspace_id=workspace.id).count() == 0
    assert OutboxEvent.objects.filter(workspace_id=workspace.id).count() == 0
    assert InboxMessage.objects.filter(workspace_id=workspace.id).count() == 0
    assert (
        AuditEvent.objects.filter(
            workspace_id=workspace.id,
            outcome=AuditOutcome.SUCCEEDED,
        ).count()
        == 0
    )
    decision = PolicyDecision.objects.get(workspace_id=workspace.id)
    assert decision.effect == "DENY"
    assert decision.policy_version == 2


def test_denied_command_leaves_preexisting_provider_delivery_rows_byte_equivalent():
    workspace, user = _workspace(role=15)
    _event, outbox = _local_event(workspace_id=workspace.id)
    before = {
        "state": outbox.state,
        "attempt_count": outbox.attempt_count,
        "claimed_by": outbox.claimed_by,
        "claimed_until": outbox.claimed_until,
        "next_attempt_at": outbox.next_attempt_at,
        "last_error": outbox.last_error,
    }

    with pytest.raises(CurvePolicyDenied):
        _register(workspace_slug=workspace.slug, user=user)

    outbox.refresh_from_db()
    assert {
        "state": outbox.state,
        "attempt_count": outbox.attempt_count,
        "claimed_by": outbox.claimed_by,
        "claimed_until": outbox.claimed_until,
        "next_attempt_at": outbox.next_attempt_at,
        "last_error": outbox.last_error,
    } == before
    assert InboxMessage.objects.filter(workspace_id=workspace.id).count() == 0


def test_foreign_connection_is_indistinguishable_from_absent_and_never_mutates_other_workspace():
    alpha, alpha_user = _workspace(slug="alpha", email="alpha-admin@example.com")
    beta, beta_user = _workspace(slug="beta", email="beta-admin@example.com")
    beta_connection = _register(workspace_slug=beta.slug, user=beta_user).connection
    beta_counts = {
        "version": beta_connection.aggregate_version,
        "events": DomainEvent.objects.filter(workspace_id=beta.id).count(),
        "outbox": OutboxEvent.objects.filter(workspace_id=beta.id).count(),
    }

    with pytest.raises(CurvePolicyDenied) as foreign:
        disable_provider_connection(
            request=_request(alpha_user),
            workspace_slug=alpha.slug,
            connection_id=beta_connection.id,
            expected_version=1,
            raw_idempotency_key="foreign-disable",
        )
    with pytest.raises(CurvePolicyDenied) as absent:
        disable_provider_connection(
            request=_request(alpha_user),
            workspace_slug=alpha.slug,
            connection_id=uuid.uuid4(),
            expected_version=1,
            raw_idempotency_key="absent-disable",
        )

    assert foreign.value.reason_codes == absent.value.reason_codes == ("RESOURCE_NOT_FOUND",)
    beta_connection.refresh_from_db()
    assert beta_connection.aggregate_version == beta_counts["version"]
    assert DomainEvent.objects.filter(workspace_id=beta.id).count() == beta_counts["events"]
    assert OutboxEvent.objects.filter(workspace_id=beta.id).count() == beta_counts["outbox"]
    assert IdempotencyRecord.objects.filter(workspace_id=alpha.id).count() == 0


def test_success_equivalent_and_changed_reconciliation_preserve_capability_history(monkeypatch):
    workspace, user = _workspace()
    connection = _register(workspace_slug=workspace.slug, user=user).connection

    first = _reconcile(
        user=user,
        connection=connection,
        expected_version=1,
        raw_key="reconcile-first",
    )

    connection.refresh_from_db()
    assert first.operation.status == OperationStatus.SUCCEEDED
    assert first.attempts == 1
    assert connection.status == ProviderConnectionStatus.ACTIVE
    assert connection.aggregate_version == 2
    assert connection.validated_at == FIXED_ACCEPTED_AT
    assert connection.last_reconciled_at == FIXED_ACCEPTED_AT
    assert connection.next_reconcile_at == FIXED_ACCEPTED_AT + timedelta(seconds=900)
    first_capability = ProviderCapability.objects.get(workspace_id=workspace.id)
    assert first_capability.capability_version == 1
    assert first_capability.connection_version == 2

    equivalent_time = FIXED_ACCEPTED_AT + timedelta(minutes=1)
    equivalent = _reconcile(
        user=user,
        connection=connection,
        expected_version=2,
        raw_key="reconcile-equivalent",
        accepted_at=equivalent_time,
    )

    connection.refresh_from_db()
    assert equivalent.operation.status == OperationStatus.SUCCEEDED
    assert connection.aggregate_version == 3
    assert connection.last_reconciled_at == equivalent_time
    assert connection.current_capability_id == first_capability.id
    assert ProviderCapability.objects.filter(workspace_id=workspace.id).count() == 1

    _use_adapter(monkeypatch, FakeLocalScenario.CHANGED)
    changed_time = FIXED_ACCEPTED_AT + timedelta(minutes=2)
    changed = _reconcile(
        user=user,
        connection=connection,
        expected_version=3,
        raw_key="reconcile-changed",
        accepted_at=changed_time,
    )

    connection.refresh_from_db()
    assert changed.operation.status == OperationStatus.SUCCEEDED
    assert connection.aggregate_version == 4
    assert ProviderCapability.objects.filter(workspace_id=workspace.id).count() == 2
    capability_versions = list(
        ProviderCapability.objects.filter(workspace_id=workspace.id)
        .order_by("capability_version")
        .values_list("capability_version", flat=True)
    )
    assert capability_versions == [1, 2]
    assert ProviderCapability.objects.get(id=first_capability.id).capability_version == 1
    assert connection.current_capability.capability_version == 2
    assert (
        DomainEvent.objects.filter(
            workspace_id=workspace.id,
            event_type="curve.provider_reconciliation.completed",
        ).count()
        >= 3
    )


@pytest.mark.parametrize(
    ("scenario", "expected_attempts", "expected_code"),
    [
        (FakeLocalScenario.TRANSIENT_FAILURE, 3, "TRANSIENT"),
        (FakeLocalScenario.TERMINAL_FAILURE, 1, "TERMINAL"),
    ],
)
def test_reconciliation_failure_is_normalized_and_degrades_an_active_connection(
    monkeypatch,
    scenario,
    expected_attempts,
    expected_code,
):
    workspace, user = _workspace()
    connection = _register(workspace_slug=workspace.slug, user=user).connection
    _reconcile(user=user, connection=connection, expected_version=1, raw_key="initial-success")
    connection.refresh_from_db()
    capability_id = connection.current_capability_id
    before_capabilities = ProviderCapability.objects.filter(workspace_id=workspace.id).count()
    _use_adapter(monkeypatch, scenario)

    result = _reconcile(
        user=user,
        connection=connection,
        expected_version=2,
        raw_key=f"reconcile-{scenario.value.lower()}",
        accepted_at=FIXED_ACCEPTED_AT + timedelta(minutes=1),
    )

    connection.refresh_from_db()
    assert result.attempts == expected_attempts
    assert result.operation.status == OperationStatus.FAILED
    assert result.operation.error == {
        "code": expected_code,
        "retryable": expected_code == "TRANSIENT",
    }
    assert connection.status == ProviderConnectionStatus.DEGRADED
    assert connection.aggregate_version == 3
    assert connection.current_capability_id == capability_id
    assert connection.last_error == result.operation.error
    assert connection.next_reconcile_at is None
    assert ProviderCapability.objects.filter(workspace_id=workspace.id).count() == before_capabilities
    assert AuditEvent.objects.filter(
        workspace_id=workspace.id,
        action="CURVE.PROVIDER_RECONCILIATION.FAIL",
        outcome=AuditOutcome.FAILED,
    ).exists()


def test_ambiguous_reconciliation_fails_without_connection_or_capability_mutation(monkeypatch):
    workspace, user = _workspace()
    connection = _register(workspace_slug=workspace.slug, user=user).connection
    _reconcile(user=user, connection=connection, expected_version=1, raw_key="initial-success")
    connection.refresh_from_db()
    before = (
        connection.aggregate_version,
        connection.status,
        connection.current_capability_id,
        ProviderCapability.objects.filter(workspace_id=workspace.id).count(),
    )
    _use_adapter(monkeypatch, FakeLocalScenario.AMBIGUOUS_OBSERVATION)

    result = _reconcile(
        user=user,
        connection=connection,
        expected_version=2,
        raw_key="ambiguous-result",
        accepted_at=FIXED_ACCEPTED_AT + timedelta(minutes=1),
    )

    connection.refresh_from_db()
    assert result.attempts == 1
    assert result.operation.status == OperationStatus.FAILED
    assert result.operation.error == {"code": "AMBIGUOUS_MUTATION", "retryable": False}
    assert (
        connection.aggregate_version,
        connection.status,
        connection.current_capability_id,
        ProviderCapability.objects.filter(workspace_id=workspace.id).count(),
    ) == before
    assert AuditEvent.objects.filter(
        workspace_id=workspace.id,
        action="CURVE.PROVIDER_RECONCILIATION.NO_EFFECT",
        outcome=AuditOutcome.NO_EFFECT,
    ).exists()


def test_registry_or_context_preparation_failure_completes_the_durable_operation(monkeypatch):
    workspace, user = _workspace()
    connection = _register(workspace_slug=workspace.slug, user=user).connection
    monkeypatch.setattr(
        provider_services,
        "STATIC_PROVIDER_REGISTRY",
        _BrokenRegistry(FakeLocalAdapter()),
    )

    result = _reconcile(
        user=user,
        connection=connection,
        expected_version=1,
        raw_key="broken-registry",
    )

    connection.refresh_from_db()
    result.operation.refresh_from_db()
    assert result.operation.status == OperationStatus.FAILED
    assert result.operation.error == {"code": "NOT_SUPPORTED", "retryable": False}
    assert connection.status == ProviderConnectionStatus.PENDING_VALIDATION
    assert (
        Operation.objects.filter(
            workspace_id=workspace.id,
            status=OperationStatus.PENDING,
        ).count()
        == 0
    )


def test_pending_reconciliation_replay_resumes_the_durable_adapter_phase(monkeypatch):
    workspace, user = _workspace()
    connection = _register(workspace_slug=workspace.slug, user=user).connection
    original_reconcile = provider_services.reconcile_with_retry

    def interrupt_after_operation_commit(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(provider_services, "reconcile_with_retry", interrupt_after_operation_commit)
    with pytest.raises(KeyboardInterrupt):
        _reconcile(
            user=user,
            connection=connection,
            expected_version=1,
            raw_key="resume-pending-reconciliation",
        )

    pending = Operation.objects.get(
        workspace_id=workspace.id,
        operation_type="PROVIDER_RECONCILIATION",
    )
    assert pending.status == OperationStatus.PENDING
    monkeypatch.setattr(provider_services, "reconcile_with_retry", original_reconcile)

    resumed = _reconcile(
        user=user,
        connection=connection,
        expected_version=1,
        raw_key="resume-pending-reconciliation",
    )

    assert resumed.replayed is True
    assert resumed.operation.id == pending.id
    assert resumed.operation.status == OperationStatus.SUCCEEDED
    assert Operation.objects.filter(workspace_id=workspace.id).count() == 1
    assert ProviderCapability.objects.filter(workspace_id=workspace.id).count() == 1


@pytest.mark.parametrize("adapter_outcome", ["success", "failure"])
def test_current_pending_operation_with_stale_connection_settles_to_optimistic_concurrency(
    monkeypatch,
    adapter_outcome,
):
    workspace, user = _workspace()
    connection = _register(workspace_slug=workspace.slug, user=user).connection
    _reconcile(user=user, connection=connection, expected_version=1, raw_key="initial-capability")
    connection.refresh_from_db()
    expected_connection_version = connection.aggregate_version
    observation = provider_services._capability_observation_from_model(connection.current_capability)
    original_reconcile = provider_services.reconcile_with_retry
    monkeypatch.setattr(
        provider_services,
        "reconcile_with_retry",
        lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    raw_key = f"stale-connection-{adapter_outcome}"
    with pytest.raises(KeyboardInterrupt):
        _reconcile(
            user=user,
            connection=connection,
            expected_version=expected_connection_version,
            raw_key=raw_key,
        )
    operation = Operation.objects.get(
        workspace_id=workspace.id,
        status=OperationStatus.PENDING,
    )
    connection.aggregate_version += 1
    connection.save(update_fields=["aggregate_version", "updated_at"])
    provider_event_count = DomainEvent.objects.filter(
        workspace_id=workspace.id,
        aggregate_type="PROVIDER_CONNECTION",
    ).count()

    if adapter_outcome == "success":
        result = provider_services._apply_reconciliation_success(
            workspace_id=workspace.id,
            connection_id=connection.id,
            expected_connection_version=expected_connection_version,
            operation_id=operation.id,
            expected_operation_version=operation.aggregate_version,
            observation=observation,
            attempts=1,
            accepted_at=FIXED_ACCEPTED_AT + timedelta(minutes=1),
        )
    else:
        result = provider_services._apply_reconciliation_failure(
            workspace_id=workspace.id,
            connection_id=connection.id,
            expected_connection_version=expected_connection_version,
            operation_id=operation.id,
            expected_operation_version=operation.aggregate_version,
            normalized_error=NormalizedProviderError(ProviderErrorCode.TERMINAL),
            attempts=1,
            accepted_at=FIXED_ACCEPTED_AT + timedelta(minutes=1),
        )

    connection.refresh_from_db()
    result.operation.refresh_from_db()
    assert connection.aggregate_version == expected_connection_version + 1
    assert result.operation.status == OperationStatus.FAILED
    assert result.operation.error == {"code": "OPTIMISTIC_CONCURRENCY", "retryable": False}
    assert (
        DomainEvent.objects.filter(
            workspace_id=workspace.id,
            aggregate_type="PROVIDER_CONNECTION",
        ).count()
        == provider_event_count
    )
    assert DomainEvent.objects.filter(
        workspace_id=workspace.id,
        aggregate_type="OPERATION",
        event_type="curve.provider_reconciliation.failed",
        aggregate_id=operation.id,
    ).count() == 1

    monkeypatch.setattr(provider_services, "reconcile_with_retry", original_reconcile)
    terminal_replay = _reconcile(
        user=user,
        connection=connection,
        expected_version=expected_connection_version,
        raw_key=raw_key,
    )
    assert terminal_replay.replayed is True
    assert terminal_replay.operation.id == operation.id
    assert terminal_replay.operation.error == {"code": "OPTIMISTIC_CONCURRENCY", "retryable": False}


def test_stale_success_or_failure_result_normalizes_to_optimistic_concurrency():
    workspace, user = _workspace()
    connection = _register(workspace_slug=workspace.slug, user=user).connection
    applied = _reconcile(
        user=user,
        connection=connection,
        expected_version=1,
        raw_key="result-race",
    )
    connection.refresh_from_db()
    applied.operation.refresh_from_db()
    observation = provider_services._capability_observation_from_model(connection.current_capability)
    before = {
        "connection_version": connection.aggregate_version,
        "operation_version": applied.operation.aggregate_version,
        "operation_status": applied.operation.status,
        "capabilities": ProviderCapability.objects.filter(workspace_id=workspace.id).count(),
        "events": DomainEvent.objects.filter(workspace_id=workspace.id).count(),
        "outbox": OutboxEvent.objects.filter(workspace_id=workspace.id).count(),
    }

    with pytest.raises(OptimisticConcurrencyError):
        provider_services._apply_reconciliation_success(
            workspace_id=workspace.id,
            connection_id=connection.id,
            expected_connection_version=connection.aggregate_version,
            operation_id=applied.operation.id,
            expected_operation_version=1,
            observation=observation,
            attempts=1,
            accepted_at=FIXED_ACCEPTED_AT + timedelta(minutes=1),
        )
    with pytest.raises(OptimisticConcurrencyError):
        provider_services._apply_reconciliation_failure(
            workspace_id=workspace.id,
            connection_id=connection.id,
            expected_connection_version=connection.aggregate_version,
            operation_id=applied.operation.id,
            expected_operation_version=1,
            normalized_error=NormalizedProviderError(ProviderErrorCode.TRANSIENT),
            attempts=3,
            accepted_at=FIXED_ACCEPTED_AT + timedelta(minutes=2),
        )

    connection.refresh_from_db()
    applied.operation.refresh_from_db()
    assert connection.aggregate_version == before["connection_version"]
    assert applied.operation.aggregate_version == before["operation_version"]
    assert applied.operation.status == before["operation_status"] == OperationStatus.SUCCEEDED
    assert ProviderCapability.objects.filter(workspace_id=workspace.id).count() == before["capabilities"]
    assert DomainEvent.objects.filter(workspace_id=workspace.id).count() == before["events"]
    assert OutboxEvent.objects.filter(workspace_id=workspace.id).count() == before["outbox"]
    assert (
        AuditEvent.objects.filter(
            workspace_id=workspace.id,
            action="CURVE.PROVIDER_RECONCILIATION.OPTIMISTIC_CONCURRENCY",
            outcome=AuditOutcome.NO_EFFECT,
        ).count()
        == 2
    )


def test_lifecycle_disable_enable_revoke_is_versioned_and_revoked_is_terminal():
    workspace, user = _workspace()
    connection = _register(workspace_slug=workspace.slug, user=user).connection

    disabled = disable_provider_connection(
        request=_request(user),
        workspace_slug=workspace.slug,
        connection_id=connection.id,
        expected_version=1,
        raw_idempotency_key="disable-connection",
    )
    assert disabled.connection.status == ProviderConnectionStatus.DISABLED
    assert disabled.connection.aggregate_version == 2
    with pytest.raises(InvalidProviderTransition):
        _reconcile(
            user=user,
            connection=disabled.connection,
            expected_version=2,
            raw_key="reconcile-disabled",
        )

    enabled = enable_provider_connection(
        request=_request(user),
        workspace_slug=workspace.slug,
        connection_id=connection.id,
        expected_version=2,
        raw_idempotency_key="enable-connection",
    )
    assert enabled.connection.status == ProviderConnectionStatus.PENDING_VALIDATION
    assert enabled.connection.aggregate_version == 3

    revoked = revoke_provider_connection(
        request=_request(user),
        workspace_slug=workspace.slug,
        connection_id=connection.id,
        expected_version=3,
        raw_idempotency_key="revoke-connection",
    )
    assert revoked.connection.status == ProviderConnectionStatus.REVOKED
    assert revoked.connection.aggregate_version == 4
    before_events = DomainEvent.objects.filter(workspace_id=workspace.id).count()
    with pytest.raises(InvalidProviderTransition):
        enable_provider_connection(
            request=_request(user),
            workspace_slug=workspace.slug,
            connection_id=connection.id,
            expected_version=4,
            raw_idempotency_key="enable-revoked",
        )
    connection.refresh_from_db()
    assert connection.status == ProviderConnectionStatus.REVOKED
    assert connection.aggregate_version == 4
    assert DomainEvent.objects.filter(workspace_id=workspace.id).count() == before_events
    assert AuditEvent.objects.filter(
        workspace_id=workspace.id,
        action="CURVE.PROVIDER_CONNECTION.INVALID_TRANSITION",
        outcome=AuditOutcome.NO_EFFECT,
    ).exists()


def test_stale_lifecycle_version_has_no_domain_effect():
    workspace, user = _workspace()
    connection = _register(workspace_slug=workspace.slug, user=user).connection
    before_events = DomainEvent.objects.filter(workspace_id=workspace.id).count()

    with pytest.raises(OptimisticConcurrencyError):
        disable_provider_connection(
            request=_request(user),
            workspace_slug=workspace.slug,
            connection_id=connection.id,
            expected_version=99,
            raw_idempotency_key="stale-disable",
        )

    connection.refresh_from_db()
    assert connection.aggregate_version == 1
    assert connection.status == ProviderConnectionStatus.PENDING_VALIDATION
    assert DomainEvent.objects.filter(workspace_id=workspace.id).count() == before_events
    assert AuditEvent.objects.filter(
        workspace_id=workspace.id,
        action="CURVE.PROVIDER_CONNECTION.VERSION_CONFLICT",
        outcome=AuditOutcome.NO_EFFECT,
    ).exists()


def test_provider_registry_flag_disables_every_provider_command(settings):
    workspace, user = _workspace()
    settings.CURVE_PROVIDER_REGISTRY_ENABLED = False

    with pytest.raises(ProviderRegistryDisabled):
        _register(workspace_slug=workspace.slug, user=user)

    assert ProviderConnection.objects.filter(workspace_id=workspace.id).count() == 0
    assert PolicyDecision.objects.filter(workspace_id=workspace.id).count() == 0
    assert AuditEvent.objects.filter(workspace_id=workspace.id).count() == 0


def test_post_commit_failure_is_recovered_before_the_next_provider_command(monkeypatch):
    workspace, user = _workspace()
    original_post_commit_drain = provider_services._post_commit_drain
    monkeypatch.setattr(provider_services, "_post_commit_drain", lambda **kwargs: None)
    connection = _register(workspace_slug=workspace.slug, user=user).connection
    registered_outbox = OutboxEvent.objects.get(
        workspace_id=workspace.id,
        destination=PROVIDER_LOCAL_DESTINATION,
    )
    assert registered_outbox.state == OutboxState.PENDING
    assert InboxMessage.objects.filter(workspace_id=workspace.id).count() == 0

    monkeypatch.setattr(provider_services, "_post_commit_drain", original_post_commit_drain)
    disable_provider_connection(
        request=_request(user),
        workspace_slug=workspace.slug,
        connection_id=connection.id,
        expected_version=1,
        raw_idempotency_key="recovery-trigger",
    )

    registered_outbox.refresh_from_db()
    assert registered_outbox.state == OutboxState.DELIVERED
    assert (
        InboxMessage.objects.filter(
            workspace_id=workspace.id,
            consumer_id=PROVIDER_LOCAL_CONSUMER_ID,
            event_id=registered_outbox.event_id,
            state=InboxState.PROCESSED,
        ).count()
        == 1
    )


def test_duplicate_delivery_reuses_one_inbox_effect_and_acknowledges_replay():
    workspace, _user_instance = _workspace()
    event, outbox = _local_event(workspace_id=workspace.id)
    first = drain_local_provider_events(
        workspace_id=workspace.id,
        correlation_id="first-delivery",
        now=FIXED_ACCEPTED_AT,
    )
    assert first.delivered == 1
    outbox.refresh_from_db()
    assert outbox.state == OutboxState.DELIVERED
    assert (
        InboxMessage.objects.filter(
            workspace_id=workspace.id,
            consumer_id=PROVIDER_LOCAL_CONSUMER_ID,
            event_id=event.id,
        ).count()
        == 1
    )

    OutboxEvent.objects.filter(id=outbox.id).update(
        state=OutboxState.PENDING,
        delivered_at=None,
        claimed_by=None,
        claimed_until=None,
    )
    replay = drain_local_provider_events(
        workspace_id=workspace.id,
        correlation_id="duplicate-delivery",
        now=FIXED_ACCEPTED_AT + timedelta(seconds=1),
    )

    outbox.refresh_from_db()
    assert replay.deduplicated == 1
    assert replay.delivered == 0
    assert outbox.state == OutboxState.DELIVERED
    assert (
        InboxMessage.objects.filter(
            workspace_id=workspace.id,
            consumer_id=PROVIDER_LOCAL_CONSUMER_ID,
            event_id=event.id,
        ).count()
        == 1
    )


def test_local_drain_is_bounded_to_ten_and_destination_isolated():
    workspace, _user_instance = _workspace()
    for _ in range(11):
        _local_event(workspace_id=workspace.id)
    temporal_event = DomainEvent.objects.create(
        workspace_id=workspace.id,
        event_type="curve.operation.state_changed",
        aggregate_type="OPERATION",
        aggregate_id=uuid.uuid4(),
        aggregate_version=1,
        sequence=1,
        actor=ACTOR,
        effective_principal=ACTOR,
        correlation_id="temporal-isolation",
        classification=DataClassification.INTERNAL,
        payload_schema="https://curve.example.invalid/contracts/schemas/operation-event-v1.schema.json",
        payload={"workspace_id": str(workspace.id), "status": "PENDING"},
    )
    temporal_outbox = OutboxEvent.objects.create(
        workspace_id=workspace.id,
        event_id=temporal_event.id,
        destination="CURVE_TEMPORAL_OPERATION_V1",
    )

    result = drain_local_provider_events(
        workspace_id=workspace.id,
        correlation_id="bounded-provider-drain",
        now=FIXED_ACCEPTED_AT,
    )

    assert result.claimed == 10
    assert result.delivered == 10
    assert (
        OutboxEvent.objects.filter(
            workspace_id=workspace.id,
            destination=PROVIDER_LOCAL_DESTINATION,
            state=OutboxState.PENDING,
        ).count()
        == 1
    )
    temporal_outbox.refresh_from_db()
    assert temporal_outbox.state == OutboxState.PENDING
    assert (
        InboxMessage.objects.filter(
            workspace_id=workspace.id,
            consumer_id=PROVIDER_LOCAL_CONSUMER_ID,
        ).count()
        == 10
    )


def test_abandoned_claim_is_reclaimed_at_exactly_thirty_seconds():
    workspace, _user_instance = _workspace()
    _event, outbox = _local_event(workspace_id=workspace.id)
    claimed = claim_due_outbox(
        workspace_id=workspace.id,
        worker_id="abandoned-provider-worker",
        limit=1,
        lease_duration=PROVIDER_LOCAL_CLAIM_LEASE,
        now=FIXED_ACCEPTED_AT,
        destination=PROVIDER_LOCAL_DESTINATION,
    )
    assert len(claimed) == 1

    early = drain_local_provider_events(
        workspace_id=workspace.id,
        correlation_id="lease-not-expired",
        now=FIXED_ACCEPTED_AT + timedelta(seconds=29, microseconds=999999),
    )
    assert early.claimed == 0
    outbox.refresh_from_db()
    assert outbox.state == OutboxState.CLAIMED

    exact = drain_local_provider_events(
        workspace_id=workspace.id,
        correlation_id="lease-expired",
        now=FIXED_ACCEPTED_AT + timedelta(seconds=30),
    )
    assert exact.claimed == 1
    assert exact.delivered == 1
    outbox.refresh_from_db()
    assert outbox.state == OutboxState.DELIVERED
    assert outbox.attempt_count == 2
    assert AuditEvent.objects.filter(
        workspace_id=workspace.id,
        action="CURVE.OUTBOX.CLAIM_EXPIRED",
        outcome=AuditOutcome.NO_EFFECT,
    ).exists()


def test_third_abandoned_claim_dead_letters_without_a_fourth_claim():
    workspace, _user_instance = _workspace()
    _event, outbox = _local_event(workspace_id=workspace.id)
    for attempt in range(1, 4):
        claim_time = FIXED_ACCEPTED_AT + timedelta(seconds=30 * (attempt - 1))
        claimed = claim_due_outbox(
            workspace_id=workspace.id,
            worker_id="abandoned-provider-worker",
            limit=1,
            lease_duration=PROVIDER_LOCAL_CLAIM_LEASE,
            now=claim_time,
            destination=PROVIDER_LOCAL_DESTINATION,
            maximum_attempts=3,
        )
        assert len(claimed) == 1
        assert claimed[0].attempt_count == attempt
        if attempt < 3:
            recover_expired_outbox_claims(
                workspace_id=workspace.id,
                actor=ACTOR,
                correlation_id=f"expired-claim-{attempt}",
                now=claim_time + PROVIDER_LOCAL_CLAIM_LEASE,
                destination=PROVIDER_LOCAL_DESTINATION,
                maximum_attempts=3,
            )

    exhausted = drain_local_provider_events(
        workspace_id=workspace.id,
        correlation_id="expired-claim-3",
        now=FIXED_ACCEPTED_AT + timedelta(seconds=90),
    )
    outbox.refresh_from_db()
    assert exhausted.claimed == 0
    assert outbox.state == OutboxState.DEAD_LETTER
    assert outbox.attempt_count == 3
    assert outbox.last_error == {
        "code": "CLAIM_EXPIRED_MAX_ATTEMPTS",
        "retryable": False,
    }
    assert AuditEvent.objects.filter(
        workspace_id=workspace.id,
        action="CURVE.OUTBOX.CLAIM_EXPIRED_DEAD_LETTER",
    ).count() == 1


def test_provider_event_contract_rejects_unknown_mismatched_and_invalid_payloads_before_persistence():
    workspace, user = _workspace()
    connection = _register(workspace_slug=workspace.slug, user=user).connection
    before_events = DomainEvent.objects.filter(workspace_id=workspace.id).count()
    before_outbox = OutboxEvent.objects.filter(workspace_id=workspace.id).count()

    with pytest.raises(ProviderEventContractError):
        provider_services._append_provider_event(
            connection=connection,
            event_type="curve.provider_connection.unknown",
            actor=ACTOR,
            effective_principal=ACTOR,
            correlation_id="unknown-provider-event",
            causation_id=None,
            key_digest=None,
        )
    with pytest.raises(ProviderEventContractError):
        provider_services._append_provider_event(
            connection=connection,
            event_type="curve.provider_connection.registered",
            actor=ACTOR,
            effective_principal=ACTOR,
            correlation_id="invalid-provider-event",
            causation_id=None,
            key_digest=None,
            extra_payload={"unknown": True},
        )
    with pytest.raises(ProviderEventContractError):
        validate_provider_event_payload(
            aggregate_type="OPERATION",
            event_type="curve.provider_connection.registered",
            payload={},
        )

    assert DomainEvent.objects.filter(workspace_id=workspace.id).count() == before_events
    assert OutboxEvent.objects.filter(workspace_id=workspace.id).count() == before_outbox


def test_local_delivery_retries_after_five_seconds_and_dead_letters_third_attempt(monkeypatch):
    workspace, _user_instance = _workspace()
    _event, outbox = _local_event(workspace_id=workspace.id)

    def fail_local_effect(*args, **kwargs):
        raise RuntimeError("sensitive local exception text")

    monkeypatch.setattr(provider_services, "complete_inbox_message", fail_local_effect)

    first = drain_local_provider_events(
        workspace_id=workspace.id,
        correlation_id="delivery-attempt-1",
        now=FIXED_ACCEPTED_AT,
    )
    assert first.retry_scheduled == 1
    outbox.refresh_from_db()
    assert outbox.state == OutboxState.RETRY_SCHEDULED
    assert outbox.attempt_count == 1
    assert outbox.next_attempt_at == FIXED_ACCEPTED_AT + timedelta(seconds=5)
    assert "sensitive" not in str(outbox.last_error)

    too_early = drain_local_provider_events(
        workspace_id=workspace.id,
        correlation_id="delivery-too-early",
        now=FIXED_ACCEPTED_AT + timedelta(seconds=4, microseconds=999999),
    )
    assert too_early.claimed == 0

    second = drain_local_provider_events(
        workspace_id=workspace.id,
        correlation_id="delivery-attempt-2",
        now=FIXED_ACCEPTED_AT + timedelta(seconds=5),
    )
    assert second.retry_scheduled == 1
    outbox.refresh_from_db()
    assert outbox.attempt_count == 2
    assert outbox.next_attempt_at == FIXED_ACCEPTED_AT + timedelta(seconds=10)

    third = drain_local_provider_events(
        workspace_id=workspace.id,
        correlation_id="delivery-attempt-3",
        now=FIXED_ACCEPTED_AT + timedelta(seconds=10),
    )
    assert third.dead_lettered == 1
    outbox.refresh_from_db()
    assert outbox.state == OutboxState.DEAD_LETTER
    assert outbox.attempt_count == 3
    assert outbox.last_error == {
        "code": "LOCAL_PROVIDER_DELIVERY_FAILED",
        "retryable": False,
    }
    assert InboxMessage.objects.filter(workspace_id=workspace.id).count() == 0


def test_delivery_is_strictly_workspace_scoped():
    alpha, _alpha_user = _workspace(slug="alpha", email="alpha@example.com")
    beta, _beta_user = _workspace(slug="beta", email="beta@example.com")
    _alpha_event, alpha_outbox = _local_event(workspace_id=alpha.id)
    _beta_event, beta_outbox = _local_event(workspace_id=beta.id)

    result = drain_local_provider_events(
        workspace_id=alpha.id,
        correlation_id="alpha-only-drain",
        now=FIXED_ACCEPTED_AT,
    )

    assert result.delivered == 1
    alpha_outbox.refresh_from_db()
    beta_outbox.refresh_from_db()
    assert alpha_outbox.state == OutboxState.DELIVERED
    assert beta_outbox.state == OutboxState.PENDING
    assert InboxMessage.objects.filter(workspace_id=alpha.id).count() == 1
    assert InboxMessage.objects.filter(workspace_id=beta.id).count() == 0
