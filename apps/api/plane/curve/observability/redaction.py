# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import re
import uuid
from collections.abc import Mapping

from plane.curve.observability.manifest import telemetry_manifest


_HEX_TRACE = re.compile(r"^[0-9a-f]{32}$")
_HEX_SPAN = re.compile(r"^[0-9a-f]{16}$")
_SCOPE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_STABLE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


def _manifest_policy():
    manifest = telemetry_manifest()
    metric_values = {item["name"]: frozenset(item["allowed_values"]) for item in manifest["metric_attributes"]}
    forbidden_patterns = tuple(
        re.compile(value, re.IGNORECASE) for value in manifest["attribute_policy"]["forbidden_name_patterns"]
    )
    return manifest, metric_values, forbidden_patterns


def _safe_scalar(name: str, value) -> bool:
    if isinstance(value, bool):
        return name in {"curve.cancel.requested", "curve.replayed"}
    if isinstance(value, int):
        return name == "curve.retry.attempt" and 0 <= value <= 1_000
    if not isinstance(value, str) or len(value.encode("utf-8")) > 128:
        return False
    if name in {"curve.operation.id", "curve.event.id"}:
        try:
            uuid.UUID(value)
            return True
        except ValueError:
            return False
    if name == "curve.workspace.scope":
        return _SCOPE.fullmatch(value) is not None
    if name == "trace.id":
        return _HEX_TRACE.fullmatch(value) is not None
    if name == "span.id":
        return _HEX_SPAN.fullmatch(value) is not None
    if name == "log.level":
        return value in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if name == "curve.event.code":
        return _STABLE.fullmatch(value) is not None
    if name == "curve.telemetry.scope_key_id":
        return re.fullmatch(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$", value) is not None
    return _STABLE.fullmatch(value) is not None


def sanitize_attributes(*, signal: str, allowed_names: set[str] | frozenset[str], attributes: Mapping) -> dict:
    """Return only bounded values approved for the named signal."""

    manifest, metric_values, forbidden_patterns = _manifest_policy()
    global_allowlist = (
        set(metric_values) if signal == "metric" else set(manifest["attribute_policy"][f"{signal}_allowlist"])
    )
    safe = {}
    for name, value in attributes.items():
        if name not in allowed_names or name not in global_allowlist:
            continue
        if any(pattern.search(name) for pattern in forbidden_patterns) or not _safe_scalar(name, value):
            continue
        if signal == "metric" and value not in metric_values.get(name, frozenset()):
            continue
        safe[name] = value
    return safe


def contains_forbidden_name(value) -> bool:
    _, _, forbidden_patterns = _manifest_policy()
    if isinstance(value, Mapping):
        return any(
            any(pattern.search(str(key)) for pattern in forbidden_patterns) or contains_forbidden_name(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set)):
        return any(contains_forbidden_name(item) for item in value)
    return False
