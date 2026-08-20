# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import dataclasses
import uuid

import pytest

from plane.curve.temporal.contracts import (
    CancelSignalV1,
    CurveOperationWorkflowInputV1,
    OperationActivityInputV1,
)
from plane.curve.temporal.environment import validate_worker_environment
from plane.curve.temporal.proof import _argument_parser


pytestmark = pytest.mark.unit


def _workflow_input(**overrides):
    values = {
        "schema_version": "1.0",
        "workspace_id": str(uuid.uuid4()),
        "operation_id": str(uuid.uuid4()),
        "operation_version": 2,
        "operation_type": "FOUNDATION_PROBE",
        "correlation_id": "synthetic-local-proof",
    }
    values.update(overrides)
    return CurveOperationWorkflowInputV1(**values)


def test_workflow_payload_is_exact_safe_identifier_contract():
    payload = dataclasses.asdict(_workflow_input())

    assert set(payload) == {
        "schema_version",
        "workspace_id",
        "operation_id",
        "operation_version",
        "operation_type",
        "correlation_id",
    }
    assert not any(key in payload for key in {"body", "secret", "credential", "prompt", "source"})


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema_version": "2.0"},
        {"workspace_id": "not-a-uuid"},
        {"operation_version": 0},
        {"operation_type": "BUSINESS_WORKFLOW"},
        {"correlation_id": "protected body with spaces"},
    ],
)
def test_workflow_payload_rejects_unapproved_values(overrides):
    with pytest.raises(ValueError):
        _workflow_input(**overrides)


def test_signal_and_activity_payloads_reject_free_text():
    with pytest.raises(ValueError):
        CancelSignalV1(
            schema_version="1.0",
            actor_ref="developer:1",
            reason_code="because this includes free text",
            command_id="cancel:1",
        )
    with pytest.raises(ValueError):
        OperationActivityInputV1(
            schema_version="1.0",
            workspace_id=str(uuid.uuid4()),
            operation_id=str(uuid.uuid4()),
            operation_version=1,
            correlation_id="safe",
            command_id="protected body",
        )


def _worker_environment(**overrides):
    values = {
        "DJANGO_SETTINGS_MODULE": "plane.settings.curve_worker",
        "DATABASE_URL": "postgresql://curve@plane-db:5432/plane",
        "CURVE_ENABLED": "1",
        "CURVE_ENABLED_WORKSPACE_SLUGS": "curve-local-proof",
        "TEMPORAL_ADDRESS": "temporal:7233",
        "TEMPORAL_NAMESPACE": "curve-local",
        "TEMPORAL_TASK_QUEUE": "curve-control-plane-v1",
        "TEMPORAL_WORKER_IDENTITY": "curve-worker-test",
        "LOG_LEVEL": "INFO",
    }
    values.update(overrides)
    return values


def test_worker_environment_accepts_exact_application_allowlist():
    validate_worker_environment(_worker_environment())


def test_proof_cli_defaults_to_the_required_round_trip():
    assert _argument_parser().parse_args([]).command == "run"


@pytest.mark.parametrize("forbidden", ["REDIS_URL", "AWS_SECRET_ACCESS_KEY", "GITHUB_ACCESS_TOKEN", "OPENAI_API_KEY"])
def test_worker_environment_rejects_unapproved_credentials_and_endpoints(forbidden):
    with pytest.raises(RuntimeError, match="forbidden environment"):
        validate_worker_environment(_worker_environment(**{forbidden: "must-not-load"}))
