# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from plane.curve.policy_types import DataClassification
from plane.curve.providers.fake_local import (
    FAKE_LOCAL_ADAPTER_KEY,
    FAKE_LOCAL_ADAPTER_VERSION,
    FAKE_LOCAL_PROTOCOL_VERSION,
    FakeLocalAdapter,
)
from plane.curve.providers.types import (
    ProviderAdapter,
    ProviderCapabilityObservation,
    ProviderCapabilityRisk,
    ProviderType,
)


class ProviderRegistryErrorCode(StrEnum):
    UNKNOWN_ADAPTER = "UNKNOWN_ADAPTER"
    DUPLICATE_ADAPTER = "DUPLICATE_ADAPTER"
    PROVIDER_TYPE_MISMATCH = "PROVIDER_TYPE_MISMATCH"
    ADAPTER_VERSION_MISMATCH = "ADAPTER_VERSION_MISMATCH"
    UNSUPPORTED_PROTOCOL = "UNSUPPORTED_PROTOCOL"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    CLASSIFICATION_NOT_ALLOWED = "CLASSIFICATION_NOT_ALLOWED"
    INVALID_ADAPTER = "INVALID_ADAPTER"


class ProviderRegistryError(ValueError):
    def __init__(self, code: ProviderRegistryErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class AdapterRegistration:
    adapter_key: str
    provider_type: ProviderType
    adapter_version: str
    protocol_versions: tuple[str, ...]
    enabled_capability_risks: frozenset[ProviderCapabilityRisk]
    allowed_classifications: tuple[DataClassification, ...]
    supported_schema_uris: frozenset[str]
    factory: Callable[[], ProviderAdapter]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.adapter_key, str)
            or not self.adapter_key
            or not isinstance(self.provider_type, ProviderType)
            or not isinstance(self.adapter_version, str)
            or not self.adapter_version
            or type(self.protocol_versions) is not tuple
            or not self.protocol_versions
            or any(not isinstance(value, str) or not value for value in self.protocol_versions)
            or len(set(self.protocol_versions)) != len(self.protocol_versions)
            or type(self.enabled_capability_risks) is not frozenset
            or not self.enabled_capability_risks
            or any(not isinstance(value, ProviderCapabilityRisk) for value in self.enabled_capability_risks)
            or type(self.allowed_classifications) is not tuple
            or not self.allowed_classifications
            or any(
                not isinstance(value, DataClassification) or value is DataClassification.UNKNOWN
                for value in self.allowed_classifications
            )
            or len(set(self.allowed_classifications)) != len(self.allowed_classifications)
            or type(self.supported_schema_uris) is not frozenset
            or any(not isinstance(value, str) or not value for value in self.supported_schema_uris)
            or not callable(self.factory)
        ):
            raise ProviderRegistryError(ProviderRegistryErrorCode.INVALID_ADAPTER)

    @property
    def target_id(self) -> str:
        return f"{self.adapter_key}@{self.adapter_version}"


def _provider_type_value(provider_type: ProviderType | str) -> str:
    if isinstance(provider_type, ProviderType):
        return provider_type.value
    if type(provider_type) is str:
        return provider_type
    return ""


class StaticProviderRegistry:
    def __init__(self, registrations: Sequence[AdapterRegistration]) -> None:
        by_key: dict[str, AdapterRegistration] = {}
        for registration in registrations:
            if not isinstance(registration, AdapterRegistration):
                raise ProviderRegistryError(ProviderRegistryErrorCode.INVALID_ADAPTER)
            if registration.adapter_key in by_key:
                raise ProviderRegistryError(ProviderRegistryErrorCode.DUPLICATE_ADAPTER)
            by_key[registration.adapter_key] = registration
        self._registrations: Mapping[str, AdapterRegistration] = MappingProxyType(by_key)

    @property
    def registrations(self) -> Mapping[str, AdapterRegistration]:
        return self._registrations

    def registration_for(
        self,
        adapter_key: str,
        *,
        adapter_version: str,
        provider_type: ProviderType | str,
    ) -> AdapterRegistration:
        if type(adapter_key) is not str:
            raise ProviderRegistryError(ProviderRegistryErrorCode.UNKNOWN_ADAPTER)
        registration = self._registrations.get(adapter_key)
        if registration is None:
            raise ProviderRegistryError(ProviderRegistryErrorCode.UNKNOWN_ADAPTER)
        if registration.provider_type.value != _provider_type_value(provider_type):
            raise ProviderRegistryError(ProviderRegistryErrorCode.PROVIDER_TYPE_MISMATCH)
        if registration.adapter_version != adapter_version:
            raise ProviderRegistryError(ProviderRegistryErrorCode.ADAPTER_VERSION_MISMATCH)
        return registration

    def resolve(
        self,
        adapter_key: str,
        *,
        adapter_version: str,
        provider_type: ProviderType | str,
    ) -> ProviderAdapter:
        registration = self.registration_for(
            adapter_key,
            adapter_version=adapter_version,
            provider_type=provider_type,
        )
        try:
            adapter = registration.factory()
            valid_adapter = (
                isinstance(adapter, ProviderAdapter)
                and adapter.adapter_key == registration.adapter_key
                and _provider_type_value(adapter.provider_type) == registration.provider_type.value
                and adapter.adapter_version == registration.adapter_version
            )
        except Exception:
            valid_adapter = False
        if not valid_adapter:
            raise ProviderRegistryError(ProviderRegistryErrorCode.INVALID_ADAPTER)
        return adapter

    def validate_observation(self, observation: ProviderCapabilityObservation) -> None:
        if not isinstance(observation, ProviderCapabilityObservation):
            raise ProviderRegistryError(ProviderRegistryErrorCode.INVALID_ADAPTER)
        registration = self.registration_for(
            observation.adapter_key,
            adapter_version=observation.adapter_version,
            provider_type=observation.provider_type,
        )
        if observation.protocol_versions != registration.protocol_versions:
            raise ProviderRegistryError(ProviderRegistryErrorCode.UNSUPPORTED_PROTOCOL)
        if observation.allowed_classifications != registration.allowed_classifications:
            raise ProviderRegistryError(ProviderRegistryErrorCode.CLASSIFICATION_NOT_ALLOWED)
        for capability in observation.capabilities:
            if capability.risk not in registration.enabled_capability_risks:
                raise ProviderRegistryError(ProviderRegistryErrorCode.UNSUPPORTED_CAPABILITY)
            if capability.schema_uri is not None and capability.schema_uri not in registration.supported_schema_uris:
                raise ProviderRegistryError(ProviderRegistryErrorCode.UNSUPPORTED_CAPABILITY)


FAKE_LOCAL_REGISTRATION = AdapterRegistration(
    adapter_key=FAKE_LOCAL_ADAPTER_KEY,
    provider_type=ProviderType.FAKE_LOCAL,
    adapter_version=FAKE_LOCAL_ADAPTER_VERSION,
    protocol_versions=(FAKE_LOCAL_PROTOCOL_VERSION,),
    enabled_capability_risks=frozenset({ProviderCapabilityRisk.READ}),
    allowed_classifications=(DataClassification.INTERNAL,),
    supported_schema_uris=frozenset(),
    factory=FakeLocalAdapter,
)

STATIC_PROVIDER_REGISTRY = StaticProviderRegistry((FAKE_LOCAL_REGISTRATION,))
