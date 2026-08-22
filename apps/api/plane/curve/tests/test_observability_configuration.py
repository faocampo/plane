# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import base64
import json
import uuid

import pytest

from plane.curve.observability.configuration import TelemetryMode, load_telemetry_configuration
from plane.curve.observability.redaction import contains_forbidden_name, sanitize_attributes
from plane.curve.observability.scope import workspace_scope
from plane.curve.observability.structured_logging import CurveStructuredLogger


pytestmark = pytest.mark.unit


SCOPE_KEY = b"curve-observability-test-key-32b"
SCOPE_KEY_B64 = base64.urlsafe_b64encode(SCOPE_KEY).rstrip(b"=").decode("ascii")


def _environment(**overrides):
    return {
        "CURVE_ENVIRONMENT": "LOCAL",
        "CURVE_TELEMETRY_MODE": "IN_MEMORY_TEST",
        "CURVE_TELEMETRY_SCOPE_HMAC_KEY": SCOPE_KEY_B64,
        "CURVE_TELEMETRY_SCOPE_KEY_ID": "test-key-v1",
        **overrides,
    }


def test_disabled_default_ignores_generic_otel_and_plane_telemetry_values():
    configuration = load_telemetry_configuration(
        component="API",
        environ={
            "CURVE_ENVIRONMENT": "LOCAL",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://unapproved.invalid",
            "TELEMETRY_ENABLED": "1",
        },
    )

    assert configuration.mode is TelemetryMode.DISABLED
    assert configuration.error_code is None
    assert configuration.endpoint is None
    assert configuration.workspace_scope_key is None


def test_in_memory_configuration_requires_an_explicit_synthetic_scope_pair():
    valid = load_telemetry_configuration(component="API", environ=_environment())
    missing = load_telemetry_configuration(
        component="API",
        environ={"CURVE_ENVIRONMENT": "LOCAL", "CURVE_TELEMETRY_MODE": "IN_MEMORY_TEST"},
    )

    assert valid.mode is TelemetryMode.IN_MEMORY_TEST
    assert valid.workspace_scope_key == SCOPE_KEY
    assert valid.workspace_scope_key_id == "test-key-v1"
    assert missing.mode is TelemetryMode.DISABLED
    assert missing.error_code == "CURVE_TELEMETRY_CONFIGURATION_INVALID"


@pytest.mark.parametrize(
    "overrides",
    [
        {"CURVE_TELEMETRY_MODE": "in_memory_test"},
        {"CURVE_TELEMETRY_SCOPE_HMAC_KEY": "not+base64url"},
        {"CURVE_TELEMETRY_SCOPE_HMAC_KEY": base64.urlsafe_b64encode(b"short").rstrip(b"=").decode()},
        {"CURVE_TELEMETRY_SCOPE_KEY_ID": "invalid key id"},
    ],
)
def test_invalid_configuration_fails_closed_without_echoing_values(overrides):
    environment = _environment(**overrides)
    configuration = load_telemetry_configuration(component="API", environ=environment)

    assert configuration.mode is TelemetryMode.DISABLED
    assert configuration.error_code == "CURVE_TELEMETRY_CONFIGURATION_INVALID"
    assert all(value not in repr(configuration) for value in overrides.values())


@pytest.mark.parametrize(
    ("endpoint", "protocol", "insecure", "environment", "enabled"),
    [
        ("http://collector:4317", "grpc", "true", "LOCAL", True),
        ("http://collector:4318/otel", "http/protobuf", "true", "LOCAL", True),
        ("https://collector:4317", "grpc", "false", "LOCAL", True),
        ("http://collector:4317/path", "grpc", "true", "LOCAL", False),
        ("http://collector:4318/v1/traces", "http/protobuf", "true", "LOCAL", False),
        ("http://user:pass@collector:4317", "grpc", "true", "LOCAL", False),
        ("http://collector:4317?token=value", "grpc", "true", "LOCAL", False),
        ("http://collector:4317", "grpc", "true", "STAGING", False),
        ("http://collector:4317", "grpc", "false", "LOCAL", False),
    ],
)
def test_otlp_endpoint_and_transport_matrix(endpoint, protocol, insecure, environment, enabled):
    configuration = load_telemetry_configuration(
        component="TEMPORAL_WORKER",
        environ=_environment(
            CURVE_ENVIRONMENT=environment,
            CURVE_TELEMETRY_MODE="OTLP",
            CURVE_OTEL_EXPORTER_OTLP_ENDPOINT=endpoint,
            CURVE_OTEL_EXPORTER_OTLP_PROTOCOL=protocol,
            CURVE_OTEL_EXPORTER_OTLP_INSECURE=insecure,
        ),
    )

    assert configuration.enabled is enabled


def test_otel_sdk_kill_switch_can_only_disable_curve_telemetry():
    configuration = load_telemetry_configuration(
        component="API",
        environ=_environment(OTEL_SDK_DISABLED="true"),
    )

    assert configuration.mode is TelemetryMode.DISABLED
    assert configuration.error_code is None


@pytest.mark.parametrize(
    "headers",
    [
        "bad header=value",
        "bad:header=value",
        "duplicate=one,DUPLICATE=two",
        "missing-separator",
        "broken=%ZZ",
    ],
)
def test_invalid_otlp_headers_fail_closed(headers):
    configuration = load_telemetry_configuration(
        component="API",
        environ=_environment(
            CURVE_TELEMETRY_MODE="OTLP",
            CURVE_OTEL_EXPORTER_OTLP_ENDPOINT="http://collector:4318/otel",
            CURVE_OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf",
            CURVE_OTEL_EXPORTER_OTLP_INSECURE="true",
            CURVE_OTEL_EXPORTER_OTLP_HEADERS=headers,
        ),
    )

    assert not configuration.enabled


def test_tls_files_must_be_absolute_bounded_read_only_and_complete(tmp_path):
    certificate = tmp_path / "client.pem"
    key = tmp_path / "client.key"
    certificate.write_bytes(b"certificate")
    key.write_bytes(b"key")
    certificate.chmod(0o400)
    key.chmod(0o400)
    common = {
        "CURVE_TELEMETRY_MODE": "OTLP",
        "CURVE_OTEL_EXPORTER_OTLP_ENDPOINT": "https://collector:4317",
        "CURVE_OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
        "CURVE_OTEL_EXPORTER_OTLP_INSECURE": "false",
    }

    valid = load_telemetry_configuration(
        component="TEMPORAL_WORKER",
        environ=_environment(
            **common,
            CURVE_OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE=str(certificate),
            CURVE_OTEL_EXPORTER_OTLP_CLIENT_KEY=str(key),
        ),
    )
    partial = load_telemetry_configuration(
        component="TEMPORAL_WORKER",
        environ=_environment(
            **common,
            CURVE_OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE=str(certificate),
        ),
    )
    key.chmod(0o600)
    writable = load_telemetry_configuration(
        component="TEMPORAL_WORKER",
        environ=_environment(
            **common,
            CURVE_OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE=str(certificate),
            CURVE_OTEL_EXPORTER_OTLP_CLIENT_KEY=str(key),
        ),
    )

    assert valid.enabled
    assert not partial.enabled
    assert not writable.enabled


def test_workspace_scope_is_stable_distinct_and_contains_no_raw_uuid():
    first_id = uuid.UUID("10000000-0000-4000-8000-000000000001")
    second_id = uuid.UUID("10000000-0000-4000-8000-000000000002")

    first = workspace_scope(workspace_id=first_id, key=SCOPE_KEY)
    repeated = workspace_scope(workspace_id=str(first_id), key=SCOPE_KEY)
    second = workspace_scope(workspace_id=second_id, key=SCOPE_KEY)

    assert first == repeated
    assert first != second
    assert str(first_id) not in first
    assert len(first) == 43


def test_trace_and_metric_attributes_use_closed_allowlists():
    operation_id = str(uuid.uuid4())
    safe_trace = sanitize_attributes(
        signal="trace",
        allowed_names=frozenset({"curve.component", "curve.operation.id", "curve.error.code"}),
        attributes={
            "curve.component": "API",
            "curve.operation.id": operation_id,
            "curve.error.code": "NONE",
            "request_body": "DO_NOT_EXPORT",
            "unknown": "VALUE",
        },
    )
    safe_metric = sanitize_attributes(
        signal="metric",
        allowed_names=frozenset({"curve.component", "curve.result"}),
        attributes={"curve.component": "API", "curve.result": "SUCCEEDED", "curve.operation.id": operation_id},
    )

    assert safe_trace == {
        "curve.component": "API",
        "curve.operation.id": operation_id,
        "curve.error.code": "NONE",
    }
    assert safe_metric == {"curve.component": "API", "curve.result": "SUCCEEDED"}
    assert contains_forbidden_name({"nested": {"authorization": "sentinel"}})


def test_structured_log_is_bounded_workspace_scoped_and_sentinel_free():
    workspace_id = uuid.uuid4()
    logger = CurveStructuredLogger(
        component="API",
        scope_key=SCOPE_KEY,
        scope_key_id="test-key-v1",
    )

    rendered = logger.render(
        event_code="CURVE_COMMAND_ACCEPTED",
        level="INFO",
        workspace_id=workspace_id,
        attributes={
            "curve.command.type": "CREATE_FOUNDATION_PROBE",
            "request_body": "CURVE_SENTINEL_REQUEST_BODY",
            "token": "CURVE_SENTINEL_TOKEN",
        },
    )
    payload = json.loads(rendered)

    assert payload["curve.event.code"] == "CURVE_COMMAND_ACCEPTED"
    assert payload["curve.workspace.scope"] == workspace_scope(workspace_id=workspace_id, key=SCOPE_KEY)
    assert str(workspace_id) not in rendered
    assert "CURVE_SENTINEL" not in rendered
    assert len(rendered.encode()) <= 2048
