# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker, ValidationError


SCHEMA = json.loads((Path(__file__).parents[1] / "feature_editors/command-event-v1.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
IDENTITY = "00000000-0000-0000-0000-000000000001"
STAMP = "2026-01-01T00:00:00Z"
RECORD = {
    "resource_type": "FEATURE_EDITOR_GRANT",
    "resource_id": IDENTITY,
    "resource_version": 1,
    "member_id": IDENTITY,
    "membership_id": IDENTITY,
    "membership_generation": 0,
    "granted_by": IDENTITY,
    "granted_at": STAMP,
    "revoked_by": None,
    "revoked_at": None,
}
EVENT = {
    "schema_version": "1.0",
    "workspace_id": IDENTITY,
    "product_id": IDENTITY,
    "action": "GRANT_FEATURE_EDITOR",
    "before": None,
    "after": RECORD,
    "actor": {"actor_type": "HUMAN", "actor_id": IDENTITY},
    "occurred_at": STAMP,
}


class FeatureEditorEventTests(unittest.TestCase):
    def test_schema_and_grant_event_are_valid(self):
        Draft202012Validator.check_schema(SCHEMA)
        VALIDATOR.validate(EVENT)

    def test_revocation_requires_full_retained_before_and_after(self):
        event = deepcopy(EVENT)
        event.update(action="REVOKE_FEATURE_EDITOR", before=deepcopy(RECORD))
        event["after"].update(resource_version=2, revoked_by=IDENTITY, revoked_at=STAMP)
        VALIDATOR.validate(event)
        event["before"] = None
        with self.assertRaises(ValidationError):
            VALIDATOR.validate(event)

    def test_grant_cannot_claim_revoked_state(self):
        event = deepcopy(EVENT)
        event["after"].update(resource_version=2, revoked_by=IDENTITY, revoked_at=STAMP)
        with self.assertRaises(ValidationError):
            VALIDATOR.validate(event)

    def test_extra_event_or_history_fields_reject(self):
        for target in ("event", "after", "actor"):
            event = deepcopy(EVENT)
            (event if target == "event" else event[target])["unexpected"] = "value"
            with self.subTest(target=target), self.assertRaises(ValidationError):
                VALIDATOR.validate(event)

    def test_only_human_actor_and_valid_identifiers_are_accepted(self):
        for field, value in (("actor_type", "AGENT"), ("actor_id", "invalid")):
            event = deepcopy(EVENT)
            event["actor"][field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                VALIDATOR.validate(event)

    def test_invalid_generations_and_unpaired_revocation_reject(self):
        for changes in (
            {"membership_generation": True},
            {"membership_generation": -1},
            {"revoked_by": IDENTITY},
        ):
            event = deepcopy(EVENT)
            event["after"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                VALIDATOR.validate(event)


if __name__ == "__main__":
    unittest.main()
