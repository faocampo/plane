# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import builtins
import importlib
import os
import pathlib
import socket
import subprocess
from dataclasses import FrozenInstanceError, fields, replace

import pytest

from plane.curve.policy_types import DataClassification
from plane.curve.providers import (
    MAX_RECONCILIATION_ATTEMPTS,
    STATIC_PROVIDER_REGISTRY,
    TOTAL_RECONCILIATION_DEADLINE_SECONDS,
    ActorRef,
    ActorType,
    FakeLocalAdapter,
    FakeLocalScenario,
    NeverCancelled,
    NormalizedProviderError,
    ProviderCallContext,
    ProviderCapability,
    ProviderCapabilityObservation,
    ProviderCapabilityRisk,
    ProviderErrorCode,
    ProviderObservationRef,
    ProviderReconciliationCancelled,
    ProviderReconciliationDeadlineExceeded,
    ProviderReconciliationFailed,
    ProviderRegistryError,
    ProviderRegistryErrorCode,
    ProviderType,
    StaticProviderRegistry,
    reconcile_with_retry,
)


WORKSPACE_ID = "00000000-0000-4000-8000-000000000001"
CONNECTION_ID = "00000000-0000-4000-8000-000000000002"
DIGEST = f"sha256:{'a' * 64}"


class MutableCancellation:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled

    def is_cancelled(self) -> bool:
        return self.cancelled


def _context(
    *,
    cancellation_token: NeverCancelled | MutableCancellation | None = None,
    started_at: float = 100.0,
) -> ProviderCallContext:
    return ProviderCallContext.start(
        workspace_id=WORKSPACE_ID,
        connection_id=CONNECTION_ID,
        effective_principal=ActorRef(ActorType.HUMAN, "human-reviewer"),
        correlation_id="correlation-1",
        causation_id="causation-1",
        idempotency_key_digest=DIGEST,
        cancellation_token=cancellation_token or NeverCancelled(),
        policy_key="CURVE_CORE_POLICY",
        policy_version=2,
        policy_manifest_digest=DIGEST,
        provider_type=ProviderType.FAKE_LOCAL,
        adapter_key="curve.fake-local",
        adapter_version="1.0.0",
        monotonic=lambda: started_at,
    )


def _base_observation(context: ProviderCallContext) -> ProviderCapabilityObservation:
    return FakeLocalAdapter().describe_capabilities(context)


def test_call_context_is_immutable_digest_only_and_exactly_fifteen_seconds() -> None:
    context = _context()

    assert context.service_actor == ActorRef(ActorType.SERVICE, "provider-registry")
    assert context.classification is DataClassification.INTERNAL
    assert context.deadline_monotonic - context.started_monotonic == TOTAL_RECONCILIATION_DEADLINE_SECONDS
    assert context.idempotency_key_digest == DIGEST
    with pytest.raises(FrozenInstanceError):
        context.adapter_version = "2.0.0"
    with pytest.raises(ValueError, match="invalid deadline_monotonic"):
        replace(context, deadline_monotonic=context.started_monotonic + 14.9)

    field_names = {item.name for item in fields(ProviderCallContext)}
    assert not any(
        forbidden in field_name
        for field_name in field_names
        for forbidden in (
            "secret",
            "credential",
            "configuration",
            "password",
            "oauth",
            "access_token",
            "api_key",
            "raw_idempotency",
        )
    )


def test_capability_values_and_observations_are_deeply_immutable() -> None:
    observation = _base_observation(_context())

    assert type(observation.protocol_versions) is tuple
    assert type(observation.capabilities) is tuple
    assert type(observation.allowed_classifications) is tuple
    with pytest.raises(FrozenInstanceError):
        observation.adapter_key = "curve.other"
    with pytest.raises(FrozenInstanceError):
        observation.capabilities[0].enabled = False


def test_normalized_error_taxonomy_retries_only_rate_limit_and_transient() -> None:
    assert tuple(code.value for code in ProviderErrorCode) == (
        "AUTHENTICATION",
        "AUTHORIZATION",
        "POLICY",
        "NOT_SUPPORTED",
        "RATE_LIMIT",
        "TRANSIENT",
        "AMBIGUOUS_MUTATION",
        "TERMINAL",
    )
    assert {code for code in ProviderErrorCode if NormalizedProviderError(code).retryable} == {
        ProviderErrorCode.RATE_LIMIT,
        ProviderErrorCode.TRANSIENT,
    }


def test_static_registry_contains_only_the_exact_fake_local_target() -> None:
    registration = STATIC_PROVIDER_REGISTRY.registration_for(
        "curve.fake-local",
        adapter_version="1.0.0",
        provider_type="FAKE_LOCAL",
    )

    assert tuple(STATIC_PROVIDER_REGISTRY.registrations) == ("curve.fake-local",)
    assert registration.target_id == "curve.fake-local@1.0.0"
    assert registration.protocol_versions == ("curve.fake-local/v1",)
    assert registration.enabled_capability_risks == frozenset({ProviderCapabilityRisk.READ})
    assert registration.allowed_classifications == (DataClassification.INTERNAL,)
    with pytest.raises(TypeError):
        STATIC_PROVIDER_REGISTRY.registrations["curve.other"] = registration


@pytest.mark.parametrize(
    ("adapter_key", "adapter_version", "provider_type", "error_code"),
    [
        ("curve.dynamic.module", "1.0.0", "FAKE_LOCAL", ProviderRegistryErrorCode.UNKNOWN_ADAPTER),
        ("curve.fake-local", "9.9.9", "FAKE_LOCAL", ProviderRegistryErrorCode.ADAPTER_VERSION_MISMATCH),
        (
            "curve.fake-local",
            "1.0.0",
            ProviderType.MCP,
            ProviderRegistryErrorCode.PROVIDER_TYPE_MISMATCH,
        ),
    ],
)
def test_registry_fails_closed_for_unknown_or_mismatched_targets(
    adapter_key: str,
    adapter_version: str,
    provider_type: ProviderType | str,
    error_code: ProviderRegistryErrorCode,
) -> None:
    with pytest.raises(ProviderRegistryError) as caught:
        STATIC_PROVIDER_REGISTRY.resolve(
            adapter_key,
            adapter_version=adapter_version,
            provider_type=provider_type,
        )

    assert caught.value.code is error_code


def test_registry_rejects_duplicate_static_registration() -> None:
    registration = next(iter(STATIC_PROVIDER_REGISTRY.registrations.values()))

    with pytest.raises(ProviderRegistryError) as caught:
        StaticProviderRegistry((registration, registration))

    assert caught.value.code is ProviderRegistryErrorCode.DUPLICATE_ADAPTER


def test_registry_returns_a_fresh_exact_adapter_and_validates_its_observation() -> None:
    first = STATIC_PROVIDER_REGISTRY.resolve(
        "curve.fake-local",
        adapter_version="1.0.0",
        provider_type=ProviderType.FAKE_LOCAL,
    )
    second = STATIC_PROVIDER_REGISTRY.resolve(
        "curve.fake-local",
        adapter_version="1.0.0",
        provider_type=ProviderType.FAKE_LOCAL,
    )
    observation = first.describe_capabilities(_context())

    assert isinstance(first, FakeLocalAdapter)
    assert isinstance(second, FakeLocalAdapter)
    assert first is not second
    STATIC_PROVIDER_REGISTRY.validate_observation(observation)


@pytest.mark.parametrize(
    ("replacement", "error_code"),
    [
        ({"protocol_versions": ("curve.unknown/v1",)}, ProviderRegistryErrorCode.UNSUPPORTED_PROTOCOL),
        (
            {"allowed_classifications": (DataClassification.CONFIDENTIAL,)},
            ProviderRegistryErrorCode.CLASSIFICATION_NOT_ALLOWED,
        ),
        (
            {
                "capabilities": (
                    ProviderCapability(
                        name="curve.fake-local.write",
                        risk=ProviderCapabilityRisk.WORKFLOW_WRITE,
                        enabled=True,
                    ),
                )
            },
            ProviderRegistryErrorCode.UNSUPPORTED_CAPABILITY,
        ),
        (
            {
                "capabilities": (
                    ProviderCapability(
                        name="curve.fake-local.read",
                        risk=ProviderCapabilityRisk.READ,
                        enabled=True,
                        schema_uri="curve://unknown-schema",
                    ),
                )
            },
            ProviderRegistryErrorCode.UNSUPPORTED_CAPABILITY,
        ),
    ],
)
def test_registry_rejects_unsupported_fake_observations(
    replacement: dict[str, object],
    error_code: ProviderRegistryErrorCode,
) -> None:
    observation = replace(_base_observation(_context()), **replacement)

    with pytest.raises(ProviderRegistryError) as caught:
        STATIC_PROVIDER_REGISTRY.validate_observation(observation)

    assert caught.value.code is error_code


def test_fake_adapter_describes_only_the_fixed_internal_read_capability() -> None:
    observation = _base_observation(_context())

    assert observation.provider_type is ProviderType.FAKE_LOCAL
    assert observation.adapter_key == "curve.fake-local"
    assert observation.adapter_version == "1.0.0"
    assert observation.protocol_versions == ("curve.fake-local/v1",)
    assert observation.allowed_classifications == (DataClassification.INTERNAL,)
    assert {capability.risk for capability in observation.capabilities if capability.enabled} == {
        ProviderCapabilityRisk.READ
    }


def test_fake_adapter_reconciliation_is_deterministic_for_equivalent_and_changed_observations() -> None:
    context = _context()
    current = _base_observation(context)
    previous = ProviderObservationRef.from_observation(current)

    equivalent = FakeLocalAdapter().reconcile(context, previous)
    changed = FakeLocalAdapter((FakeLocalScenario.CHANGED,)).reconcile(context, previous)

    assert equivalent.changed is False
    assert equivalent.capability_observation.capability_digest == current.capability_digest
    assert changed.changed is True
    assert changed.capability_observation.capability_digest != current.capability_digest
    assert all(
        capability.risk is ProviderCapabilityRisk.READ for capability in changed.capability_observation.capabilities
    )


@pytest.mark.parametrize(
    "scenario",
    [FakeLocalScenario.TRANSIENT_FAILURE, FakeLocalScenario.RATE_LIMIT_FAILURE],
)
def test_retryable_errors_retry_and_then_return_success(scenario: FakeLocalScenario) -> None:
    adapter = FakeLocalAdapter((scenario, FakeLocalScenario.SUCCESS))

    result = reconcile_with_retry(adapter, _context(), None, monotonic=lambda: 100.0)

    assert result.attempts == 2
    assert adapter.reconcile_calls == 2


def test_retryable_error_exhaustion_stops_at_exactly_three_attempts() -> None:
    adapter = FakeLocalAdapter((FakeLocalScenario.TRANSIENT_FAILURE,))

    with pytest.raises(ProviderReconciliationFailed) as caught:
        reconcile_with_retry(adapter, _context(), None, monotonic=lambda: 100.0)

    assert caught.value.error == NormalizedProviderError(ProviderErrorCode.TRANSIENT)
    assert caught.value.attempts == MAX_RECONCILIATION_ATTEMPTS
    assert adapter.reconcile_calls == MAX_RECONCILIATION_ATTEMPTS


@pytest.mark.parametrize(
    ("scenario", "error_code"),
    [
        (FakeLocalScenario.TERMINAL_FAILURE, ProviderErrorCode.TERMINAL),
        (FakeLocalScenario.UNSUPPORTED_CAPABILITY, ProviderErrorCode.NOT_SUPPORTED),
        (FakeLocalScenario.AMBIGUOUS_OBSERVATION, ProviderErrorCode.AMBIGUOUS_MUTATION),
    ],
)
def test_non_retryable_and_ambiguous_errors_never_blind_retry(
    scenario: FakeLocalScenario,
    error_code: ProviderErrorCode,
) -> None:
    adapter = FakeLocalAdapter((scenario, FakeLocalScenario.SUCCESS))

    with pytest.raises(ProviderReconciliationFailed) as caught:
        reconcile_with_retry(adapter, _context(), None, monotonic=lambda: 100.0)

    assert caught.value.error == NormalizedProviderError(error_code)
    assert caught.value.attempts == 1
    assert adapter.reconcile_calls == 1


def test_deadline_is_one_total_monotonic_budget_and_discards_a_late_result() -> None:
    context = _context(started_at=100.0)
    clock = iter((100.0, 115.0))
    adapter = FakeLocalAdapter()

    with pytest.raises(ProviderReconciliationDeadlineExceeded) as caught:
        reconcile_with_retry(adapter, context, None, monotonic=lambda: next(clock))

    assert caught.value.error == NormalizedProviderError(ProviderErrorCode.TRANSIENT)
    assert caught.value.attempts == 1
    assert adapter.reconcile_calls == 1


def test_deadline_exhaustion_between_retry_attempts_stops_immediately() -> None:
    context = _context(started_at=100.0)
    clock = iter((100.0, 114.0, 115.0))
    adapter = FakeLocalAdapter((FakeLocalScenario.TRANSIENT_FAILURE, FakeLocalScenario.SUCCESS))

    with pytest.raises(ProviderReconciliationDeadlineExceeded) as caught:
        reconcile_with_retry(adapter, context, None, monotonic=lambda: next(clock))

    assert caught.value.attempts == 1
    assert adapter.reconcile_calls == 1


def test_cancellation_before_the_first_attempt_fails_closed() -> None:
    adapter = FakeLocalAdapter()

    with pytest.raises(ProviderReconciliationCancelled) as caught:
        reconcile_with_retry(
            adapter,
            _context(cancellation_token=MutableCancellation(cancelled=True)),
            None,
            monotonic=lambda: 100.0,
        )

    assert caught.value.error == NormalizedProviderError(ProviderErrorCode.TERMINAL)
    assert caught.value.attempts == 0
    assert adapter.reconcile_calls == 0


def test_cancellation_after_adapter_return_discards_the_result() -> None:
    cancellation = MutableCancellation()

    class CancellingAdapter(FakeLocalAdapter):
        def reconcile(self, context, previous):
            observation = super().reconcile(context, previous)
            cancellation.cancelled = True
            return observation

    adapter = CancellingAdapter()
    with pytest.raises(ProviderReconciliationCancelled) as caught:
        reconcile_with_retry(
            adapter,
            _context(cancellation_token=cancellation),
            None,
            monotonic=lambda: 100.0,
        )

    assert caught.value.attempts == 1
    assert adapter.reconcile_calls == 1


def test_unexpected_adapter_exception_is_normalized_without_exposing_its_text() -> None:
    class UnexpectedAdapter(FakeLocalAdapter):
        def reconcile(self, context, previous):
            raise RuntimeError("protected-provider-detail")

    with pytest.raises(ProviderReconciliationFailed) as caught:
        reconcile_with_retry(UnexpectedAdapter(), _context(), None, monotonic=lambda: 100.0)

    assert caught.value.error == NormalizedProviderError(ProviderErrorCode.TERMINAL)
    assert caught.value.attempts == 1
    assert str(caught.value) == "TERMINAL"
    assert caught.value.__cause__ is None


def test_fake_adapter_and_registry_use_no_dynamic_import_network_filesystem_environment_or_subprocess(
    monkeypatch,
) -> None:
    context = _context()

    def forbidden(*args, **kwargs):
        raise AssertionError("prohibited runtime access")

    class ForbiddenEnvironment(dict):
        def __getitem__(self, key):
            raise AssertionError("prohibited runtime access")

        def get(self, key, default=None):
            raise AssertionError("prohibited runtime access")

    with monkeypatch.context() as denied:
        denied.setattr(importlib, "import_module", forbidden)
        denied.setattr(socket, "socket", forbidden)
        denied.setattr(socket, "create_connection", forbidden)
        denied.setattr(builtins, "open", forbidden)
        denied.setattr(pathlib.Path, "open", forbidden)
        denied.setattr(pathlib.Path, "read_text", forbidden)
        denied.setattr(pathlib.Path, "read_bytes", forbidden)
        denied.setattr(os, "getenv", forbidden)
        denied.setattr(os, "environ", ForbiddenEnvironment())
        denied.setattr(subprocess, "Popen", forbidden)
        denied.setattr(subprocess, "run", forbidden)
        denied.setattr(subprocess, "call", forbidden)
        denied.setattr(subprocess, "check_call", forbidden)
        denied.setattr(subprocess, "check_output", forbidden)

        adapter = STATIC_PROVIDER_REGISTRY.resolve(
            "curve.fake-local",
            adapter_version="1.0.0",
            provider_type=ProviderType.FAKE_LOCAL,
        )
        described = adapter.describe_capabilities(context)
        reconciled = reconcile_with_retry(adapter, context, None, monotonic=lambda: 100.0)

    assert described.capability_digest == reconciled.observation.capability_observation.capability_digest
