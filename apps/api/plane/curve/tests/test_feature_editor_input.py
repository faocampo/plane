# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import unittest

from plane.curve.feature_editor_input import FeatureEditorInputError, normalize_editor_command


MEMBER = "00000000-0000-0000-0000-000000000001"


class FeatureEditorInputTests(unittest.TestCase):
    def test_grant_normalizes_recipient_and_is_independent_of_input_mutation(self):
        supplied = {"member_id": MEMBER.replace("-", "")}
        result = normalize_editor_command("GRANT_FEATURE_EDITOR", supplied, None)
        supplied["member_id"] = "changed"
        self.assertEqual(dict(result.payload), {"member_id": MEMBER})
        self.assertIsNone(result.expected_version)
        with self.assertRaises(TypeError):
            result.payload["actor_id"] = MEMBER

    def test_grant_rejects_client_authority_and_storage_identity(self):
        for key in (
            "actor_id",
            "owner_id",
            "role",
            "membership_id",
            "membership_generation",
            "grant_id",
            "granted_at",
        ):
            with self.subTest(key=key), self.assertRaises(FeatureEditorInputError):
                normalize_editor_command("GRANT_FEATURE_EDITOR", {"member_id": MEMBER, key: MEMBER}, None)

    def test_grant_rejects_missing_or_invalid_recipients(self):
        for value in (
            {},
            {"member_id": None},
            {"member_id": True},
            {"member_id": "invalid"},
            [],
        ):
            with self.subTest(value=value), self.assertRaises(FeatureEditorInputError):
                normalize_editor_command("GRANT_FEATURE_EDITOR", value, None)

    def test_creation_does_not_accept_target_versions(self):
        for version in (0, 1, "1", True):
            with (
                self.subTest(version=version),
                self.assertRaises(FeatureEditorInputError),
            ):
                normalize_editor_command("GRANT_FEATURE_EDITOR", {"member_id": MEMBER}, version)

    def test_revocation_preserves_exact_version_for_receipt_and_stale_check(self):
        for version in (1, 2, 9223372036854775807):
            with self.subTest(version=version):
                result = normalize_editor_command("REVOKE_FEATURE_EDITOR", {}, version)
                self.assertEqual(result.expected_version, version)
                self.assertEqual(dict(result.payload), {})

    def test_revocation_requires_bounded_integer_version(self):
        for version in (None, True, False, 0, -1, "1", 1.0, 9223372036854775808):
            with (
                self.subTest(version=version),
                self.assertRaises(FeatureEditorInputError),
            ):
                normalize_editor_command("REVOKE_FEATURE_EDITOR", {}, version)

    def test_revocation_rejects_client_history_fields(self):
        for payload in (
            {"revoked_by": MEMBER},
            {"revoked_at": "2026-01-01T00:00:00Z"},
            {"version": 2},
            [],
        ):
            with (
                self.subTest(payload=payload),
                self.assertRaises(FeatureEditorInputError),
            ):
                normalize_editor_command("REVOKE_FEATURE_EDITOR", payload, 1)

    def test_unknown_action_is_closed(self):
        for action in (
            None,
            "UPDATE_FEATURE_EDITOR",
            "CREATE_FEATURE",
            "grant_feature_editor",
        ):
            with (
                self.subTest(action=action),
                self.assertRaises(FeatureEditorInputError),
            ):
                normalize_editor_command(action, {}, None)


if __name__ == "__main__":
    unittest.main()
