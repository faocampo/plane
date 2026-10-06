"""Protected local bodies, not asserted catalog facts, determine plan coverage."""

# ruff: noqa: E402
from copy import deepcopy
import unittest
import uuid

import bootstrap

bootstrap.install()
from manual_plan_v2.validation import (
    InvalidPlan,
    canonical_json,
    derive_semantic_facts,
    digest,
    metadata_digest,
    validate_definition,
)
from test_draft_core import fixture


def semantic_case():
    definition, identity, facts = (
        fixture(name) for name in ("definition.valid", "input-identity.valid", "immutable-semantic-facts")
    )
    materials = {}

    def store(value):
        raw = canonical_json(value)
        ref = dict(object_id=str(uuid.uuid4()), digest=digest(raw), size_bytes=len(raw), media_type="application/json")
        materials[ref["object_id"]] = raw
        identity["protected_inputs"].append(
            dict(
                object_ref=ref,
                material_version_id=str(uuid.uuid4()),
                access_envelope_id=str(uuid.uuid4()),
                classification="INTERNAL",
                input_kind="ATTACHMENT",
            )
        )
        return ref

    def body(edition, **data):
        return dict(schema_version=edition, workspace_id=identity["workspace_id"], **data)

    context_ref = identity["protected_inputs"][0]["object_ref"]
    materials[context_ref["object_id"]] = b"Synthetic context."
    context_ref.update(
        digest=digest(materials[context_ref["object_id"]]), size_bytes=len(materials[context_ref["object_id"]])
    )
    prd = store(
        body(
            "curve.synthetic-prd-body/v2",
            initiative_id=identity["initiative_id"],
            requirements=[
                dict(id="FR-008", text="First requirement", acceptance_ids=["AC-10"]),
                dict(id="FR-009", text="Second requirement", acceptance_ids=["AC-11"]),
            ],
            acceptances=[dict(id="AC-10", text="First acceptance"), dict(id="AC-11", text="Second acceptance")],
        )
    )
    identity["prd_content_digest"] = prd["digest"]
    workflow = store(
        body(
            "curve.synthetic-workflow/v2",
            id=identity["workflow_ref"]["entity_id"],
            allowed_conditions=facts["workflow_conditions"]["allowed_conditions"],
            dependency_artifact_refs=[],
        )
    )
    quality = store(
        body(
            "curve.synthetic-quality-policy/v2",
            id=identity["quality_policy_ref"]["entity_id"],
            required_check_ids=["lint", "unit"],
        )
    )
    identity["workflow_ref"]["digest"] = workflow["digest"]
    identity["quality_policy_ref"]["digest"] = quality["digest"]
    repository = identity["repository_inputs"][0]
    policy = store(
        body(
            "curve.synthetic-repository-policy/v2",
            id=repository["repository_policy_ref"]["entity_id"],
            repository_id=repository["repository_ref"]["entity_id"],
            allowed_base_branches=["main"],
            required_check_ids=["security"],
        )
    )
    repository["repository_policy_ref"]["digest"] = policy["digest"]
    repository["context_input_ref"] = deepcopy(context_ref)
    repo = store(
        body(
            "curve.synthetic-repository/v2",
            id=repository["repository_ref"]["entity_id"],
            **{
                key: deepcopy(repository[key])
                for key in ("base_branch", "base_commit", "repository_policy_ref", "context_input_ref")
            },
        )
    )
    repository["repository_ref"]["digest"] = repo["digest"]
    for key in ("workflow_ref", "quality_policy_ref"):
        definition[key] = deepcopy(identity[key])
        facts[key] = deepcopy(identity[key])
    for edge in definition["dependencies"]:
        edge["workflow_ref"] = deepcopy(identity["workflow_ref"])
    definition["repositories"] = deepcopy(identity["repository_inputs"])
    facts["repositories"] = deepcopy(identity["repository_inputs"])
    facts["workflow_conditions"]["workflow_ref"] = deepcopy(identity["workflow_ref"])
    facts["protected_object_refs"] = [deepcopy(item["object_ref"]) for item in identity["protected_inputs"]]
    raw = canonical_json(definition)
    identity["definition_ref"].update(digest=digest(raw), size_bytes=len(raw))
    identity["digest"] = metadata_digest(identity)
    sources = dict(prd=prd, workflow=workflow, quality=quality, repositories=[dict(repository=repo, policy=policy)])
    return raw, identity, facts, sources, materials


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
