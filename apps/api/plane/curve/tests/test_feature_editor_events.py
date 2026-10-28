# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
import unittest

from plane.curve.feature_editor_events import FeatureEditorEventError, build_editor_event
from plane.curve.tests.test_feature_editor_event_contract import EVENT, IDENTITY, RECORD, STAMP


OTHER = "00000000-0000-0000-0000-000000000002"


def arguments(event):
    return {key: deepcopy(value) for key, value in event.items() if key != "schema_version"}


def revoked_event():
    event = deepcopy(EVENT)
    event.update(action="REVOKE_FEATURE_EDITOR", before=deepcopy(RECORD))
    event["after"].update(resource_version=2, revoked_by=IDENTITY, revoked_at=STAMP)
    return event


class FeatureEditorEventBuilderTests(unittest.TestCase):
    def test_grant_is_detached_from_mutable_callers(self):
        supplied = arguments(EVENT)
        result = build_editor_event(**supplied)
        supplied["after"]["member_id"] = OTHER
        self.assertEqual(result, EVENT)

    def test_grant_actor_must_match_original_attribution(self):
        supplied = arguments(EVENT)
        supplied["actor"]["actor_id"] = OTHER
        with self.assertRaises(FeatureEditorEventError):
            build_editor_event(**supplied)

    def test_revocation_preserves_all_original_evidence(self):
        event = revoked_event()
        self.assertEqual(build_editor_event(**arguments(event)), event)
        for field in ("resource_id", "member_id", "membership_id", "granted_by"):
            damaged = deepcopy(event)
            damaged["after"][field] = OTHER
            with self.subTest(field=field), self.assertRaises(FeatureEditorEventError):
                build_editor_event(**arguments(damaged))

    def test_revocation_cannot_change_generation_or_grant_time(self):
        for field, value in (
            ("membership_generation", 1),
            ("granted_at", "2026-01-02T00:00:00Z"),
        ):
            event = revoked_event()
            event["after"][field] = value
            with self.subTest(field=field), self.assertRaises(FeatureEditorEventError):
                build_editor_event(**arguments(event))

    def test_revocation_actor_must_match_current_attribution(self):
        event = revoked_event()
        event["actor"]["actor_id"] = OTHER
        with self.assertRaises(FeatureEditorEventError):
            build_editor_event(**arguments(event))

    def test_clock_rollback_does_not_prevent_revocation(self):
        event = revoked_event()
        event["after"]["revoked_at"] = "2025-12-31T23:59:59Z"
        event["occurred_at"] = event["after"]["revoked_at"]
        self.assertEqual(build_editor_event(**arguments(event)), event)


if __name__ == "__main__":
    unittest.main()
