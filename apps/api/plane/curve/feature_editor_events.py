# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Closed Feature editor events from server-resolved command snapshots.

The command adapter supplies its live authorization receipt separately. Event
construction cannot authorize a write or accept client-owned authority facts.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


_SCHEMA_BYTES = (Path(__file__).parent / "feature_editors/command-event-v1.schema.json").read_bytes()
if hashlib.sha256(_SCHEMA_BYTES).hexdigest() != "1f2ddeb982b2a8554027174dc83d5051ea21cde1c48a35b70cb0004b25f50048":
    raise RuntimeError("FEATURE_EDITOR_EVENT_CONTRACT_CHANGED")
_VALIDATOR = Draft202012Validator(json.loads(_SCHEMA_BYTES), format_checker=FormatChecker())


class FeatureEditorEventError(ValueError):
    pass


def build_editor_event(*, action, workspace_id, product_id, before, after, actor, occurred_at):
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
    if action == "GRANT_FEATURE_EDITOR":
        if new["granted_by"] != event["actor"]["actor_id"]:
            raise FeatureEditorEventError("FEATURE_EDITOR_GRANT_ACTOR_MISMATCH")
    else:
        mutable = {"resource_version", "revoked_by", "revoked_at"}
        if {key: value for key, value in old.items() if key not in mutable} != {
            key: value for key, value in new.items() if key not in mutable
        }:
            raise FeatureEditorEventError("FEATURE_EDITOR_GRANT_HISTORY_CHANGED")
        if new["revoked_by"] != event["actor"]["actor_id"]:
            raise FeatureEditorEventError("FEATURE_EDITOR_REVOCATION_ACTOR_MISMATCH")
    return event
