"""Host checks of immutable binding and policy gates; ORM results are test doubles."""

# ruff: noqa: E402 -- Django settings must be configured before candidate imports.
from copy import deepcopy
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import bootstrap

bootstrap.install()

from django.test import override_settings
from manual_plan_v2 import contracts, policy
from test_draft_core import fixture


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.identity = fixture("input-identity.valid")
        self.original = self.identity["protected_inputs"][0]

    def retained(self):
        policy.require_retained_material(
            self.identity,
            self.original["object_ref"],
            material_version_id=self.original["material_version_id"],
            access_envelope_id=self.original["access_envelope_id"],
            classification=self.original["classification"],
        )

    def test_exact_retained_material_is_required(self):
        self.retained()
        for key in ("material_version_id", "access_envelope_id", "classification"):
            wrong = deepcopy(self.original)
            wrong[key] = "wrong"
            self.identity["protected_inputs"] = [wrong]
            with self.subTest(key=key), self.assertRaises(contracts.ManualPlanError):
                self.retained()
        for inputs in ([], [self.original, self.original]):
            self.identity["protected_inputs"] = inputs
            with self.subTest(inputs=inputs), self.assertRaises(contracts.ManualPlanError):
                self.retained()

    def test_body_reference_cannot_be_replaced_by_same_object_id(self):
        wrong = deepcopy(self.original)
        wrong["object_ref"]["digest"] = "sha256:" + "0" * 64
        self.identity["protected_inputs"] = [wrong]
        with self.assertRaises(contracts.ManualPlanError):
            self.retained()

    def test_feature_gate_fails_closed_before_workspace_lookup(self):
        enabled = Mock(return_value=True)
        with patch.dict(sys.modules, {"plane.curve.config": SimpleNamespace(is_curve_enabled_for_workspace=enabled)}):
            for flags in ({}, {"CURVE_MANUAL_PLAN_DRAFT_V2_ENABLED": True, "CURVE_ENVIRONMENT": "PRODUCTION"}):
                with (
                    self.subTest(flags=flags),
                    override_settings(**flags),
                    self.assertRaises(contracts.ManualPlanError),
                ):
                    policy.require_enabled(SimpleNamespace(user=SimpleNamespace(is_authenticated=True)), "synthetic")
            enabled.assert_not_called()

    def test_missing_trusted_successor_is_not_an_implicit_allow(self):
        with patch.dict(sys.modules, {"plane.curve.scope_reopening_qualification": SimpleNamespace()}):
            with self.assertRaises(contracts.ManualPlanError) as error:
                policy.require_edition()
            self.assertEqual(error.exception.status_code, 503)

    def test_prd_metadata_binds_every_selected_evidence_body_and_excerpt(self):
        original = self.original
        self.identity["prd_content_digest"] = original["object_ref"]["digest"]
        version = SimpleNamespace(
            id=original["material_version_id"],
            body_digest=self.identity["prd_content_digest"],
            access_envelope_id=original["access_envelope_id"],
            validate_metadata=Mock(),
            as_record=lambda: {"body": original["object_ref"]},
        )
        member = dict(
            evidence_item_id="synthetic-id",
            evidence_item_version=2,
            access_envelope_digest="synthetic-digest",
            access_envelope_id=original["access_envelope_id"],
            content_digest=original["object_ref"]["digest"],
            source_version="source-v2",
            material=True,
            selected_excerpt_ref=original["object_ref"],
        )
        snapshot = SimpleNamespace(items=[member], validate_metadata=Mock())
        item = SimpleNamespace(
            row_id=original["material_version_id"],
            envelope_digest="synthetic-digest",
            validate_metadata=Mock(),
            record=dict(
                access_envelope={"id": original["access_envelope_id"]},
                content_digest=member["content_digest"],
                source_version="source-v2",
                content=original["object_ref"],
                classification=original["classification"],
            ),
        )

        def manager(row):
            model = Mock()
            model.objects.select_for_update.return_value.filter.return_value.first.return_value = row
            return model

        module = SimpleNamespace(
            PrdArtifactVersion=manager(version),
            PrdEvidenceSnapshot=manager(snapshot),
            PrdEvidenceItemVersion=manager(item),
        )
        context = SimpleNamespace(
            workspace=SimpleNamespace(id=self.identity["workspace_id"]),
            initiative=SimpleNamespace(id=self.identity["initiative_id"]),
        )
        with patch.dict(sys.modules, {"plane.curve.prd_models": module}):
            policy.require_prd_materials(context, SimpleNamespace(identity=self.identity))
            snapshot.validate_metadata.assert_called_once()
            for field, value in (("source_version", "changed"), ("content", None), ("classification", "RESTRICTED")):
                previous = item.record[field]
                item.record[field] = value
                with self.subTest(field=field), self.assertRaises(contracts.ManualPlanError):
                    policy.require_prd_materials(context, SimpleNamespace(identity=self.identity))
                item.record[field] = previous
            member["selected_excerpt_ref"] = dict(original["object_ref"], object_id="other-id")
            with self.assertRaises(contracts.ManualPlanError):
                policy.require_prd_materials(context, SimpleNamespace(identity=self.identity))


if __name__ == "__main__":
    unittest.main()
