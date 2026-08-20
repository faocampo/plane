# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import re
import uuid
from dataclasses import dataclass


SAFE_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
SAFE_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,99}$")
SUPPORTED_OPERATION_TYPES = frozenset({"FOUNDATION_PROBE"})


def _require_uuid(value: str, field: str) -> None:
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError(f"invalid {field}") from error
    if str(parsed) != value:
        raise ValueError(f"invalid {field}")


def _require_safe_reference(value: str, field: str) -> None:
    if not isinstance(value, str) or SAFE_REFERENCE_PATTERN.fullmatch(value) is None:
        raise ValueError(f"invalid {field}")


def _require_positive_version(value: int, field: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"invalid {field}")


@dataclass(frozen=True, slots=True)
class CurveOperationWorkflowInputV1:
    schema_version: str
    workspace_id: str
    operation_id: str
    operation_version: int
    operation_type: str
    correlation_id: str

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("invalid schema_version")
        _require_uuid(self.workspace_id, "workspace_id")
        _require_uuid(self.operation_id, "operation_id")
        _require_positive_version(self.operation_version, "operation_version")
        if self.operation_type not in SUPPORTED_OPERATION_TYPES:
            raise ValueError("invalid operation_type")
        _require_safe_reference(self.correlation_id, "correlation_id")


@dataclass(frozen=True, slots=True)
class OperationActivityInputV1:
    schema_version: str
    workspace_id: str
    operation_id: str
    operation_version: int
    correlation_id: str
    command_id: str

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("invalid schema_version")
        _require_uuid(self.workspace_id, "workspace_id")
        _require_uuid(self.operation_id, "operation_id")
        _require_positive_version(self.operation_version, "operation_version")
        _require_safe_reference(self.correlation_id, "correlation_id")
        _require_safe_reference(self.command_id, "command_id")


@dataclass(frozen=True, slots=True)
class OperationActivityResultV1:
    schema_version: str
    operation_status: str
    operation_version: int
    effect_applied: bool
    result_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("invalid schema_version")
        if not isinstance(self.operation_status, str) or SAFE_CODE_PATTERN.fullmatch(self.operation_status) is None:
            raise ValueError("invalid operation_status")
        _require_positive_version(self.operation_version, "operation_version")
        if type(self.effect_applied) is not bool:
            raise ValueError("invalid effect_applied")
        if not isinstance(self.result_digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", self.result_digest) is None:
            raise ValueError("invalid result_digest")


@dataclass(frozen=True, slots=True)
class CancelSignalV1:
    schema_version: str
    actor_ref: str
    reason_code: str
    command_id: str

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("invalid schema_version")
        _require_safe_reference(self.actor_ref, "actor_ref")
        if self.reason_code not in {"USER_REQUESTED", "TEST_REQUESTED", "STATE_RECONCILIATION"}:
            raise ValueError("invalid reason_code")
        _require_safe_reference(self.command_id, "command_id")


@dataclass(frozen=True, slots=True)
class RefreshOperationSignalV1:
    schema_version: str
    operation_version: int
    event_id: str

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("invalid schema_version")
        _require_positive_version(self.operation_version, "operation_version")
        _require_uuid(self.event_id, "event_id")


@dataclass(frozen=True, slots=True)
class WorkflowStateV1:
    schema_version: str
    phase: str
    last_observed_operation_version: int
    cancellation_requested: bool


@dataclass(frozen=True, slots=True)
class WorkflowResultV1:
    schema_version: str
    operation_status: str
    operation_version: int
    result_digest: str
