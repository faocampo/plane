# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Pinned joint creation event; draft content stays out of event projections."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from plane.curve.item_creation_results import validate_pair_reference

_SCHEMA_BYTES = (Path(__file__).parent / "items/creation-event-v1.schema.json").read_bytes()
if hashlib.sha256(_SCHEMA_BYTES).hexdigest() != "32f14b6a44545acd9ccddb32cba991189e91b5801c08c2d52f8b3f1fc6a1fc79":
    raise RuntimeError("ITEM_CREATION_EVENT_CONTRACT_CHANGED")
_SCHEMA = json.loads(_SCHEMA_BYTES)
Draft202012Validator.check_schema(_SCHEMA)
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())


def build_item_creation_event(
    *, workspace_id, product_id, roadmap_id, milestone_id, feature_id, owner_id, result, actor, occurred_at
):
    validate_pair_reference(result)
    event = deepcopy(
        {
            "schema_version": "1.0",
            "action": "CREATE_ROADMAP_ITEM_INITIATIVE",
            "workspace_id": str(workspace_id),
            "product_id": str(product_id),
            "roadmap_id": str(roadmap_id),
            "milestone_id": str(milestone_id),
            "feature_id": str(feature_id),
            "owner_id": str(owner_id),
            "result": result,
            "actor": actor,
            "occurred_at": occurred_at,
            "initial_item_status": "PROPOSED",
            "initial_initiative_state": "DRAFT",
            "approval_stages": ["PRD_APPROVAL", "PLAN_APPROVAL"],
        }
    )
    _VALIDATOR.validate(event)
    if event["owner_id"] != event["actor"]["actor_id"]:
        raise ValueError("ITEM_OWNER_MUST_BE_CURRENT_ROADMAP_OWNER")
    return event
