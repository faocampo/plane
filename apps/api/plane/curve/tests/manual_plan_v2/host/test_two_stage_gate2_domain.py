# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Two-stage subjects exercise the unchanged reservation/release kernel."""

# ruff: noqa: E402
from copy import deepcopy
from dataclasses import replace
import json
import uuid

import bootstrap

bootstrap.install()
# The historical host setup supplies the same isolated import profile.
import test_gate2_domain as historical

from plane.curve.manual_gate2_v3 import domain as g
from plane.curve.manual_plan_v3.validation import canonical_json, metadata_digest
from plane.curve.tests.test_manual_plan_v3 import bundle, validate_bundle, FIXTURES
from plane.curve.manual_plan_v3.contracts import ManualPlanError
from plane.curve.manual_plan_v3.validation import InvalidPlan


def inputs():
    definition, identity, facts = bundle()
    receipt = validate_bundle(definition, identity, facts)
    revision = json.loads((FIXTURES / "revision.valid.json").read_text())
    revision["schema_version"] = "curve.manual-plan-draft.revision/v3-candidate"
    revision["policy_edition"] = "LOCAL_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V3"
    revision["definition_ref"] = deepcopy(identity["definition_ref"])
    revision["manual_profile_ref"] = deepcopy(identity["manual_profile_ref"])
    revision["digest"] = metadata_digest(revision)
    return dict(
        revision=revision,
        identity=identity,
        facts=facts,
        receipt=receipt,
        definition=canonical_json(definition),
        controlling_prd_decision_id="30000000-0000-4000-8000-000000000071",
    )


class TwoStageTransitions(historical.Gate2Transitions):
    """Run all historical reservation invariants with a two-stage subject.

    Inherited competing-initiative cases deliberately retain the old subject:
    task exclusivity and release generations must span both document editions.
    """

    def setUp(self):
        self.subject = g.prepare_subject(**inputs())
        self.authority = historical.authority(self.subject)
        self.rationale = "sha256:" + "d" * 64

    def test_only_product_and_technical_reviewers_are_required(self):
        assignments = self.subject.data["input_identity"]["gate_assignments"]
        self.assertEqual([a["gate_type"] for a in assignments], ["PLAN_APPROVAL", "PRD_APPROVAL"])
        self.assertEqual(self.subject.data["edition"], "MANUAL_GATE2_TWO_STAGE_TRANSITION_V3")
        ledger, _, _ = self.transition()
        self.assertEqual(len(ledger.claims), len(self.subject.tasks))
        self.assertNotIn("CODE_READINESS", self.subject.metadata.decode())

    def test_missing_current_product_access_still_denies_technical_approval(self):
        product = next(
            a["approver_user_id"]
            for a in self.subject.data["input_identity"]["gate_assignments"]
            if a["gate_type"] == "PRD_APPROVAL"
        )
        auth = replace(
            self.authority, material_readers=tuple(x for x in self.authority.material_readers if x != product)
        )
        with self.assertRaises(g.Gate2Denied):
            self.transition(authority=auth)

    def test_old_revision_or_receipt_cannot_be_reinterpreted(self):
        for name, fixture in [("revision", "revision.valid"), ("identity", "input-identity.valid")]:
            value = inputs()
            value[name] = json.loads((FIXTURES / (fixture + ".json")).read_text())
            with self.subTest(name=name), self.assertRaises((InvalidPlan, ManualPlanError, g.Gate2Denied)):
                g.prepare_subject(**value)

    def test_receipt_substitution_is_rejected(self):
        value = inputs()
        value["receipt"]["input_identity_digest"] = "sha256:" + "0" * 64
        value["receipt"]["digest"] = metadata_digest(value["receipt"])
        with self.assertRaises(g.Gate2Denied):
            g.prepare_subject(**value)

    def test_new_two_stage_initiative_cannot_take_reserved_tasks(self):
        ledger, _, _ = self.transition()
        value = inputs()
        new_id = str(uuid.uuid4())
        definition = json.loads(value["definition"])
        for item in (definition, value["identity"], value["facts"], value["revision"]):
            item["initiative_id"] = new_id
        value["receipt"] = validate_bundle(definition, value["identity"], value["facts"])
        value["definition"] = canonical_json(definition)
        value["revision"]["definition_ref"] = deepcopy(value["identity"]["definition_ref"])
        value["revision"]["digest"] = metadata_digest(value["revision"])
        other = g.prepare_subject(**value)
        with self.assertRaises(g.Gate2Denied):
            self.transition(ledger, subject=other, authority=historical.authority(other))

    def test_standard_and_high_risk_subjects_require_distinct_reviewers(self):
        for risk in ("STANDARD", "HIGH"):
            value = inputs()
            value.pop("definition")
            value["facts"]["risk_tier"] = risk
            assignments = value["identity"]["gate_assignments"]
            assignments[0]["approver_user_id"] = assignments[1]["approver_user_id"]
            value["identity"]["digest"] = metadata_digest(value["identity"])
            value["receipt"]["input_identity_digest"] = value["identity"]["digest"]
            value["receipt"]["digest"] = metadata_digest(value["receipt"])
            with self.subTest(risk=risk), self.assertRaises(g.Gate2Denied):
                g.subject_from_verified_receipt(**value)
