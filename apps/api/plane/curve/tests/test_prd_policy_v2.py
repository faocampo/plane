# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
import hashlib

import pytest

from plane.curve.policy_evaluator import evaluate_core_policy
from plane.curve.policy_manifest import (
    PRD_POLICY_MANIFEST_DIGEST,
    PRD_POLICY_V2_MANIFEST_DIGEST,
    PRD_POLICY_V2_MANIFEST_PATH,
    PolicyManifestIntegrityError,
    clear_core_policy_manifest_cache,
    load_core_policy_manifest_for_digest,
    load_prd_policy_v2_manifest,
)
from plane.curve.policy_types import PolicyEffect
from plane.curve.tests.test_prd_policy import ACTIONS, prd_context

pytestmark = pytest.mark.unit


def two_stage_context(action="APPROVE"):
    context = prd_context(action)
    context["policy_manifest_digest"] = PRD_POLICY_V2_MANIFEST_DIGEST
    context["assignment_context"]["gate_assignments"].pop()
    return context


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("risk", ["LOW", "STANDARD", "HIGH"])
def test_two_approvers_can_submit_and_review_under_successor_policy(action, risk):
    context = two_stage_context(action)
    context["assignment_context"]["risk_tier"] = risk
    before = deepcopy(context)
    result = evaluate_core_policy(context)
    assert result.effect is PolicyEffect.ALLOW
    assert (result.policy_key, result.policy_version) == ("CURVE_PRD_POLICY", 2)
    assert result.policy_manifest_digest == PRD_POLICY_V2_MANIFEST_DIGEST
    assert result.permitted_projection == ("NO_BODY",)
    assert context == before


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize(
    "bypass", ["missing", "extra", "inactive", "service", "duplicate-role", "code-role", "overlap"]
)
def test_two_stage_policy_denies_invalid_assignments(action, bypass):
    context = two_stage_context(action)
    gates = context["assignment_context"]["gate_assignments"]
    if bypass == "missing":
        gates.pop()
    elif bypass == "extra":
        gates.append(prd_context()["assignment_context"]["gate_assignments"][2])
    elif bypass == "inactive":
        gates[1]["active"] = False
    elif bypass == "service":
        gates[1]["principal"]["actor_type"] = "SERVICE"
    elif bypass == "duplicate-role":
        gates[1]["role"] = "PRODUCT_APPROVER"
    elif bypass == "code-role":
        gates[1]["role"] = "CODE_APPROVER"
    else:
        gates[1]["principal"] = deepcopy(gates[0]["principal"])
    result = evaluate_core_policy(context)
    assert result.effect is PolicyEffect.DENY
    assert "SEPARATION_OF_DUTY_DENIED" in result.reason_codes


def test_low_risk_retains_existing_overlap_rule_for_two_assignments():
    context = two_stage_context()
    assignment = context["assignment_context"]
    assignment["risk_tier"] = "LOW"
    assignment["gate_assignments"][1]["principal"] = deepcopy(context["subject"])
    assert evaluate_core_policy(context).effect is PolicyEffect.ALLOW
    assignment["risk_tier"] = "HIGH"
    assert evaluate_core_policy(context).effect is PolicyEffect.DENY


@pytest.mark.parametrize("action", ["APPROVE", "REQUEST_CHANGES", "REJECT"])
def test_technical_or_code_approver_cannot_make_product_decision(action):
    for role in ("TECHNICAL_APPROVER", "CODE_APPROVER"):
        context = two_stage_context(action)
        context["roles"] = ["WORKSPACE_MEMBER", role]
        assert evaluate_core_policy(context).effect is PolicyEffect.DENY


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize(
    "bypass", ["inactive-member", "missing-acl", "explicit-deny", "foreign-acl", "stale-acl", "disabled"]
)
def test_successor_preserves_membership_access_and_feature_checks(action, bypass):
    context = two_stage_context(action)
    if bypass == "inactive-member":
        context["membership"]["active"] = False
    elif bypass == "missing-acl":
        context["object_acl"] = None
    elif bypass == "explicit-deny":
        context["object_acl"]["deny_principals"] = [deepcopy(context["subject"])]
    elif bypass == "foreign-acl":
        context["object_acl"]["workspace_id"] = "other-workspace"
    elif bypass == "stale-acl":
        context["object_acl"]["resource_ref"]["resource_version"] = 2
    else:
        context["feature_enabled"] = False
    assert evaluate_core_policy(context).effect is PolicyEffect.DENY


def test_historical_policy_keeps_three_role_semantics():
    assert evaluate_core_policy(prd_context()).effect is PolicyEffect.ALLOW
    context = two_stage_context()
    context["policy_manifest_digest"] = PRD_POLICY_MANIFEST_DIGEST
    assert evaluate_core_policy(context).effect is PolicyEffect.DENY


def test_successor_manifest_is_pinned_and_immutable():
    actual_digest = "sha256:" + hashlib.sha256(PRD_POLICY_V2_MANIFEST_PATH.read_bytes()).hexdigest()
    assert actual_digest == PRD_POLICY_V2_MANIFEST_DIGEST
    manifest = load_prd_policy_v2_manifest()
    assert load_core_policy_manifest_for_digest(PRD_POLICY_V2_MANIFEST_DIGEST) is manifest
    with pytest.raises(TypeError):
        manifest["actions"][0]["owner_satisfies_acl"] = False


def test_modified_successor_manifest_fails_closed(tmp_path, monkeypatch):
    changed = tmp_path / "policy.json"
    changed.write_bytes(PRD_POLICY_V2_MANIFEST_PATH.read_bytes() + b" ")
    monkeypatch.setattr("plane.curve.policy_manifest.PRD_POLICY_V2_MANIFEST_PATH", changed)
    clear_core_policy_manifest_cache()
    try:
        with pytest.raises(PolicyManifestIntegrityError):
            load_prd_policy_v2_manifest()
    finally:
        clear_core_policy_manifest_cache()
