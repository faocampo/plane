# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from dataclasses import replace
from types import MappingProxyType
import unittest
import pytest

from uuid import UUID

from django.db import transaction

from plane.curve import feature_editor_policy as policy

pytestmark = pytest.mark.django_db(transaction=True)


IDENTITY = UUID(int=1)


def receipt(token):
    return policy.FeatureEditorReceipt(
        IDENTITY,
        "GRANT_FEATURE_EDITOR",
        IDENTITY,
        IDENTITY,
        None,
        IDENTITY,
        IDENTITY,
        0,
        MappingProxyType({"actor_type": "HUMAN", "actor_id": str(IDENTITY)}),
        "synthetic-correlation",
        MappingProxyType({"resource_type": "PRODUCT", "resource_id": str(IDENTITY)}),
        token,
    )


class FeatureEditorReceiptTests(unittest.TestCase):
    def test_missing_or_forged_receipt_rejects_even_inside_transaction(self):
        with transaction.atomic():
            for candidate in (None, object(), receipt(object())):
                with (
                    self.subTest(candidate_type=type(candidate).__name__),
                    self.assertRaises(PermissionError),
                ):
                    policy.assert_receipt(candidate)

    def test_trusted_token_alone_cannot_supply_an_active_receipt(self):
        with transaction.atomic(), self.assertRaises(PermissionError):
            policy.assert_receipt(receipt(policy._TOKEN))

    def test_live_receipt_rejects_copied_or_changed_capabilities(self):
        current = receipt(policy._TOKEN)
        token = policy._ACTIVE.set(current)
        try:
            with transaction.atomic():
                policy.assert_receipt(current)
                for candidate in (
                    replace(current),
                    replace(current, action="REVOKE_FEATURE_EDITOR"),
                ):
                    with (
                        self.subTest(action=candidate.action),
                        self.assertRaises(PermissionError),
                    ):
                        policy.assert_receipt(candidate)
        finally:
            policy._ACTIVE.reset(token)
        with transaction.atomic(), self.assertRaises(PermissionError):
            policy.assert_receipt(current)

    def test_context_cannot_escape_its_transaction(self):
        current = receipt(policy._TOKEN)
        token = policy._ACTIVE.set(current)
        try:
            with self.assertRaises(PermissionError):
                policy.assert_receipt(current)
        finally:
            policy._ACTIVE.reset(token)


if __name__ == "__main__":
    unittest.main()
