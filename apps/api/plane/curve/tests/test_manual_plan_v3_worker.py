# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from plane.curve.manual_plan_v2.contracts import ManualPlanError
from plane.curve.manual_plan_v2.validation import InvalidPlan, canonical_json, digest, metadata_digest
from plane.curve.manual_plan_v3.validation import ROOT, derive_semantic_facts
from plane.curve.manual_plan_v3.validator_worker import validate_in_worker
from plane.curve.tests.manual_plan_v2.host.semantic_fixture import semantic_case

pytestmark = pytest.mark.unit


def captured_plan():
    raw, identity, facts, sources, materials = semantic_case()
    definition = json.loads(raw)
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
    raw = canonical_json(definition)
    identity["definition_ref"].update(digest=digest(raw), size_bytes=len(raw))
    identity["digest"] = metadata_digest(identity)
    return SimpleNamespace(
        definition=raw, identity=identity, facts=facts, semantic_sources=sources, materials=materials
    )


def test_two_stage_facts_are_derived_from_retained_bytes():
    captured = captured_plan()
    assert (
        derive_semantic_facts(captured.identity, captured.semantic_sources, captured.materials, captured.facts)
        == captured.facts
    )


@pytest.mark.parametrize("tamper", ["body", "facts", "gate", "historical-role"])
def test_semantic_sources_cannot_weaken_successor_plan(tamper):
    captured = captured_plan()
    if tamper == "body":
        key = captured.semantic_sources["prd"]["object_id"]
        captured.materials[key] += b" "
    elif tamper == "facts":
        captured.facts["required_check_ids"] = []
    elif tamper == "gate":
        captured.identity["gate_assignments"].pop()
        captured.identity["digest"] = metadata_digest(captured.identity)
    else:
        captured.facts["code_approver_id"] = "historical-role"
    with pytest.raises(InvalidPlan):
        derive_semantic_facts(captured.identity, captured.semantic_sources, captured.materials, captured.facts)


def test_linux_worker_returns_byte_bound_successor_receipt():
    captured = captured_plan()
    receipt = validate_in_worker(captured)
    assert receipt["validator_edition"] == "DETERMINISTIC_SDLC_MANUAL_PLAN_V3"
    assert receipt["input_identity_digest"] == captured.identity["digest"]
    assert receipt["definition_digest"] == digest(captured.definition)


def test_linux_worker_rejects_modified_body_without_returning_its_contents():
    captured = captured_plan()
    captured.materials[captured.semantic_sources["prd"]["object_id"]] = b"private-test-sentinel"
    with pytest.raises(ManualPlanError) as error:
        validate_in_worker(captured)
    assert error.value.code == "MANUAL_PLAN_DRAFT_VALIDATION_FAILED"
    assert "private-test-sentinel" not in str(error.value)
