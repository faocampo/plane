# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from plane.curve.item_cancellation_results import cancellation_reference

_SCHEMA_BYTES = (Path(__file__).parent / "items/item-creation-cancelled-v1.schema.json").read_bytes()
if hashlib.sha256(_SCHEMA_BYTES).hexdigest() != "b085ee2a736fa4431b1d73aa4f014fadd755012898dd4f7e35bbcd434596a3c5":
    raise RuntimeError("ITEM_CANCELLATION_EVENT_CONTRACT_CHANGED")
_SCHEMA = json.loads(_SCHEMA_BYTES)
Draft202012Validator.check_schema(_SCHEMA)
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())


def build_item_cancellation_event(*, workspace_id, product_id, roadmap_id, record_id):
    payload = deepcopy(
        {
            "schema_version": "1.0",
            "workspace_id": str(workspace_id),
            "product_id": str(product_id),
            "roadmap_id": str(roadmap_id),
            "result": cancellation_reference(record_id),
        }
    )
    _VALIDATOR.validate(payload)
    return payload
