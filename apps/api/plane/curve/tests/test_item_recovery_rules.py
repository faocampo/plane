# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from types import SimpleNamespace
import unittest

from item_recovery_rules import recovery_read_reason


class ReceiptReadRules(unittest.TestCase):
    def facts(self, **changes):
        product = dict(
            feature_enabled=True,
            actor_active_human=True,
            actor_active_member=True,
            product_active=True,
            product_format_supported=True,
            membership_id="synthetic-membership",
            membership_generation=0,
        )
        product.update(changes)
        return SimpleNamespace(product=SimpleNamespace(**product), roadmap_active=True, roadmap_format_supported=True)

    def test_current_reader_can_reconcile_without_retaining_creation_role(self):
        self.assertEqual(recovery_read_reason(self.facts(), enabled=True, local=True), "ALLOW")

    def test_explicit_local_activation_required(self):
        self.assertEqual(recovery_read_reason(self.facts(), enabled=False, local=True), "FEATURE_DISABLED")
        self.assertEqual(recovery_read_reason(self.facts(), enabled=True, local=False), "LOCAL_ITEM_PROFILE_REQUIRED")

    def test_current_authority_failures(self):
        cases = [
            ("feature_enabled", False, "FEATURE_DISABLED"),
            ("actor_active_human", False, "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"),
            ("actor_active_member", False, "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"),
            ("product_active", False, "PRODUCT_UNAVAILABLE"),
            ("product_format_supported", False, "FORMAT_UNAVAILABLE"),
            ("membership_id", None, "CURRENT_MEMBERSHIP_LIFETIME_REQUIRED"),
            ("membership_generation", -1, "CURRENT_MEMBERSHIP_LIFETIME_REQUIRED"),
            ("membership_generation", True, "CURRENT_MEMBERSHIP_LIFETIME_REQUIRED"),
            ("membership_generation", None, "CURRENT_MEMBERSHIP_LIFETIME_REQUIRED"),
        ]
        for field, value, expected in cases:
            with self.subTest(field=field, value=value):
                self.assertEqual(recovery_read_reason(self.facts(**{field: value}), enabled=True, local=True), expected)

    def test_current_roadmap_must_remain_live_and_supported(self):
        facts = self.facts()
        facts.roadmap_active = False
        self.assertEqual(recovery_read_reason(facts, enabled=True, local=True), "RESOURCE_UNAVAILABLE")
        facts.roadmap_active = True
        facts.roadmap_format_supported = False
        self.assertEqual(recovery_read_reason(facts, enabled=True, local=True), "FORMAT_UNAVAILABLE")
