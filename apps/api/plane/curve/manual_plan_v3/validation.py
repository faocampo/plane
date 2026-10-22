# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Pure successor plan validation. HTTP authorization remains server-owned."""

from pathlib import Path
from plane.curve.manual_plan_v2.validation import (
    MAX_DEFINITION,
    MAX_INTEGER as MAX_INTEGER,
    InvalidPlan as InvalidPlan,
    canonical_json as canonical_json,
    parse_typed_initiative_etag as parse_typed_initiative_etag,
    digest,
    metadata_digest,
    parse_strict_json,
    require,
    validate_definition_semantics,
    validate_input_identity,
    validate_schema,
)

ROOT = Path(__file__).parent / "contract_snapshot"
MANIFEST_DIGEST = "sha256:f06c6aa28605c43acbdd45332dc4619354fa8ec9190caa91207f4b322ac0a8d2"
APPROVAL_GATES = ("PLAN_APPROVAL", "PRD_APPROVAL")


def candidate_schemas(root=ROOT):
    require(not root.is_symlink(), "CONTRACT_UNAVAILABLE")
    manifest_path = root / "manifest-v3.json"
    require(not manifest_path.is_symlink(), "CONTRACT_UNAVAILABLE")
    raw = manifest_path.read_bytes()
    require(digest(raw) == MANIFEST_DIGEST, "CONTRACT_UNAVAILABLE")
    manifest = parse_strict_json(raw)
    require(set(manifest) == {p.name for p in root.iterdir() if p.name != "manifest-v3.json"}, "CONTRACT_UNAVAILABLE")
    schemas = {}
    for name, expected in manifest.items():
        path = root / name
        require(path.is_file() and not path.is_symlink(), "CONTRACT_UNAVAILABLE")
        raw = path.read_bytes()
        require(digest(raw) == expected, "CONTRACT_UNAVAILABLE")
        if name.endswith(".schema.json"):
            schemas[name] = parse_strict_json(raw)
    profile = parse_strict_json((root / "manual-plan-profile-v3.json").read_bytes())
    validate_schema("manual-plan-profile-v3.schema.json", profile, schemas)
    return schemas


def validate_definition(raw, identity, facts):
    schemas = candidate_schemas()
    definition = parse_strict_json(raw, max_bytes=MAX_DEFINITION)
    validate_schema("manual-plan-definition-v3.schema.json", definition, schemas)
    validate_schema("manual-plan-input-identity-v3.schema.json", identity, schemas)
    ref = identity["definition_ref"]
    require(
        ref["digest"] == digest(raw) and ref["size_bytes"] == len(raw) and ref["media_type"] == "application/json",
        "DEFINITION_IDENTITY_MISMATCH",
    )
    require("code_approver_id" not in facts, "LEGACY_APPROVAL_FACTS")
    validate_definition_semantics(definition, facts, require_code_approver=False)
    validate_input_identity(identity, definition, approval_gates=APPROVAL_GATES)
    receipt = dict(
        schema_version="curve.manual-plan-validation-receipt/v3-candidate",
        validator_edition="DETERMINISTIC_SDLC_MANUAL_PLAN_V3",
        definition_digest=digest(raw),
        input_identity_digest=identity["digest"],
        result="VALID",
        repository_count=len(definition["repositories"]),
        slice_count=len(definition["slices"]),
        edge_count=len(definition["dependencies"]),
        required_conditions="FUTURE_NOT_ASSERTED",
    )
    receipt["digest"] = metadata_digest(receipt)
    validate_schema("manual-plan-validation-receipt-v3.schema.json", receipt, schemas)
    return receipt


def derive_semantic_facts(identity, sources, materials, native_facts):
    """Bind the two-stage plan to exact retained source bytes and native facts."""
    from plane.curve.manual_plan_v2.validation import derive_semantic_facts as derive

    schemas = candidate_schemas()
    validate_schema("manual-plan-input-identity-v3.schema.json", identity, schemas)
    require("code_approver_id" not in native_facts, "LEGACY_APPROVAL_FACTS")
    return derive(identity, sources, materials, native_facts, require_code_approver=False)
