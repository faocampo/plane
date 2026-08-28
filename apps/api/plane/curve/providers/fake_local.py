# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from enum import StrEnum

from plane.curve.policy_types import DataClassification
from plane.curve.providers.types import (
    NormalizedProviderError,
    ProviderAdapterError,
    ProviderCallContext,
    ProviderCapability,
    ProviderCapabilityObservation,
    ProviderCapabilityRisk,
    ProviderErrorCode,
    ProviderObservationRef,
    ProviderReconciliationObservation,
    ProviderType,
)


FAKE_LOCAL_ADAPTER_KEY = "curve.fake-local"
FAKE_LOCAL_ADAPTER_VERSION = "1.0.0"
FAKE_LOCAL_PROTOCOL_VERSION = "curve.fake-local/v1"


class FakeLocalScenario(StrEnum):
    SUCCESS = "SUCCESS"
    CHANGED = "CHANGED"
    RATE_LIMIT_FAILURE = "RATE_LIMIT_FAILURE"
    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    AMBIGUOUS_OBSERVATION = "AMBIGUOUS_OBSERVATION"


_ERROR_CODES = {
    FakeLocalScenario.RATE_LIMIT_FAILURE: ProviderErrorCode.RATE_LIMIT,
    FakeLocalScenario.TRANSIENT_FAILURE: ProviderErrorCode.TRANSIENT,
    FakeLocalScenario.TERMINAL_FAILURE: ProviderErrorCode.TERMINAL,
    FakeLocalScenario.UNSUPPORTED_CAPABILITY: ProviderErrorCode.NOT_SUPPORTED,
    FakeLocalScenario.AMBIGUOUS_OBSERVATION: ProviderErrorCode.AMBIGUOUS_MUTATION,
}


def _base_capability_observation(context: ProviderCallContext) -> ProviderCapabilityObservation:
    return ProviderCapabilityObservation(
        workspace_id=context.workspace_id,
        connection_id=context.connection_id,
        provider_type=ProviderType.FAKE_LOCAL,
        adapter_key=FAKE_LOCAL_ADAPTER_KEY,
        adapter_version=FAKE_LOCAL_ADAPTER_VERSION,
        protocol_versions=(FAKE_LOCAL_PROTOCOL_VERSION,),
        capabilities=(
            ProviderCapability(
                name="curve.fake-local.read",
                risk=ProviderCapabilityRisk.READ,
                enabled=True,
            ),
        ),
        allowed_classifications=(DataClassification.INTERNAL,),
    )


def _changed_capability_observation(context: ProviderCallContext) -> ProviderCapabilityObservation:
    return ProviderCapabilityObservation(
        workspace_id=context.workspace_id,
        connection_id=context.connection_id,
        provider_type=ProviderType.FAKE_LOCAL,
        adapter_key=FAKE_LOCAL_ADAPTER_KEY,
        adapter_version=FAKE_LOCAL_ADAPTER_VERSION,
        protocol_versions=(FAKE_LOCAL_PROTOCOL_VERSION,),
        capabilities=(
            ProviderCapability(
                name="curve.fake-local.read",
                risk=ProviderCapabilityRisk.READ,
                enabled=True,
            ),
            ProviderCapability(
                name="curve.fake-local.metadata.read",
                risk=ProviderCapabilityRisk.READ,
                enabled=True,
            ),
        ),
        allowed_classifications=(DataClassification.INTERNAL,),
    )


class FakeLocalAdapter:
    adapter_key = FAKE_LOCAL_ADAPTER_KEY
    provider_type = ProviderType.FAKE_LOCAL
    adapter_version = FAKE_LOCAL_ADAPTER_VERSION

    def __init__(self, scenarios: tuple[FakeLocalScenario, ...] = (FakeLocalScenario.SUCCESS,)) -> None:
        if type(scenarios) is not tuple or not scenarios:
            raise ValueError("invalid fake-local scenarios")
        if any(not isinstance(scenario, FakeLocalScenario) for scenario in scenarios):
            raise ValueError("invalid fake-local scenarios")
        self._scenarios = scenarios
        self._reconcile_calls = 0

    @property
    def reconcile_calls(self) -> int:
        return self._reconcile_calls

    def _validate_context(self, context: ProviderCallContext) -> None:
        if (
            context.provider_type is not self.provider_type
            or context.adapter_key != self.adapter_key
            or context.adapter_version != self.adapter_version
            or context.classification is not DataClassification.INTERNAL
        ):
            raise ProviderAdapterError(NormalizedProviderError(ProviderErrorCode.NOT_SUPPORTED))

    def _validate_previous(self, context: ProviderCallContext, previous: ProviderObservationRef | None) -> None:
        if previous is None:
            return
        if (
            previous.workspace_id != context.workspace_id
            or previous.connection_id != context.connection_id
            or previous.provider_type is not self.provider_type
            or previous.adapter_key != self.adapter_key
            or previous.adapter_version != self.adapter_version
        ):
            raise ProviderAdapterError(NormalizedProviderError(ProviderErrorCode.TERMINAL))

    def _next_scenario(self) -> FakeLocalScenario:
        position = min(self._reconcile_calls, len(self._scenarios) - 1)
        self._reconcile_calls += 1
        return self._scenarios[position]

    def describe_capabilities(self, context: ProviderCallContext) -> ProviderCapabilityObservation:
        self._validate_context(context)
        return _base_capability_observation(context)

    def reconcile(
        self,
        context: ProviderCallContext,
        previous: ProviderObservationRef | None,
    ) -> ProviderReconciliationObservation:
        self._validate_context(context)
        self._validate_previous(context, previous)
        scenario = self._next_scenario()
        error_code = _ERROR_CODES.get(scenario)
        if error_code is not None:
            raise ProviderAdapterError(NormalizedProviderError(error_code))

        capability_observation = (
            _changed_capability_observation(context)
            if scenario is FakeLocalScenario.CHANGED
            else _base_capability_observation(context)
        )
        changed = previous is None or previous.capability_digest != capability_observation.capability_digest
        return ProviderReconciliationObservation(
            capability_observation=capability_observation,
            changed=changed,
        )
