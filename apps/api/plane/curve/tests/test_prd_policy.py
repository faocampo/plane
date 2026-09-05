# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
import hashlib

import pytest

from plane.curve.policy_evaluator import evaluate_core_policy
from plane.curve.policy_manifest import (
    PRD_POLICY_MANIFEST_DIGEST,
    PRD_POLICY_MANIFEST_PATH,
    PolicyManifestIntegrityError,
    clear_core_policy_manifest_cache,
    load_prd_policy_manifest,
)
from plane.curve.policy_types import PolicyEffect
from plane.curve.tests.test_policy_v2_evaluator import provider_registration_context


pytestmark = pytest.mark.unit
ACTIONS = ["SUBMIT", "APPROVE", "REQUEST_CHANGES", "REJECT"]


def prd_context(action="APPROVE"):
    context = provider_registration_context()
    context["policy_manifest_digest"] = PRD_POLICY_MANIFEST_DIGEST
    context["action"] = f"CURVE.PRD.{action}"
    context["roles"] = ["WORKSPACE_MEMBER", "PRODUCT_APPROVER"]
    context["resource"]["ref"] = {
        "resource_type": "INITIATIVE",
        "resource_id": context["resource"]["ref"]["resource_id"],
        "resource_version": 3,
    }
    context["resource"]["owner"] = {"actor_type": "HUMAN", "actor_id": "creator"}
    context["target_context"] = None
    context["object_acl"] = dict(
        workspace_id=context["workspace_id"],
        resource_ref=deepcopy(context["resource"]["ref"]),
        acl_version=1,
        allow_principals=[deepcopy(context["subject"])],
        deny_principals=[],
        allow_roles=[],
        deny_roles=[],
    )
    context["assignment_context"] = dict(
        workspace_id=context["workspace_id"],
        subject_ref=deepcopy(context["resource"]["ref"]),
        assignment_version=1,
        risk_tier="STANDARD",
        gate_assignments=[
            dict(role="PRODUCT_APPROVER", principal=deepcopy(context["subject"]), active=True),
            dict(role="TECHNICAL_APPROVER", principal={"actor_type": "HUMAN", "actor_id": "technical"}, active=True),
            dict(role="CODE_APPROVER", principal={"actor_type": "HUMAN", "actor_id": "code"}, active=True),
        ],
        material_contributors=[],
        overlap_exception_ref=None,
        low_risk_overlap_allowed=False,
    )
    return context


@pytest.mark.parametrize("action", ACTIONS)
def test_exact_prd_action_has_separate_policy_identity_and_no_body_projection(action):
    context = prd_context(action)
    before = deepcopy(context)
    result = evaluate_core_policy(context)
    assert result.effect is PolicyEffect.ALLOW
    assert result.policy_key == "CURVE_PRD_POLICY" and result.policy_version == 1
    assert result.policy_manifest_digest == PRD_POLICY_MANIFEST_DIGEST
    assert result.permitted_projection == ("NO_BODY",) and context == before


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize(
    "change", ["inactive", "feature-disabled", "missing-acl", "denied-acl", "foreign-acl", "old-acl"]
)
def test_prd_commands_require_current_scoped_membership_and_object_access(action, change):
    context = prd_context(action)
    if change == "inactive":
        context["membership"]["active"] = False
    elif change == "feature-disabled":
        context["feature_enabled"] = False
    elif change == "missing-acl":
        context["object_acl"] = None
    elif change == "denied-acl":
        context["object_acl"]["deny_principals"] = [context["subject"]]
    elif change == "foreign-acl":
        context["object_acl"]["workspace_id"] = "foreign"
    else:
        context["object_acl"]["resource_ref"]["resource_version"] = 2
    assert evaluate_core_policy(context).effect is PolicyEffect.DENY


def test_creator_can_submit_but_explicit_deny_still_wins():
    context = prd_context("SUBMIT")
    context["resource"]["owner"] = deepcopy(context["subject"])
    context["object_acl"] = None
    assert evaluate_core_policy(context).effect is PolicyEffect.ALLOW
    context["object_acl"] = prd_context()["object_acl"]
    context["object_acl"]["deny_principals"] = [context["subject"]]
    assert evaluate_core_policy(context).effect is PolicyEffect.DENY


def test_contributor_requires_explicit_object_grant_not_general_workspace_role():
    context = prd_context("SUBMIT")
    context["roles"] = ["WORKSPACE_MEMBER"]
    assert evaluate_core_policy(context).effect is PolicyEffect.ALLOW
    context["object_acl"]["allow_principals"] = []
    assert evaluate_core_policy(context).effect is PolicyEffect.DENY


@pytest.mark.parametrize("action", ["APPROVE", "REQUEST_CHANGES", "REJECT"])
def test_administrator_or_creator_cannot_substitute_for_assigned_product_approver(action):
    context = prd_context(action)
    context["resource"]["owner"] = deepcopy(context["subject"])
    context["roles"] = ["WORKSPACE_MEMBER", "PLATFORM_ADMINISTRATOR"]
    assert evaluate_core_policy(context).effect is PolicyEffect.DENY
    context["roles"].append("PRODUCT_APPROVER")
    context["assignment_context"]["gate_assignments"][0]["principal"]["actor_id"] = "other-product-approver"
    assert evaluate_core_policy(context).effect is PolicyEffect.DENY


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("risk", ["STANDARD", "HIGH"])
@pytest.mark.parametrize("bypass", ["overlap", "missing", "extra", "inactive", "service", "wrong-role", "invalid-role"])
def test_all_three_current_humans_and_strict_risk_separation_are_required(action, risk, bypass):
    context = prd_context(action)
    assignment = context["assignment_context"]
    assignment["risk_tier"] = risk
    gates = assignment["gate_assignments"]
    if bypass == "overlap":
        gates[2]["principal"] = deepcopy(gates[1]["principal"])
        assignment["overlap_exception_ref"] = {"resource_type": "EXCEPTION", "resource_id": "synthetic"}
        assignment["low_risk_overlap_allowed"] = True
    elif bypass == "missing":
        gates.pop()
    elif bypass == "extra":
        gates.append(deepcopy(gates[0]))
    elif bypass == "inactive":
        gates[2]["active"] = False
    elif bypass == "service":
        gates[2]["principal"]["actor_type"] = "SERVICE"
    elif bypass == "wrong-role":
        gates[2]["role"] = "TECHNICAL_APPROVER"
    else:
        gates[2]["role"] = []
    result = evaluate_core_policy(context)
    assert result.effect is PolicyEffect.DENY
    assert "SEPARATION_OF_DUTY_DENIED" in result.reason_codes


@pytest.mark.parametrize("action", ACTIONS)
def test_low_risk_allows_overlap_but_requires_three_active_assignments(action):
    context = prd_context(action)
    context["assignment_context"]["risk_tier"] = "LOW"
    for gate in context["assignment_context"]["gate_assignments"]:
        gate["principal"] = deepcopy(context["subject"])
    assert evaluate_core_policy(context).effect is PolicyEffect.ALLOW
    context["assignment_context"]["gate_assignments"].pop()
    assert evaluate_core_policy(context).effect is PolicyEffect.DENY


@pytest.mark.parametrize("actor_type", ["SERVICE", "AGENT", "SYSTEM"])
def test_nonhuman_principals_cannot_submit_or_review(actor_type):
    for action in ACTIONS:
        context = prd_context(action)
        context["subject"]["actor_type"] = context["effective_principal"]["actor_type"] = actor_type
        assert evaluate_core_policy(context).effect is PolicyEffect.DENY


def test_policy_bytes_are_pinned_and_loaded_immutably():
    assert "sha256:" + hashlib.sha256(PRD_POLICY_MANIFEST_PATH.read_bytes()).hexdigest() == PRD_POLICY_MANIFEST_DIGEST
    with pytest.raises(TypeError):
        load_prd_policy_manifest()["actions"][0]["owner_satisfies_acl"] = False


def test_modified_policy_fails_closed(tmp_path, monkeypatch):
    candidate = tmp_path / "changed-policy.json"
    candidate.write_bytes(PRD_POLICY_MANIFEST_PATH.read_bytes() + b" ")
    monkeypatch.setattr("plane.curve.policy_manifest.PRD_POLICY_MANIFEST_PATH", candidate)
    clear_core_policy_manifest_cache()
    try:
        with pytest.raises(PolicyManifestIntegrityError):
            load_prd_policy_manifest()
    finally:
        clear_core_policy_manifest_cache()
