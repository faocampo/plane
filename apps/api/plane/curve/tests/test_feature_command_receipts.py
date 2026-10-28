# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID
import unittest

from plane.curve.feature_input import normalize_feature_command
from plane.curve.feature_policy import assert_receipt
from plane.curve.feature_services import _validate_retained_result
from plane.curve.services import ReplayResourceUnavailable, operation_response_digest


IDENTITY = UUID("00000000-0000-0000-0000-000000000001")
OTHER = UUID("00000000-0000-0000-0000-000000000002")


class FeatureRetainedResultTests(unittest.TestCase):
    def command(self, update=False):
        return normalize_feature_command(
            "UPDATE_FEATURE" if update else "CREATE_FEATURE",
            {"name": "Synthetic Feature", "description": None},
            4 if update else None,
        )

    def record(self, update=False):
        ref = {"resource_type": "FEATURE", "resource_id": str(IDENTITY), "resource_version": 5 if update else 1}
        status = 200 if update else 201
        return SimpleNamespace(
            state="COMPLETED",
            response_resource_ref=ref,
            response_status=status,
            response_digest=operation_response_digest(response_status=status, resource_ref=ref),
        )

    def test_valid_creation_and_update_results_retain_identity(self):
        for update in (False, True):
            self.assertEqual(
                _validate_retained_result(self.record(update), self.command(update), IDENTITY if update else None),
                IDENTITY,
            )

    def test_corrupt_state_status_or_digest_cannot_be_replayed(self):
        for key, value in (
            ("state", "FAILED"),
            ("state", "IN_PROGRESS"),
            ("response_status", 200),
            ("response_digest", "sha256:" + "0" * 64),
        ):
            record = self.record()
            setattr(record, key, value)
            with self.subTest(key=key, value=value), self.assertRaises(ReplayResourceUnavailable):
                _validate_retained_result(record, self.command(), None)

    def test_closed_ref_and_exact_integer_version_are_required(self):
        reference = self.record().response_resource_ref
        for ref in (
            None,
            {},
            {**reference, "actor_id": str(OTHER)},
            {**reference, "resource_type": "PRODUCT"},
            {**reference, "resource_version": True},
            {**reference, "resource_version": 2},
            {**reference, "resource_id": "invalid"},
        ):
            record = self.record()
            record.response_resource_ref = deepcopy(ref)
            if isinstance(ref, dict) and set(ref) >= {"resource_type", "resource_id", "resource_version"}:
                record.response_digest = operation_response_digest(response_status=201, resource_ref=ref)
            with self.subTest(ref=ref), self.assertRaises(ReplayResourceUnavailable):
                _validate_retained_result(record, self.command(), None)

    def test_update_result_cannot_point_to_another_feature_or_version(self):
        for identity, version in ((OTHER, 5), (IDENTITY, 4), (IDENTITY, 6)):
            record = self.record(True)
            record.response_resource_ref.update(resource_id=str(identity), resource_version=version)
            record.response_digest = operation_response_digest(
                response_status=200, resource_ref=record.response_resource_ref
            )
            with self.subTest(identity=identity, version=version), self.assertRaises(ReplayResourceUnavailable):
                _validate_retained_result(record, self.command(True), IDENTITY)

    def test_plain_objects_cannot_supply_a_mutation_receipt(self):
        for value in (None, {}, SimpleNamespace(_token=object())):
            with self.assertRaises(PermissionError):
                assert_receipt(value)


if __name__ == "__main__":
    unittest.main()
