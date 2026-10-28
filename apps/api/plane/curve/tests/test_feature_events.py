# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
import unittest

from jsonschema import ValidationError

from plane.curve.feature_events import FeatureEventError, build_feature_event
from plane.curve.feature_input import FeatureInputError


ID = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000002"


class FeatureEventTests(unittest.TestCase):
    def event(self, update=False):
        record = {
            "resource_type": "FEATURE",
            "resource_id": ID,
            "resource_version": 1,
            "name": "Synthetic Feature",
            "description": None,
        }
        return {
            "action": "UPDATE_FEATURE" if update else "CREATE_FEATURE",
            "workspace_id": ID,
            "product_id": ID,
            "before": deepcopy(record) if update else None,
            "after": {**record, "resource_version": 2 if update else 1},
            "actor": {"actor_type": "HUMAN", "actor_id": ID},
            "occurred_at": "2026-01-01T00:00:00+00:00",
        }

    def test_create_and_update_preserve_snapshots(self):
        for update in (False, True):
            args = self.event(update)
            result = build_feature_event(**args)
            self.assertEqual(result, {"schema_version": "1.0", **args})

    def test_create_requires_new_identity_version(self):
        for key, value in (
            ("before", self.event()["after"]),
            ("after", {**self.event()["after"], "resource_version": 2}),
        ):
            args = self.event()
            args[key] = value
            with self.subTest(key=key), self.assertRaises(ValidationError):
                build_feature_event(**args)

    def test_update_requires_before_snapshot(self):
        args = self.event(True)
        args["before"] = None
        with self.assertRaises(ValidationError):
            build_feature_event(**args)

    def test_update_identity_cannot_change(self):
        args = self.event(True)
        args["after"]["resource_id"] = OTHER
        with self.assertRaisesRegex(FeatureEventError, "FEATURE_IDENTITY_CHANGED"):
            build_feature_event(**args)

    def test_update_version_must_advance_exactly_once(self):
        args = self.event(True)
        args["after"]["resource_version"] = 3
        with self.assertRaisesRegex(FeatureEventError, "FEATURE_VERSION_NOT_SUCCESSOR"):
            build_feature_event(**args)

    def test_actor_and_snapshot_shapes_are_closed(self):
        for target, key, value in (
            ("actor", "actor_type", "AGENT"),
            ("actor", "role", "admin"),
            ("after", "owner_id", ID),
            ("after", "resource_version", True),
        ):
            args = self.event()
            args[target][key] = value
            with self.subTest(target=target, key=key), self.assertRaises(ValidationError):
                build_feature_event(**args)

    def test_event_is_detached_from_supplied_nested_values(self):
        args = self.event(True)
        result = build_feature_event(**args)
        args["actor"]["actor_id"] = OTHER
        args["before"]["name"] = "changed"
        args["after"]["name"] = "changed"
        self.assertEqual(result["actor"]["actor_id"], ID)
        self.assertEqual(result["before"]["name"], "Synthetic Feature")
        self.assertEqual(result["after"]["name"], "Synthetic Feature")

    def test_reference_digest_rejects_trailing_newline(self):
        args = self.event()
        args["after"]["description"] = {
            "object_id": ID,
            "digest": "sha256:" + "a" * 64 + "\n",
            "size_bytes": 0,
            "media_type": "application/json",
            "editor_schema_version": "synthetic-v1",
        }
        with self.assertRaises((FeatureInputError, ValidationError)):
            build_feature_event(**args)


if __name__ == "__main__":
    unittest.main()
