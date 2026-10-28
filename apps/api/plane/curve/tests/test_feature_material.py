# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import unittest

from plane.curve.feature_input import FeatureInputError, normalize_feature_command
from plane.curve.feature_material import FeatureMaterialError, description_requirements


class FeatureMaterialTests(unittest.TestCase):
    def reference(self, value=1):
        return {
            "object_id": f"00000000-0000-0000-0000-{value:012d}",
            "digest": "sha256:" + "a" * 64,
            "size_bytes": 4,
            "media_type": "application/json",
            "editor_schema_version": "synthetic-v1",
        }

    def command(self, description, create=False):
        return normalize_feature_command(
            "CREATE_FEATURE" if create else "UPDATE_FEATURE",
            {"name": "Synthetic Feature", "description": description},
            None if create else 1,
        )

    def test_clearing_still_requires_retained_access(self):
        old = self.reference()
        result = description_requirements(self.command(None), retained_description=old)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].reference, old)
        self.assertEqual(result[0].purposes, frozenset({"RETAINED"}))

    def test_replacing_requires_both_in_stable_object_order(self):
        old, new = self.reference(2), self.reference(1)
        result = description_requirements(self.command(new), retained_description=old)
        self.assertEqual([dict(item.reference) for item in result], [new, old])
        self.assertEqual(
            [item.purposes for item in result],
            [frozenset({"REQUESTED"}), frozenset({"RETAINED"})],
        )

    def test_unchanged_reference_retains_both_purposes(self):
        old = self.reference()
        result = description_requirements(self.command(old), retained_description=old)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].purposes, frozenset({"RETAINED", "REQUESTED"}))

    def test_same_object_cannot_change_immutable_metadata(self):
        old = self.reference()
        for key, value in (
            ("digest", "sha256:" + "b" * 64),
            ("size_bytes", 5),
            ("media_type", "text/plain"),
            ("editor_schema_version", "synthetic-v2"),
        ):
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(FeatureMaterialError, "REFERENCE_CONFLICT"),
            ):
                description_requirements(self.command({**old, key: value}), retained_description=old)

    def test_create_and_empty_description_requirements(self):
        self.assertEqual(
            description_requirements(self.command(None, True), retained_description=None),
            (),
        )
        self.assertEqual(description_requirements(self.command(None), retained_description=None), ())
        result = description_requirements(self.command(self.reference(), True), retained_description=None)
        self.assertEqual(result[0].purposes, frozenset({"REQUESTED"}))
        with self.assertRaisesRegex(FeatureMaterialError, "CREATE_HAS_RETAINED"):
            description_requirements(self.command(None, True), retained_description=self.reference())

    def test_retained_reference_must_be_valid(self):
        for value in (
            {},
            {**self.reference(), "acl": "allow"},
            {**self.reference(), "size_bytes": True},
        ):
            with self.subTest(value=value), self.assertRaises(FeatureInputError):
                description_requirements(self.command(None), retained_description=value)

    def test_requirements_are_detached_and_immutable(self):
        old = self.reference()
        result = description_requirements(self.command(None), retained_description=old)
        old["digest"] = "changed"
        self.assertEqual(result[0].reference["digest"], "sha256:" + "a" * 64)
        with self.assertRaises(TypeError):
            result[0].reference["digest"] = "changed"
        with self.assertRaisesRegex(FeatureMaterialError, "NORMALIZED"):
            description_requirements({}, retained_description=None)


if __name__ == "__main__":
    unittest.main()
