# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import json
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable, Protocol, runtime_checkable

from plane.curve.policy_types import DataClassification


TOTAL_RECONCILIATION_DEADLINE_SECONDS = 15.0
MAX_RECONCILIATION_ATTEMPTS = 3
PROVIDER_REGISTRY_SERVICE_ACTOR_ID = "provider-registry"

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_ADAPTER_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9.-]{0,99}$")
_CAPABILITY_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")


class ProviderType(StrEnum):
    FAKE_LOCAL = "FAKE_LOCAL"
    ONYX = "ONYX"
    MCP = "MCP"
    ORCA_HUMAN_ASSISTANCE = "ORCA_HUMAN_ASSISTANCE"
    MODEL_GATEWAY = "MODEL_GATEWAY"
    OPENHANDS = "OPENHANDS"
    GITHUB = "GITHUB"
    GITLAB = "GITLAB"
    QUALITY = "QUALITY"
    FEATURE_FLAG = "FEATURE_FLAG"
    DOCUMENTATION = "DOCUMENTATION"
    MONITORING = "MONITORING"
    PROTOTYPE = "PROTOTYPE"


class ProviderCapabilityRisk(StrEnum):
    READ = "READ"
    WORKFLOW_WRITE = "WORKFLOW_WRITE"
    EXTERNAL_MUTATION = "EXTERNAL_MUTATION"


class ProviderErrorCode(StrEnum):
    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    POLICY = "POLICY"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    RATE_LIMIT = "RATE_LIMIT"
    TRANSIENT = "TRANSIENT"
    AMBIGUOUS_MUTATION = "AMBIGUOUS_MUTATION"
    TERMINAL = "TERMINAL"


RETRYABLE_PROVIDER_ERROR_CODES = frozenset(
    {
        ProviderErrorCode.RATE_LIMIT,
        ProviderErrorCode.TRANSIENT,
    }
)


class ActorType(StrEnum):
    HUMAN = "HUMAN"
    SERVICE = "SERVICE"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"


def _require_uuid(value: str, field_name: str) -> None:
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError(f"invalid {field_name}") from error
    if str(parsed) != value:
        raise ValueError(f"invalid {field_name}")


def _require_safe_reference(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _SAFE_REFERENCE_PATTERN.fullmatch(value) is None:
        raise ValueError(f"invalid {field_name}")


def _require_digest(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError(f"invalid {field_name}")


def _require_adapter_key(value: str) -> None:
    if not isinstance(value, str) or _ADAPTER_KEY_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid adapter_key")


def _require_adapter_version(value: str) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 100:
        raise ValueError("invalid adapter_version")


@dataclass(frozen=True, slots=True)
class ActorRef:
    actor_type: ActorType
    actor_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.actor_type, ActorType):
            raise ValueError("invalid actor_type")
        _require_safe_reference(self.actor_id, "actor_id")


@runtime_checkable
class CancellationToken(Protocol):
    def is_cancelled(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class NeverCancelled:
    def is_cancelled(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class ProviderCallContext:
    workspace_id: str
    connection_id: str
    service_actor: ActorRef
    effective_principal: ActorRef
    classification: DataClassification
    correlation_id: str
    causation_id: str
    idempotency_key_digest: str
    started_monotonic: float
    deadline_monotonic: float
    cancellation_token: CancellationToken
    policy_key: str
    policy_version: int
    policy_manifest_digest: str
    provider_type: ProviderType
    adapter_key: str
    adapter_version: str

    def __post_init__(self) -> None:
        _require_uuid(self.workspace_id, "workspace_id")
        _require_uuid(self.connection_id, "connection_id")
        if not isinstance(self.service_actor, ActorRef) or self.service_actor != ActorRef(
            ActorType.SERVICE,
            PROVIDER_REGISTRY_SERVICE_ACTOR_ID,
        ):
            raise ValueError("invalid service_actor")
        if (
            not isinstance(self.effective_principal, ActorRef)
            or self.effective_principal.actor_type is not ActorType.HUMAN
        ):
            raise ValueError("invalid effective_principal")
        if self.classification is not DataClassification.INTERNAL:
            raise ValueError("invalid classification")
        _require_safe_reference(self.correlation_id, "correlation_id")
        _require_safe_reference(self.causation_id, "causation_id")
        _require_digest(self.idempotency_key_digest, "idempotency_key_digest")
        if (
            not isinstance(self.started_monotonic, (int, float))
            or isinstance(self.started_monotonic, bool)
            or not math.isfinite(self.started_monotonic)
        ):
            raise ValueError("invalid started_monotonic")
        if (
            not isinstance(self.deadline_monotonic, (int, float))
            or isinstance(self.deadline_monotonic, bool)
            or not math.isfinite(self.deadline_monotonic)
        ):
            raise ValueError("invalid deadline_monotonic")
        if not math.isclose(
            self.deadline_monotonic - self.started_monotonic,
            TOTAL_RECONCILIATION_DEADLINE_SECONDS,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ValueError("invalid deadline_monotonic")
        if not isinstance(self.cancellation_token, CancellationToken):
            raise ValueError("invalid cancellation_token")
        _require_safe_reference(self.policy_key, "policy_key")
        if type(self.policy_version) is not int or self.policy_version < 1:
            raise ValueError("invalid policy_version")
        _require_digest(self.policy_manifest_digest, "policy_manifest_digest")
        if not isinstance(self.provider_type, ProviderType):
            raise ValueError("invalid provider_type")
        _require_adapter_key(self.adapter_key)
        _require_adapter_version(self.adapter_version)

    @classmethod
    def start(
        cls,
        *,
        workspace_id: str,
        connection_id: str,
        effective_principal: ActorRef,
        correlation_id: str,
        causation_id: str,
        idempotency_key_digest: str,
        cancellation_token: CancellationToken,
        policy_key: str,
        policy_version: int,
        policy_manifest_digest: str,
        provider_type: ProviderType,
        adapter_key: str,
        adapter_version: str,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> "ProviderCallContext":
        started_monotonic = monotonic()
        return cls(
            workspace_id=workspace_id,
            connection_id=connection_id,
            service_actor=ActorRef(ActorType.SERVICE, PROVIDER_REGISTRY_SERVICE_ACTOR_ID),
            effective_principal=effective_principal,
            classification=DataClassification.INTERNAL,
            correlation_id=correlation_id,
            causation_id=causation_id,
            idempotency_key_digest=idempotency_key_digest,
            started_monotonic=started_monotonic,
            deadline_monotonic=started_monotonic + TOTAL_RECONCILIATION_DEADLINE_SECONDS,
            cancellation_token=cancellation_token,
            policy_key=policy_key,
            policy_version=policy_version,
            policy_manifest_digest=policy_manifest_digest,
            provider_type=provider_type,
            adapter_key=adapter_key,
            adapter_version=adapter_version,
        )


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    name: str
    risk: ProviderCapabilityRisk
    enabled: bool
    schema_uri: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _CAPABILITY_NAME_PATTERN.fullmatch(self.name) is None:
            raise ValueError("invalid capability name")
        if not isinstance(self.risk, ProviderCapabilityRisk):
            raise ValueError("invalid capability risk")
        if type(self.enabled) is not bool:
            raise ValueError("invalid capability enabled")
        if self.schema_uri is not None and (not isinstance(self.schema_uri, str) or not self.schema_uri):
            raise ValueError("invalid capability schema_uri")


@dataclass(frozen=True, slots=True)
class ProviderCapabilityObservation:
    workspace_id: str
    connection_id: str
    provider_type: ProviderType
    adapter_key: str
    adapter_version: str
    protocol_versions: tuple[str, ...]
    capabilities: tuple[ProviderCapability, ...]
    allowed_classifications: tuple[DataClassification, ...]

    def __post_init__(self) -> None:
        _require_uuid(self.workspace_id, "workspace_id")
        _require_uuid(self.connection_id, "connection_id")
        if not isinstance(self.provider_type, ProviderType):
            raise ValueError("invalid provider_type")
        _require_adapter_key(self.adapter_key)
        _require_adapter_version(self.adapter_version)
        if type(self.protocol_versions) is not tuple or not self.protocol_versions:
            raise ValueError("invalid protocol_versions")
        if any(not isinstance(value, str) or not value for value in self.protocol_versions):
            raise ValueError("invalid protocol_versions")
        if len(set(self.protocol_versions)) != len(self.protocol_versions):
            raise ValueError("invalid protocol_versions")
        if type(self.capabilities) is not tuple or not self.capabilities:
            raise ValueError("invalid capabilities")
        if any(not isinstance(value, ProviderCapability) for value in self.capabilities):
            raise ValueError("invalid capabilities")
        capability_keys = {
            (value.name, value.risk.value, value.enabled, value.schema_uri) for value in self.capabilities
        }
        if len(capability_keys) != len(self.capabilities):
            raise ValueError("invalid capabilities")
        if type(self.allowed_classifications) is not tuple or not self.allowed_classifications:
            raise ValueError("invalid allowed_classifications")
        if any(not isinstance(value, DataClassification) for value in self.allowed_classifications):
            raise ValueError("invalid allowed_classifications")
        if DataClassification.UNKNOWN in self.allowed_classifications:
            raise ValueError("invalid allowed_classifications")
        if len(set(self.allowed_classifications)) != len(self.allowed_classifications):
            raise ValueError("invalid allowed_classifications")

    @property
    def capability_digest(self) -> str:
        payload = {
            "adapter_key": self.adapter_key,
            "adapter_version": self.adapter_version,
            "allowed_classifications": [value.value for value in self.allowed_classifications],
            "capabilities": [
                {
                    "enabled": capability.enabled,
                    "name": capability.name,
                    "risk": capability.risk.value,
                    **({"schema_uri": capability.schema_uri} if capability.schema_uri is not None else {}),
                }
                for capability in self.capabilities
            ],
            "connection_id": self.connection_id,
            "protocol_versions": list(self.protocol_versions),
            "provider_type": self.provider_type.value,
            "workspace_id": self.workspace_id,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True, slots=True)
class ProviderObservationRef:
    workspace_id: str
    connection_id: str
    provider_type: ProviderType
    adapter_key: str
    adapter_version: str
    capability_digest: str

    def __post_init__(self) -> None:
        _require_uuid(self.workspace_id, "workspace_id")
        _require_uuid(self.connection_id, "connection_id")
        if not isinstance(self.provider_type, ProviderType):
            raise ValueError("invalid provider_type")
        _require_adapter_key(self.adapter_key)
        _require_adapter_version(self.adapter_version)
        _require_digest(self.capability_digest, "capability_digest")

    @classmethod
    def from_observation(cls, observation: ProviderCapabilityObservation) -> "ProviderObservationRef":
        return cls(
            workspace_id=observation.workspace_id,
            connection_id=observation.connection_id,
            provider_type=observation.provider_type,
            adapter_key=observation.adapter_key,
            adapter_version=observation.adapter_version,
            capability_digest=observation.capability_digest,
        )


@dataclass(frozen=True, slots=True)
class ProviderReconciliationObservation:
    capability_observation: ProviderCapabilityObservation
    changed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.capability_observation, ProviderCapabilityObservation):
            raise ValueError("invalid capability_observation")
        if type(self.changed) is not bool:
            raise ValueError("invalid changed")


@dataclass(frozen=True, slots=True)
class NormalizedProviderError:
    code: ProviderErrorCode
    retryable: bool = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.code, ProviderErrorCode):
            raise ValueError("invalid provider error code")
        object.__setattr__(self, "retryable", self.code in RETRYABLE_PROVIDER_ERROR_CODES)


class ProviderAdapterError(RuntimeError):
    def __init__(self, error: NormalizedProviderError) -> None:
        if not isinstance(error, NormalizedProviderError):
            raise TypeError("invalid normalized provider error")
        self.error = error
        super().__init__(error.code.value)


@runtime_checkable
class ProviderAdapter(Protocol):
    adapter_key: str
    provider_type: ProviderType
    adapter_version: str

    def describe_capabilities(self, context: ProviderCallContext) -> ProviderCapabilityObservation: ...

    def reconcile(
        self,
        context: ProviderCallContext,
        previous: ProviderObservationRef | None,
    ) -> ProviderReconciliationObservation: ...
