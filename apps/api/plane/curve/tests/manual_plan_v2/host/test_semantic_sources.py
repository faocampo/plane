# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Protected local bodies, not asserted catalog facts, determine plan coverage."""

# ruff: noqa: E402
import unittest
from copy import deepcopy

import bootstrap

bootstrap.install()
from manual_plan_v2.validation import (
    InvalidPlan,
    derive_semantic_facts,
    validate_definition,
    _normalized_prd_facts,
)


from semantic_fixture import semantic_case


class NormalizedPrdTests(unittest.TestCase):
    def setUp(self):
        def paragraph(text, heading=False):
            return dict(
                paragraph=dict(
                    elements=[dict(textRun=dict(content=text))],
                    **({"paragraphStyle": {"namedStyleType": "HEADING_1"}} if heading else {}),
                )
            )

        self.value = dict(
            normalization_version="curve.google-docs.normalized/v1-candidate",
            complete=True,
            unsupported_nodes=0,
            document_properties={"documentId": "synthetic-document"},
            tabs=[
                dict(
                    tabProperties={"title": "Definition"},
                    documentTab=dict(
                        body=dict(
                            content=[
                                paragraph("Requirements", True),
                                paragraph("FR-1: First\nFR-2: Second"),
                                paragraph("Acceptance", True),
                                paragraph("AC-1: Verify FR-1 and FR-2"),
                            ]
                        )
                    ),
                )
            ],
        )
        self.identity = dict(workspace_id="synthetic-workspace", initiative_id="synthetic-initiative")

    def test_existing_normalized_bytes_derive_complete_exact_traceability(self):
        value = _normalized_prd_facts(self.value, self.identity)
        self.assertEqual([item["id"] for item in value["requirements"]], ["FR-1", "FR-2"])
        self.assertEqual([item["acceptance_ids"] for item in value["requirements"]], [["AC-1"], ["AC-1"]])

    def test_unsupported_structures_and_duplicate_sections_fail_without_dropping_content(self):
        mutations = [
            lambda v: v["tabs"].append(deepcopy(v["tabs"][0])),
            lambda v: v["tabs"][0].update(childTabs=[{}]),
            lambda v: v["tabs"][0]["documentTab"].update(footnotes={"hidden": {}}),
            lambda v: v["tabs"][0]["documentTab"].update(body=[]),
            lambda v: v["tabs"][0]["documentTab"]["body"]["content"].append({"table": {}}),
            lambda v: v["tabs"][0]["documentTab"]["body"]["content"].append(
                deepcopy(v["tabs"][0]["documentTab"]["body"]["content"][0])
            ),
        ]
        for mutate in mutations:
            value = deepcopy(self.value)
            mutate(value)
            with self.subTest(mutate=mutate), self.assertRaises(InvalidPlan):
                _normalized_prd_facts(value, self.identity)

    def test_nested_requirement_heading_is_included_in_traceability(self):
        nodes = self.value["tabs"][0]["documentTab"]["body"]["content"]
        nodes[1]["paragraph"]["paragraphStyle"] = {"namedStyleType": "HEADING_2"}
        result = _normalized_prd_facts(self.value, self.identity)
        self.assertEqual([item["id"] for item in result["requirements"]], ["FR-1", "FR-2"])

    def test_unparsed_declarations_cannot_be_silently_dropped(self):
        for prefix in ("FR-3 - unparsed", "Unparsed requirement", "REQ-3: Unsupported"):
            value = deepcopy(self.value)
            run = value["tabs"][0]["documentTab"]["body"]["content"][1]["paragraph"]["elements"][0]["textRun"]
            run["content"] = prefix + "\n" + run["content"]
            with self.subTest(prefix=prefix), self.assertRaises(InvalidPlan):
                _normalized_prd_facts(value, self.identity)

    def test_uncovered_unknown_duplicate_and_empty_declarations_fail(self):
        for text in ("AC-1: Verify FR-1", "AC-1: Verify FR-9", "AC-1: FR-1 FR-2\nAC-1: duplicate", "AC-1:"):
            value = deepcopy(self.value)
            value["tabs"][0]["documentTab"]["body"]["content"][3]["paragraph"]["elements"][0]["textRun"]["content"] = (
                text
            )
            with self.subTest(text=text), self.assertRaises(InvalidPlan):
                _normalized_prd_facts(value, self.identity)


class SemanticSourcesTests(unittest.TestCase):
    def setUp(self):
        self.raw, self.identity, self.facts, self.sources, self.materials = semantic_case()

    def derive(self):
        return derive_semantic_facts(self.identity, self.sources, self.materials, self.facts)

    def test_exact_protected_sources_produce_the_facts_and_valid_receipt(self):
        derived = self.derive()
        self.assertEqual(derived["required_check_ids"], ["lint", "security", "unit"])
        self.assertEqual(derived["requirement_ids"], ["FR-008", "FR-009"])
        self.assertEqual(validate_definition(self.raw, self.identity, derived)["result"], "VALID")

    def test_editable_facts_cannot_drop_coverage_quality_or_repository_pin(self):
        mutations = [
            ("required_check_ids", ["lint"]),
            ("requirement_ids", ["FR-008"]),
            ("acceptance_ids", ["AC-10"]),
            ("owner_ids", []),
            ("budget_policy_ref", {}),
        ]
        for field, value in mutations:
            previous = self.facts[field]
            self.facts[field] = value
            with self.subTest(field=field), self.assertRaises(InvalidPlan):
                self.derive()
            self.facts[field] = previous

    def test_absent_or_changed_body_and_unretained_source_fail(self):
        ref = self.sources["prd"]
        original = self.materials.pop(ref["object_id"])
        with self.assertRaises(InvalidPlan):
            self.derive()
        self.materials[ref["object_id"]] = original + b" "
        with self.assertRaises(InvalidPlan):
            self.derive()
        self.materials[ref["object_id"]] = original
        self.identity["protected_inputs"] = [
            item for item in self.identity["protected_inputs"] if item["object_ref"] != ref
        ]
        with self.assertRaises(InvalidPlan):
            self.derive()

    def test_workflow_quality_and_policy_sources_cannot_be_interchanged(self):
        for field in ("workflow", "quality"):
            before = self.sources[field]
            self.sources[field] = self.sources["prd"]
            with self.subTest(field=field), self.assertRaises(InvalidPlan):
                self.derive()
            self.sources[field] = before
        self.sources["repositories"][0]["policy"] = self.sources["quality"]
        with self.assertRaises(InvalidPlan):
            self.derive()

    def test_future_dependency_artifact_cannot_be_asserted_in_facts(self):
        self.facts["dependency_artifact_refs"] = [self.sources["prd"]]
        with self.assertRaises(InvalidPlan):
            self.derive()
