# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Prepared Feature event construction from server-owned snapshots."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from plane.curve.feature_input import normalize_feature_command


_SCHEMA_BYTES = (Path(__file__).parent / "features/command-event-v1.schema.json").read_bytes()
if hashlib.sha256(_SCHEMA_BYTES).hexdigest() != "2f132769b6107b300620e584b5ccaa46b047b4827764d5484b62cecf6b1da0c8":
    raise RuntimeError("FEATURE_EVENT_CONTRACT_CHANGED")
_SCHEMA = json.loads(_SCHEMA_BYTES)
Draft202012Validator.check_schema(_SCHEMA)
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())


class FeatureEventError(ValueError):
    pass


def build_feature_event(*, action, workspace_id, product_id, before, after, actor, occurred_at):
    event = deepcopy(
        {
            "schema_version": "1.0",
            "workspace_id": str(workspace_id),
            "product_id": str(product_id),
            "action": action,
            "before": before,
            "after": after,
            "actor": actor,
            "occurred_at": occurred_at,
        }
    )
    _VALIDATOR.validate(event)
    old, new = event["before"], event["after"]
    for snapshot in (old, new):
        if snapshot is not None:
            normalize_feature_command(
                "UPDATE_FEATURE",
                {"name": snapshot["name"], "description": snapshot["description"]},
                snapshot["resource_version"],
            )
    if action == "UPDATE_FEATURE":
        if old["resource_id"] != new["resource_id"]:
            raise FeatureEventError("FEATURE_IDENTITY_CHANGED")
        if new["resource_version"] != old["resource_version"] + 1:
            raise FeatureEventError("FEATURE_VERSION_NOT_SUCCESSOR")
    return event
