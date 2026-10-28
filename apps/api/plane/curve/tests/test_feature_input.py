# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import unittest

from plane.curve.feature_input import FeatureInputError, normalize_feature_command


class FeatureInputTests(unittest.TestCase):
    def payload(self):
        return {"name": "Synthetic Feature", "description": None}

    def reference(self):
        return {
            "object_id": "00000000-0000-0000-0000-000000000001",
            "digest": "sha256:" + "a" * 64,
            "size_bytes": 0,
            "media_type": "application/json",
            "editor_schema_version": "synthetic-v1",
        }

    def test_creation_retains_nullable_description(self):
        result = normalize_feature_command("CREATE_FEATURE", self.payload(), None)
        self.assertEqual(result.as_payload(), self.payload())

    def test_complete_updates_can_clear_description(self):
        result = normalize_feature_command("UPDATE_FEATURE", self.payload(), 7)
        self.assertEqual(result.expected_version, 7)
        self.assertIsNone(result.as_payload()["description"])

    def test_payload_is_closed_and_complete(self):
        for key in ("actor", "owner_id", "product_id", "id", "role", "version", "created_at"):
            with self.subTest(key=key), self.assertRaises(FeatureInputError):
                normalize_feature_command("CREATE_FEATURE", {**self.payload(), key: "forged"}, None)
        for value in ({"name": "Feature"}, {"description": None}, {}, [], None):
            with self.subTest(value=value), self.assertRaises(FeatureInputError):
                normalize_feature_command("CREATE_FEATURE", value, None)

    def test_versions_are_action_specific(self):
        for value in (None, True, False, 0, -1, "1", 1.0, 9223372036854775808):
            with self.subTest(value=value), self.assertRaises(FeatureInputError):
                normalize_feature_command("UPDATE_FEATURE", self.payload(), value)
        for value in (0, 1, True, "1"):
            with self.subTest(value=value), self.assertRaises(FeatureInputError):
                normalize_feature_command("CREATE_FEATURE", self.payload(), value)

    def test_name_boundaries(self):
        for value in (None, True, "", " \n\t", "x" * 256):
            with self.subTest(value=value), self.assertRaises(FeatureInputError):
                normalize_feature_command("CREATE_FEATURE", {**self.payload(), "name": value}, None)
        self.assertEqual(
            normalize_feature_command("CREATE_FEATURE", {**self.payload(), "name": "x" * 255}, None).name, "x" * 255
        )

    def test_text_rejects_database_unsupported_characters(self):
        for value in ("bad\x00name", "bad\ud800name", "bad\udfffname"):
            for field in ("name", "media_type", "editor_schema_version"):
                payload = self.payload()
                if field == "name":
                    payload[field] = value
                else:
                    payload["description"] = {**self.reference(), field: value}
                with self.subTest(field=field, value=repr(value)), self.assertRaises(FeatureInputError):
                    normalize_feature_command("CREATE_FEATURE", payload, None)

    def test_valid_international_names_preserve_exact_text(self):
        for value in ("Planificación", "計画", "Feature 🚀", "Cafe\u0301"):
            with self.subTest(value=value):
                self.assertEqual(
                    normalize_feature_command("CREATE_FEATURE", {**self.payload(), "name": value}, None).name,
                    value,
                )

    def test_reference_is_canonical_and_detached(self):
        ref = self.reference()
        ref["object_id"] = ref["object_id"].replace("-", "")
        result = normalize_feature_command("CREATE_FEATURE", {**self.payload(), "description": ref}, None)
        ref["digest"] = "changed"
        self.assertEqual(result.as_payload()["description"], self.reference())
        result.as_payload()["description"]["digest"] = "changed again"
        self.assertEqual(result.as_payload()["description"], self.reference())
        with self.assertRaises(TypeError):
            result.description["digest"] = "changed"

    def test_reference_rejects_untrusted_shape_and_values(self):
        invalid = [None, True, "bad"]
        for key in self.reference():
            missing = self.reference()
            del missing[key]
            invalid.append(missing)
        invalid += [{**self.reference(), "url": "https://example.invalid/object"}]
        for key, values in {
            "object_id": [True, None, "invalid"],
            "digest": [True, "sha256:" + "A" * 64, "sha256:" + "a" * 63, "sha256:" + "a" * 64 + "\n"],
            "size_bytes": [True, -1, 1.5, "0"],
            "media_type": [True, "", "x" * 256],
            "editor_schema_version": [None, "", "x" * 101],
        }.items():
            invalid += [{**self.reference(), key: value} for value in values]
        for value in invalid:
            if value is None:
                continue  # Explicit null is the defined absence of a description.
            with self.subTest(value=value), self.assertRaises(FeatureInputError):
                normalize_feature_command("CREATE_FEATURE", {**self.payload(), "description": value}, None)

    def test_actions_are_closed(self):
        for action in (None, [], "GRANT_FEATURE_EDITOR", "create_feature"):
            with self.subTest(action=action), self.assertRaises(FeatureInputError):
                normalize_feature_command(action, self.payload(), None)


if __name__ == "__main__":
    unittest.main()
