# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Pure joint-creation preparation; no persistence or authorization authority."""

from dataclasses import dataclass
from datetime import date
import json
import re
from uuid import UUID


class ItemCreationInputError(ValueError):
    code = "ROADMAP_ITEM_COMMAND_INVALID"


def keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ItemCreationInputError


def text(value, limit):
    if not isinstance(value, str) or not 1 <= len(value) <= limit or "\x00" in value:
        raise ItemCreationInputError
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ItemCreationInputError from None
    return value


def identity(value):
    if not isinstance(value, str):
        raise ItemCreationInputError
    try:
        return str(UUID(value))
    except ValueError:
        raise ItemCreationInputError from None


def choice(value, allowed):
    if value not in allowed:
        raise ItemCreationInputError
    return value


def calendar(value):
    if value is None:
        return None
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ItemCreationInputError
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ItemCreationInputError from None
    return value


@dataclass(frozen=True, slots=True)
class NormalizedItemCreation:
    expected_version: int
    canonical_payload: bytes

    def as_payload(self):
        return json.loads(self.canonical_payload)


def normalize_item_creation(payload, expected_version):
    if type(expected_version) is not int or not 1 <= expected_version <= 9223372036854775807:
        raise ItemCreationInputError
    keys(
        payload,
        (
            "initiative",
            "milestone_id",
            "feature_id",
            "scope_body",
            "priority",
            "confidence",
            "health",
            "planned_start",
            "planned_end",
        ),
    )
    initiative = payload["initiative"]
    keys(
        initiative,
        (
            "keyword",
            "title",
            "description",
            "risk_tier",
            "business_intent",
            "gate_assignments",
        ),
    )
    keyword = text(initiative["keyword"], 50)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,49}", keyword) is None:
        raise ItemCreationInputError
    title = text(initiative["title"], 255)
    description = initiative["description"]
    keys(description, ("schema_version", "format", "body"))
    if description["schema_version"] != "1.0" or description["format"] != "MARKDOWN":
        raise ItemCreationInputError
    body = text(description["body"], 20000)
    risk = choice(initiative["risk_tier"], ("LOW", "STANDARD", "HIGH"))
    intent = choice(
        initiative["business_intent"],
        ("STRATEGIC", "CUSTOMER_COMMITMENT", "BUSINESS_IMPROVEMENT", "MANDATORY", None),
    )
    assignments = initiative["gate_assignments"]
    if not isinstance(assignments, list) or len(assignments) != 2:
        raise ItemCreationInputError
    by_gate = {}
    for assignment in assignments:
        keys(assignment, ("gate_type", "approver_user_id"))
        gate = choice(assignment["gate_type"], ("PRD_APPROVAL", "PLAN_APPROVAL"))
        if gate in by_gate:
            raise ItemCreationInputError
        by_gate[gate] = identity(assignment["approver_user_id"])
    if risk != "LOW" and len(set(by_gate.values())) != 2:
        raise ItemCreationInputError
    scope = payload["scope_body"]
    keys(
        scope,
        ("object_id", "digest", "size_bytes", "media_type", "editor_schema_version"),
    )
    if not isinstance(scope["digest"], str) or re.fullmatch(r"sha256:[a-f0-9]{64}", scope["digest"]) is None:
        raise ItemCreationInputError
    if type(scope["size_bytes"]) is not int or scope["size_bytes"] < 0:
        raise ItemCreationInputError
    start, end = calendar(payload["planned_start"]), calendar(payload["planned_end"])
    if (start is None) != (end is None) or (start is not None and start > end):
        raise ItemCreationInputError
    normalized = {
        "initiative": {
            "keyword": keyword,
            "title": title,
            "description": {
                "schema_version": "1.0",
                "format": "MARKDOWN",
                "body": body,
            },
            "risk_tier": risk,
            "business_intent": intent,
            "gate_assignments": [{"gate_type": gate, "approver_user_id": by_gate[gate]} for gate in sorted(by_gate)],
        },
        "milestone_id": identity(payload["milestone_id"]),
        "feature_id": identity(payload["feature_id"]),
        "scope_body": {
            "object_id": identity(scope["object_id"]),
            "digest": scope["digest"],
            "size_bytes": scope["size_bytes"],
            "media_type": text(scope["media_type"], 255),
            "editor_schema_version": text(scope["editor_schema_version"], 100),
        },
        "priority": choice(payload["priority"], ("CRITICAL", "HIGH", "MEDIUM", "LOW")),
        "confidence": choice(payload["confidence"], ("HIGH", "MEDIUM", "LOW")),
        "health": choice(payload["health"], ("ON_TRACK", "AT_RISK", "OFF_TRACK", "UNKNOWN")),
        "planned_start": start,
        "planned_end": end,
    }
    return NormalizedItemCreation(
        expected_version,
        json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
    )
