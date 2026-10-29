# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import copy
import unittest

from plane.curve.item_creation_input import ItemCreationInputError, normalize_item_creation


def fixture():
    return {
        "initiative": {
            "keyword": "DEMO-1",
            "title": "Launch café 日本語",
            "description": {
                "schema_version": "1.0",
                "format": "MARKDOWN",
                "body": "Synthetic scope.",
            },
            "risk_tier": "STANDARD",
            "business_intent": None,
            "gate_assignments": [
                {
                    "gate_type": "PRD_APPROVAL",
                    "approver_user_id": "93000000-0000-4000-8000-000000000001",
                },
                {
                    "gate_type": "PLAN_APPROVAL",
                    "approver_user_id": "93000000-0000-4000-8000-000000000002",
                },
            ],
        },
        "milestone_id": "93000000-0000-4000-8000-000000000003",
        "feature_id": "93000000-0000-4000-8000-000000000004",
        "scope_body": {
            "object_id": "93000000-0000-4000-8000-000000000005",
            "digest": "sha256:" + "a" * 64,
            "size_bytes": 0,
            "media_type": "text/markdown",
            "editor_schema_version": "1.0",
        },
        "priority": "MEDIUM",
        "confidence": "HIGH",
        "health": "UNKNOWN",
        "planned_start": None,
        "planned_end": None,
    }


class ItemCreationInputTests(unittest.TestCase):
    def test_assignment_order_has_one_canonical_identity(self):
        a, b = fixture(), fixture()
        b["initiative"]["gate_assignments"].reverse()
        self.assertEqual(normalize_item_creation(a, 1), normalize_item_creation(b, 1))

    def test_result_is_detached_from_input_and_exported_payload(self):
        value = fixture()
        original = copy.deepcopy(value)
        result = normalize_item_creation(value, 1)
        self.assertEqual(value, original)
        value["initiative"]["description"]["body"] = "Changed"
        exported = result.as_payload()
        exported["initiative"]["gate_assignments"].clear()
        self.assertEqual(result.as_payload()["initiative"]["description"]["body"], "Synthetic scope.")
        self.assertEqual(len(result.as_payload()["initiative"]["gate_assignments"]), 2)
        self.assertEqual(result.as_payload()["initiative"]["title"], original["initiative"]["title"])

    def test_exactly_two_stages_and_no_code_approver(self):
        for roles in (
            ("PRD_APPROVAL", "PRD_APPROVAL"),
            ("CODE_READINESS", "PLAN_APPROVAL"),
            ("PRD_APPROVAL",),
            ("PRD_APPROVAL", "PLAN_APPROVAL", "CODE_READINESS"),
        ):
            with self.subTest(roles=roles):
                value = fixture()
                value["initiative"]["gate_assignments"] = [
                    {
                        "gate_type": role,
                        "approver_user_id": "93000000-0000-4000-8000-000000000001",
                    }
                    for role in roles
                ]
                with self.assertRaises(ItemCreationInputError):
                    normalize_item_creation(value, 1)

    def test_risk_separation_uses_normalized_human_identity(self):
        for risk in ("LOW", "STANDARD", "HIGH"):
            with self.subTest(risk=risk):
                value = fixture()
                value["initiative"]["risk_tier"] = risk
                value["initiative"]["gate_assignments"][1]["approver_user_id"] = value["initiative"][
                    "gate_assignments"
                ][0]["approver_user_id"].replace("-", "")
                if risk == "LOW":
                    self.assertEqual(
                        normalize_item_creation(value, 1).as_payload()["initiative"]["risk_tier"],
                        risk,
                    )
                else:
                    with self.assertRaises(ItemCreationInputError):
                        normalize_item_creation(value, 1)

    def test_schedule_pair_and_calendar_validation(self):
        for start, end in (
            (None, "2026-01-01"),
            ("2026-01-01", None),
            ("2026-02-30", "2026-03-01"),
            ("2026-02-02", "2026-02-01"),
            ("20260101", "20260102"),
            (True, "2026-01-01"),
        ):
            with self.subTest(start=start, end=end):
                value = fixture()
                value.update(planned_start=start, planned_end=end)
                with self.assertRaises(ItemCreationInputError):
                    normalize_item_creation(value, 1)
        value = fixture()
        value.update(planned_start="2028-02-29", planned_end="2028-02-29")
        self.assertEqual(normalize_item_creation(value, 1).as_payload()["planned_end"], "2028-02-29")

    def test_authority_and_generated_fields_cannot_be_supplied(self):
        for field in (
            "owner_id",
            "actor",
            "id",
            "approved_prd_version_id",
            "state",
            "roadmap_item_id",
            "version",
            "policy_decision",
        ):
            for level in ("root", "initiative"):
                with self.subTest(field=field, level=level):
                    value = fixture()
                    (value if level == "root" else value["initiative"])[field] = "forged"
                    with self.assertRaises(ItemCreationInputError):
                        normalize_item_creation(value, 1)

    def test_storage_invalid_text_is_rejected_before_command_identity(self):
        for field in ("title", "body", "media_type", "editor_schema_version"):
            for invalid in ("bad\x00text", "bad\ud800text", ""):
                with self.subTest(field=field, invalid=repr(invalid)):
                    value = fixture()
                    target = (
                        value["initiative"]
                        if field == "title"
                        else value["initiative"]["description"]
                        if field == "body"
                        else value["scope_body"]
                    )
                    target[field] = invalid
                    with self.assertRaises(ItemCreationInputError):
                        normalize_item_creation(value, 1)

    def test_version_rejects_boolean_float_missing_and_overflow(self):
        for version in (None, True, 1.0, "1", 0, -1, 9223372036854775808):
            with self.subTest(version=version):
                with self.assertRaises(ItemCreationInputError):
                    normalize_item_creation(fixture(), version)

    def test_wrong_types_and_open_nested_structures_fail_closed(self):
        for field in (
            "initiative",
            "scope_body",
            "priority",
            "confidence",
            "health",
            "milestone_id",
            "feature_id",
        ):
            with self.subTest(field=field):
                value = fixture()
                value[field] = []
                with self.assertRaises(ItemCreationInputError):
                    normalize_item_creation(value, 1)
        value = fixture()
        value["scope_body"]["source_access"] = True
        with self.assertRaises(ItemCreationInputError):
            normalize_item_creation(value, 1)


if __name__ == "__main__":
    unittest.main()
