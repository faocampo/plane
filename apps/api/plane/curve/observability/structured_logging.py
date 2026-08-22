# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
import logging
import uuid

from plane.curve.observability.manifest import telemetry_manifest
from plane.curve.observability.redaction import sanitize_attributes
from plane.curve.observability.scope import workspace_scope


class CurveStructuredLogger:
    def __init__(self, *, component: str, scope_key: bytes | None, scope_key_id: str | None, logger=None):
        self._component = component
        self._scope_key = scope_key
        self._scope_key_id = scope_key_id
        self._logger = logger or logging.getLogger("plane.curve.observability")

    def render(self, *, event_code: str, level: str, workspace_id: uuid.UUID | None = None, attributes=None) -> str:
        manifest = telemetry_manifest()
        log_contract = manifest["logs"]
        if event_code not in log_contract["event_codes"]:
            raise ValueError("unsupported Curve telemetry event code")
        fields = {
            "curve.component": self._component,
            "curve.event.code": event_code,
            "log.level": level,
            **(attributes or {}),
        }
        if event_code in log_contract["workspace_scoped_event_codes"]:
            if workspace_id is None or self._scope_key is None or self._scope_key_id is None:
                raise ValueError("workspace telemetry scope is unavailable")
            fields["curve.workspace.scope"] = workspace_scope(workspace_id=workspace_id, key=self._scope_key)
            fields["curve.telemetry.scope_key_id"] = self._scope_key_id
        safe = sanitize_attributes(
            signal="log",
            allowed_names=frozenset(manifest["attribute_policy"]["log_allowlist"]),
            attributes=fields,
        )
        required = set(log_contract["common_required_fields"])
        if event_code in log_contract["workspace_scoped_event_codes"]:
            required.update(log_contract["workspace_required_fields"])
        if not required.issubset(safe):
            raise ValueError("required Curve structured-log fields are unavailable")
        rendered = json.dumps(safe, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        if len(rendered.encode("utf-8")) > log_contract["maximum_serialized_bytes"]:
            raise ValueError("Curve structured log exceeds the byte limit")
        return rendered

    def emit(self, **kwargs) -> str:
        rendered = self.render(**kwargs)
        self._logger.log(getattr(logging, kwargs["level"]), rendered)
        return rendered
