"""Synthetic bytes shared by host and real ORM tests, with no model imports."""

from copy import deepcopy
import json
import uuid
from manual_plan_v2.validation import ROOT, canonical_json, digest, metadata_digest


def fixture(name):
    return json.loads((ROOT / "fixtures" / (name + ".json")).read_text())


def semantic_case(replacements=None):
    definition, identity, facts = (
        fixture(name) for name in ("definition.valid", "input-identity.valid", "immutable-semantic-facts")
    )
    if replacements:

        def remap(value):
            if isinstance(value, dict):
                return {key: remap(item) for key, item in value.items()}
            if isinstance(value, list):
                return [remap(item) for item in value]
            return replacements.get(value, value) if isinstance(value, str) else value

        definition, identity, facts = map(remap, (definition, identity, facts))
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
