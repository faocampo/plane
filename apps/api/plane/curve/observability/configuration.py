# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import base64
import os
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Mapping
from urllib.parse import unquote, urlsplit

from plane.curve.observability.manifest import telemetry_manifest


class TelemetryMode(StrEnum):
    DISABLED = "DISABLED"
    IN_MEMORY_TEST = "IN_MEMORY_TEST"
    OTLP = "OTLP"


class TelemetryComponent(StrEnum):
    API = "API"
    TEMPORAL_WORKER = "TEMPORAL_WORKER"


@dataclass(frozen=True, slots=True)
class TelemetryConfiguration:
    mode: TelemetryMode
    component: TelemetryComponent
    environment: str
    endpoint: str | None = None
    protocol: str | None = None
    insecure: bool = False
    headers: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    certificate: str | None = field(default=None, repr=False)
    client_certificate: str | None = field(default=None, repr=False)
    client_key: str | None = field(default=None, repr=False)
    workspace_scope_key: bytes | None = field(default=None, repr=False)
    workspace_scope_key_id: str | None = None
    error_code: str | None = None

    @property
    def enabled(self) -> bool:
        return self.mode is not TelemetryMode.DISABLED and self.error_code is None


class _InvalidTelemetryConfiguration(ValueError):
    pass


_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_BASE64URL_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_MAX_TLS_BYTES = 1_048_576


def _disabled(component: TelemetryComponent, environment: str, *, invalid: bool = False) -> TelemetryConfiguration:
    return TelemetryConfiguration(
        mode=TelemetryMode.DISABLED,
        component=component,
        environment=environment,
        error_code="CURVE_TELEMETRY_CONFIGURATION_INVALID" if invalid else None,
    )


def _parse_scope(environ: Mapping[str, str]) -> tuple[bytes, str]:
    encoded = environ.get("CURVE_TELEMETRY_SCOPE_HMAC_KEY", "")
    key_id = environ.get("CURVE_TELEMETRY_SCOPE_KEY_ID", "")
    if not encoded or not key_id or "=" in encoded or _BASE64URL_PATTERN.fullmatch(encoded) is None:
        raise _InvalidTelemetryConfiguration
    try:
        key = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (ValueError, TypeError) as error:
        raise _InvalidTelemetryConfiguration from error
    if not 32 <= len(key) <= 64 or base64.urlsafe_b64encode(key).rstrip(b"=").decode("ascii") != encoded:
        raise _InvalidTelemetryConfiguration
    if _KEY_ID_PATTERN.fullmatch(key_id) is None:
        raise _InvalidTelemetryConfiguration
    return key, key_id


def _parse_headers(raw: str) -> tuple[tuple[str, str], ...]:
    if not raw:
        return ()
    headers = []
    names = set()
    for item in raw.split(","):
        if item.count("=") != 1 or _INVALID_PERCENT_ESCAPE.search(item):
            raise _InvalidTelemetryConfiguration
        raw_name, raw_value = item.split("=", 1)
        name = unquote(raw_name)
        value = unquote(raw_value)
        canonical = name.lower()
        if not name or not value or canonical in names or _HEADER_NAME_PATTERN.fullmatch(name) is None:
            raise _InvalidTelemetryConfiguration
        if any(ord(character) < 32 or ord(character) == 127 for character in name + value):
            raise _InvalidTelemetryConfiguration
        names.add(canonical)
        headers.append((name, value))
    return tuple(headers)


def _parse_tls_path(value: str) -> str:
    path = Path(value)
    try:
        stat = path.stat()
    except OSError as error:
        raise _InvalidTelemetryConfiguration from error
    if not path.is_absolute() or not path.is_file() or stat.st_size > _MAX_TLS_BYTES or stat.st_mode & 0o222:
        raise _InvalidTelemetryConfiguration
    return str(path)


def _parse_otlp(environ: Mapping[str, str], *, environment: str) -> dict:
    endpoint = environ.get("CURVE_OTEL_EXPORTER_OTLP_ENDPOINT", "")
    protocol = environ.get("CURVE_OTEL_EXPORTER_OTLP_PROTOCOL", "")
    insecure_raw = environ.get("CURVE_OTEL_EXPORTER_OTLP_INSECURE", "")
    if protocol not in {"grpc", "http/protobuf"} or insecure_raw not in {"true", "false"}:
        raise _InvalidTelemetryConfiguration
    parsed = urlsplit(endpoint)
    try:
        port = parsed.port
    except ValueError as error:
        raise _InvalidTelemetryConfiguration from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port is not None
        and not 1 <= port <= 65535
    ):
        raise _InvalidTelemetryConfiguration
    if protocol == "grpc" and parsed.path not in {"", "/"}:
        raise _InvalidTelemetryConfiguration
    if protocol == "http/protobuf" and parsed.path.rstrip("/").endswith(("/v1/traces", "/v1/metrics")):
        raise _InvalidTelemetryConfiguration
    insecure = insecure_raw == "true"
    if insecure and (environment != "LOCAL" or parsed.scheme != "http"):
        raise _InvalidTelemetryConfiguration
    if not insecure and parsed.scheme != "https":
        raise _InvalidTelemetryConfiguration

    certificate_raw = environ.get("CURVE_OTEL_EXPORTER_OTLP_CERTIFICATE", "")
    client_certificate_raw = environ.get("CURVE_OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE", "")
    client_key_raw = environ.get("CURVE_OTEL_EXPORTER_OTLP_CLIENT_KEY", "")
    if (
        bool(client_certificate_raw) != bool(client_key_raw)
        or insecure
        and any((certificate_raw, client_certificate_raw, client_key_raw))
    ):
        raise _InvalidTelemetryConfiguration
    return {
        "endpoint": endpoint.rstrip("/"),
        "protocol": protocol,
        "insecure": insecure,
        "headers": _parse_headers(environ.get("CURVE_OTEL_EXPORTER_OTLP_HEADERS", "")),
        "certificate": _parse_tls_path(certificate_raw) if certificate_raw else None,
        "client_certificate": _parse_tls_path(client_certificate_raw) if client_certificate_raw else None,
        "client_key": _parse_tls_path(client_key_raw) if client_key_raw else None,
    }


def load_telemetry_configuration(
    *,
    component: str,
    environ: Mapping[str, str] | None = None,
) -> TelemetryConfiguration:
    """Parse only Curve-owned inputs and fail closed without exposing values."""

    telemetry_manifest()
    values = os.environ if environ is None else environ
    try:
        parsed_component = TelemetryComponent(component)
    except ValueError:
        parsed_component = TelemetryComponent.API
        return _disabled(parsed_component, "UNKNOWN", invalid=True)
    environment = values.get("CURVE_ENVIRONMENT", "").upper()
    requested = values.get("CURVE_TELEMETRY_MODE", "") or TelemetryMode.DISABLED.value
    if values.get("OTEL_SDK_DISABLED", "").lower() == "true":
        return _disabled(parsed_component, environment)
    try:
        mode = TelemetryMode(requested)
        if mode is TelemetryMode.DISABLED:
            return _disabled(parsed_component, environment)
        scope_key, scope_key_id = _parse_scope(values)
        otlp = _parse_otlp(values, environment=environment) if mode is TelemetryMode.OTLP else {}
        return TelemetryConfiguration(
            mode=mode,
            component=parsed_component,
            environment=environment,
            workspace_scope_key=scope_key,
            workspace_scope_key_id=scope_key_id,
            **otlp,
        )
    except (ValueError, _InvalidTelemetryConfiguration):
        return _disabled(parsed_component, environment, invalid=True)
