# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from plane.curve.manual_plan_v2.validation import (
    InvalidPlan, canonical_json, digest, metadata_digest, validate_definition as validate_v2,
)
from plane.curve.manual_plan_v3.validation import ROOT, candidate_schemas, validate_definition

pytestmark = pytest.mark.unit
FIXTURES = Path(__file__).parents[1] / "manual_plan_v2" / "contract_snapshot" / "fixtures"


def bundle():
    definition = json.loads((FIXTURES / "definition.valid.json").read_text())
    identity = json.loads((FIXTURES / "input-identity.valid.json").read_text())
    facts = json.loads((FIXTURES / "immutable-semantic-facts.json").read_text())
    definition["schema_version"] = "curve.manual-plan-definition/v3-candidate"
    identity["schema_version"] = "curve.manual-plan-input-identity/v3-candidate"
    profile = json.loads((ROOT / "manual-plan-profile-v3.json").read_text())
    profile_ref = dict(entity_id=profile["id"], digest=digest((ROOT / "manual-plan-profile-v3.json").read_bytes()))
    for value in (definition, identity, facts):
        value["manual_profile_ref"] = deepcopy(profile_ref)
    for item in definition["slices"]:
        del item["code_approver"]
    identity["gate_assignments"] = [g for g in identity["gate_assignments"] if g["gate_type"] != "CODE_READINESS"]
    del facts["code_approver_id"]
    return definition, identity, facts


def validate_bundle(definition, identity, facts):
    raw = canonical_json(definition)
    identity["definition_ref"]["digest"] = digest(raw)
    identity["definition_ref"]["size_bytes"] = len(raw)
    identity["digest"] = metadata_digest(identity)
    return validate_definition(raw, identity, facts)


def test_plan_validates_without_code_approver_and_has_successor_receipt():
    result = validate_bundle(*bundle())
    assert result["result"] == "VALID"
    assert result["validator_edition"] == "DETERMINISTIC_SDLC_MANUAL_PLAN_V3"
    assert result["required_conditions"] == "FUTURE_NOT_ASSERTED"


def test_legacy_plan_still_validates_under_its_original_contract():
    raw = (FIXTURES / "definition.valid.json").read_bytes()
    identity = json.loads((FIXTURES / "input-identity.valid.json").read_text())
    facts = json.loads((FIXTURES / "immutable-semantic-facts.json").read_text())
    assert validate_v2(raw, identity, facts)["validator_edition"] == "DETERMINISTIC_SDLC_MANUAL_PLAN_V2"


@pytest.mark.parametrize("change", ["code-field", "code-gate", "one-gate", "overlap", "missing-quality", "old-facts"])
def test_successor_rejects_legacy_role_and_preserves_other_plan_requirements(change):
    definition, identity, facts = bundle()
    if change == "code-field":
        definition["slices"][0]["code_approver"] = deepcopy(definition["slices"][0]["owner"])
    elif change == "code-gate":
        identity["gate_assignments"][0]["gate_type"] = "CODE_READINESS"
    elif change == "one-gate":
        identity["gate_assignments"].pop()
    elif change == "overlap":
        identity["gate_assignments"][0]["approver_user_id"] = identity["gate_assignments"][1]["approver_user_id"]
    elif change == "missing-quality":
        definition["slices"][0]["verification_steps"] = []
    else:
        facts["code_approver_id"] = "old-code-approver"
    with pytest.raises(InvalidPlan):
        validate_bundle(definition, identity, facts)


def test_successor_cannot_be_reinterpreted_under_historical_schema():
    definition, identity, facts = bundle()
    raw = canonical_json(definition)
    with pytest.raises(InvalidPlan):
        validate_v2(raw, identity, facts)


@pytest.mark.parametrize("change", ["bytes", "extra", "missing", "symlink"])
def test_successor_contract_tampering_fails_closed(tmp_path, change):
    directory = tmp_path / "contracts"
    shutil.copytree(ROOT, directory)
    target = directory / "common-v3.schema.json"
    if change == "bytes":
        target.write_bytes(target.read_bytes() + b" ")
    elif change == "extra":
        (directory / "extra.json").write_text("{}")
    elif change == "missing":
        target.unlink()
    else:
        target.unlink()
        target.symlink_to(ROOT / "common-v3.schema.json")
    with pytest.raises(InvalidPlan):
        candidate_schemas(directory)
