# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class PolicyEffect(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_HUMAN_CONFIRMATION = "REQUIRE_HUMAN_CONFIRMATION"


class DataClassification(StrEnum):
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class PolicyEvaluationResult:
    effect: PolicyEffect
    reason_codes: tuple[str, ...]
    normalized_classification: DataClassification
    permitted_projection: tuple[str, ...]
    input_digest: str
    evaluated_at: str
    policy_key: str
    policy_version: int
    policy_manifest_digest: str

    def as_mapping(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "effect": self.effect.value,
                "reason_codes": self.reason_codes,
                "normalized_classification": self.normalized_classification.value,
                "permitted_projection": self.permitted_projection,
                "input_digest": self.input_digest,
                "evaluated_at": self.evaluated_at,
                "policy_key": self.policy_key,
                "policy_version": self.policy_version,
                "policy_manifest_digest": self.policy_manifest_digest,
            }
        )
