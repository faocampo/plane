# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
import hashlib
import json
import uuid

import pytest
from django.test import override_settings

from plane.curve.config import (
    CurvePolicyConfigurationError,
    curve_environment,
    curve_policy_recorder,
    validate_curve_policy_configuration,
)
from plane.curve.policy_evaluator import evaluate_core_policy
from plane.curve.policy_manifest import (
    CORE_POLICY_MANIFEST_DIGEST,
    CORE_POLICY_MANIFEST_PATH,
    PolicyManifestIntegrityError,
    clear_core_policy_manifest_cache,
    load_core_policy_manifest,
)
from plane.curve.policy_types import PolicyEffect


WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"
OPERATION_ID = "22222222-2222-4222-8222-222222222222"
HUMAN = {"actor_type": "HUMAN", "actor_id": "user-123"}
SERVICE = {"actor_type": "SERVICE", "actor_id": "curve-worker"}
PRODUCT_APPROVER = {"actor_type": "HUMAN", "actor_id": "product-approver"}
CODE_APPROVER = {"actor_type": "HUMAN", "actor_id": "code-approver"}


def shell_context():
    return {
        "schema_version": "1.0",
        "workspace_id": WORKSPACE_ID,
        "subject": deepcopy(HUMAN),
        "effective_principal": deepcopy(HUMAN),
        "membership": {
            "workspace_id": WORKSPACE_ID,
            "active": True,
            "plane_role": "MEMBER",
        },
        "roles": ["WORKSPACE_MEMBER"],
        "action": "CURVE.SHELL.VIEW",
        "resource": {
            "workspace_id": WORKSPACE_ID,
            "ref": {
                "resource_type": "WORKSPACE",
                "resource_id": WORKSPACE_ID,
                "resource_version": 1,
            },
            "exists": True,
            "owner": deepcopy(HUMAN),
        },
        "classification": "INTERNAL",
        "environment": "LOCAL",
        "feature_enabled": True,
        "object_acl": None,
        "assignment_context": None,
        "target_context": None,
        "service_authorization": None,
        "evaluated_at": "2026-08-18T12:00:00Z",
        "policy_manifest_digest": CORE_POLICY_MANIFEST_DIGEST,
        "correlation_id": "policy-unit-test",
    }


def operation_context():
    context = shell_context()
    context["action"] = "CURVE.OPERATION.READ"
    context["resource"] = {
        "workspace_id": WORKSPACE_ID,
        "ref": {
            "resource_type": "OPERATION",
            "resource_id": OPERATION_ID,
            "resource_version": 2,
        },
        "exists": True,
        "owner": deepcopy(HUMAN),
    }
    context["object_acl"] = {
        "workspace_id": WORKSPACE_ID,
        "resource_ref": deepcopy(context["resource"]["ref"]),
        "acl_version": 1,
        "allow_principals": [],
        "deny_principals": [],
        "allow_roles": ["WORKSPACE_MEMBER"],
        "deny_roles": [],
    }
    return context


def service_transition_context():
    context = operation_context()
    context["subject"] = deepcopy(SERVICE)
    context["effective_principal"] = deepcopy(SERVICE)
    context["membership"] = None
    context["roles"] = ["TRUSTED_SERVICE"]
    context["action"] = "CURVE.OPERATION.TRANSITION"
    context["object_acl"] = None
    context["service_authorization"] = {
        "authorization_id": "service-auth-1",
        "authorization_version": 1,
        "workspace_id": WORKSPACE_ID,
        "service": deepcopy(SERVICE),
        "active": True,
        "allowed_actions": ["CURVE.OPERATION.TRANSITION"],
        "issued_at": "2026-08-18T11:00:00Z",
        "expires_at": "2026-08-18T13:00:00Z",
    }
    return context


def gate_context():
    context = shell_context()
    context["action"] = "CURVE.GATE.DECIDE.PLAN"
    context["roles"] = ["WORKSPACE_MEMBER", "TECHNICAL_APPROVER"]
    context["resource"] = {
        "workspace_id": WORKSPACE_ID,
        "ref": {
            "resource_type": "EXECUTION_PLAN",
            "resource_id": OPERATION_ID,
            "resource_version": 2,
        },
        "exists": True,
        "owner": deepcopy(PRODUCT_APPROVER),
    }
    context["object_acl"] = {
        "workspace_id": WORKSPACE_ID,
        "resource_ref": deepcopy(context["resource"]["ref"]),
        "acl_version": 1,
        "allow_principals": [deepcopy(HUMAN)],
        "deny_principals": [],
        "allow_roles": [],
        "deny_roles": [],
    }
    context["assignment_context"] = {
        "workspace_id": WORKSPACE_ID,
        "subject_ref": deepcopy(context["resource"]["ref"]),
        "assignment_version": 1,
        "risk_tier": "HIGH",
        "gate_assignments": [
            {
                "role": "PRODUCT_APPROVER",
                "principal": deepcopy(PRODUCT_APPROVER),
                "active": True,
            },
            {
                "role": "TECHNICAL_APPROVER",
                "principal": deepcopy(HUMAN),
                "active": True,
            },
            {
                "role": "CODE_APPROVER",
                "principal": deepcopy(CODE_APPROVER),
                "active": True,
            },
        ],
        "material_contributors": [],
        "low_risk_overlap_allowed": False,
        "overlap_exception_ref": None,
    }
    return context


def target_allowlist_context():
    context = shell_context()
    context["action"] = "CURVE.PROVIDER_CONNECTION.ADMINISTER"
    context["roles"] = ["WORKSPACE_MEMBER", "PLATFORM_ADMINISTRATOR"]
    context["resource"] = {
        "workspace_id": WORKSPACE_ID,
        "ref": {
            "resource_type": "PROVIDER_CONNECTION",
            "resource_id": OPERATION_ID,
            "resource_version": 1,
        },
        "exists": True,
        "owner": None,
    }
    context["target_context"] = {
        "workspace_id": WORKSPACE_ID,
        "configuration_ref": {
            "resource_type": "PROVIDER_CONFIGURATION",
            "resource_id": "33333333-3333-4333-8333-333333333333",
            "resource_version": 1,
        },
        "target_type": "PROVIDER",
        "target_id": "openrouter",
        "allowed_targets": ["openrouter"],
    }
    return context


def test_exact_manifest_bytes_are_available_and_pinned():
    manifest = load_core_policy_manifest()

    assert manifest["policy_key"] == "CURVE_CORE_POLICY"
    assert manifest["policy_version"] == 1
    assert CORE_POLICY_MANIFEST_PATH.is_file()
    assert len(manifest["actions"]) == 10

    with pytest.raises(TypeError):
        manifest["actions"][0]["allowed_roles"] = ()
    with pytest.raises(AttributeError):
        manifest["actions"][0]["allowed_roles"].append("PLATFORM_ADMINISTRATOR")


def test_manifest_loader_rejects_changed_bytes(monkeypatch, tmp_path):
    changed = tmp_path / "core-policy-v1.json"
    changed.write_text(json.dumps({"policy_key": "changed"}), encoding="utf-8")
    monkeypatch.setattr("plane.curve.policy_manifest.CORE_POLICY_MANIFEST_PATH", changed)
    clear_core_policy_manifest_cache()
    try:
        with pytest.raises(PolicyManifestIntegrityError, match="digest mismatch"):
            load_core_policy_manifest()
    finally:
        clear_core_policy_manifest_cache()


def test_shell_member_is_allowed_with_named_projection():
    result = evaluate_core_policy(shell_context())

    assert result.effect is PolicyEffect.ALLOW
    assert result.reason_codes == ("POLICY_ALLOWED",)
    assert result.permitted_projection == (
        "WORKSPACE_ID",
        "WORKSPACE_SLUG",
        "SHELL_STATE",
    )
    assert result.policy_manifest_digest == CORE_POLICY_MANIFEST_DIGEST
    assert result.input_digest.startswith("sha256:")


def test_input_digest_has_domain_prefix_and_normalizes_semantic_sets():
    context = shell_context()
    expected_payload = json.dumps(
        context,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    expected_digest = f"sha256:{hashlib.sha256(b'curve-policy-input:v1\0' + expected_payload).hexdigest()}"

    assert evaluate_core_policy(context).input_digest == expected_digest

    reordered = gate_context()
    original = evaluate_core_policy(reordered).input_digest
    reordered["roles"].reverse()
    reordered["object_acl"]["allow_principals"].reverse()
    reordered["assignment_context"]["gate_assignments"].reverse()
    assert evaluate_core_policy(reordered).input_digest == original


def test_non_json_policy_context_fails_closed_with_safe_digest():
    context = shell_context()
    context["roles"] = [{"invalid-role"}]

    result = evaluate_core_policy(context)

    assert result.effect is PolicyEffect.DENY
    assert result.reason_codes == ("POLICY_CONTEXT_INVALID",)
    assert result.input_digest.startswith("sha256:")


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda value: value.update(feature_enabled=False), "FEATURE_DISABLED"),
        (lambda value: value.update(action="CURVE.UNKNOWN"), "UNKNOWN_ACTION"),
        (
            lambda value: value["resource"].update(workspace_id=str(uuid.uuid4())),
            "WORKSPACE_MISMATCH",
        ),
        (
            lambda value: value.update(
                subject={"actor_type": "AGENT", "actor_id": "agent-1"},
                effective_principal={"actor_type": "AGENT", "actor_id": "agent-1"},
                membership=None,
                roles=[],
            ),
            "AGENT_NOT_ALLOWED",
        ),
        (lambda value: value.update(environment="PRODUCTION"), "ENVIRONMENT_NOT_ALLOWED"),
    ],
)
def test_core_denials_follow_manifest_precedence(mutate, reason):
    context = shell_context()
    if reason == "ENVIRONMENT_NOT_ALLOWED":
        context["action"] = "CURVE.FOUNDATION_PROBE.START"
    mutate(context)

    result = evaluate_core_policy(context)

    assert result.effect is PolicyEffect.DENY
    assert reason in result.reason_codes
    assert result.permitted_projection == ()


def test_malformed_or_unpinned_context_denies_before_policy_evaluation():
    context = shell_context()
    context["policy_manifest_digest"] = "sha256:" + "0" * 64

    result = evaluate_core_policy(context)

    assert result.effect is PolicyEffect.DENY
    assert result.reason_codes == ("POLICY_CONTEXT_INVALID",)


def test_anonymous_sentinel_is_explicitly_unauthenticated():
    context = shell_context()
    context["subject"] = {"actor_type": "SYSTEM", "actor_id": "anonymous"}
    context["effective_principal"] = dict(context["subject"])
    context["membership"] = None
    context["roles"] = []

    result = evaluate_core_policy(context)

    assert result.reason_codes[0] == "UNAUTHENTICATED"


def test_unknown_classification_normalizes_to_restricted_and_denies_shell():
    context = shell_context()
    context["classification"] = "UNKNOWN"

    result = evaluate_core_policy(context)

    assert result.normalized_classification.value == "RESTRICTED"
    assert result.reason_codes == ("CLASSIFICATION_NOT_ALLOWED",)


def test_acl_deny_wins_over_role_allow_and_owner():
    context = operation_context()
    context["object_acl"]["deny_principals"] = [deepcopy(HUMAN)]

    result = evaluate_core_policy(context)

    assert result.effect is PolicyEffect.DENY
    assert result.reason_codes == ("OBJECT_ACL_DENIED",)


def test_operation_owner_can_satisfy_required_acl_when_acl_is_absent():
    context = operation_context()
    context["object_acl"] = None

    result = evaluate_core_policy(context)

    assert result.effect is PolicyEffect.ALLOW


def test_resource_type_and_absence_denials_are_ordered():
    context = shell_context()
    context["resource"]["ref"]["resource_type"] = "OPERATION"
    context["resource"]["exists"] = False
    context["resource"]["owner"] = None

    result = evaluate_core_policy(context)

    assert result.reason_codes == (
        "RESOURCE_TYPE_NOT_ALLOWED",
        "RESOURCE_NOT_FOUND",
    )


def test_effective_principal_mismatch_and_role_floor_cannot_be_repaired_by_acl():
    context = operation_context()
    context["effective_principal"] = deepcopy(PRODUCT_APPROVER)
    context["roles"] = []
    context["object_acl"]["allow_principals"] = [deepcopy(PRODUCT_APPROVER)]

    result = evaluate_core_policy(context)

    assert result.reason_codes[:2] == ("UNSUPPORTED_PRINCIPAL", "ROLE_NOT_ALLOWED")


def test_required_acl_denies_non_owner_without_allow_entry():
    context = operation_context()
    context["resource"]["owner"] = deepcopy(PRODUCT_APPROVER)
    context["object_acl"] = None

    result = evaluate_core_policy(context)

    assert result.reason_codes == ("OBJECT_ACL_REQUIRED",)


def test_valid_high_risk_gate_assignment_is_allowed():
    result = evaluate_core_policy(gate_context())

    assert result.effect is PolicyEffect.ALLOW


def test_gate_assignment_and_separation_fail_closed():
    missing = gate_context()
    missing["assignment_context"] = None
    missing_result = evaluate_core_policy(missing)

    duplicate = gate_context()
    duplicate["assignment_context"]["gate_assignments"][2]["principal"] = deepcopy(HUMAN)
    duplicate_result = evaluate_core_policy(duplicate)

    assert "ASSIGNMENT_REQUIRED" in missing_result.reason_codes
    assert "SEPARATION_OF_DUTY_DENIED" in missing_result.reason_codes
    assert duplicate_result.reason_codes == ("SEPARATION_OF_DUTY_DENIED",)


@pytest.mark.parametrize("risk_tier", ["STANDARD", "LOW"])
def test_gate_overlap_requires_exact_risk_tier_exception(risk_tier):
    context = gate_context()
    context["assignment_context"]["risk_tier"] = risk_tier
    context["assignment_context"]["gate_assignments"][2]["principal"] = deepcopy(HUMAN)

    result = evaluate_core_policy(context)

    assert result.reason_codes == ("SEPARATION_OF_DUTY_DENIED",)


def test_required_target_allowlist_is_exact_and_workspace_bound():
    allowed = evaluate_core_policy(target_allowlist_context())
    missing = target_allowlist_context()
    missing["target_context"]["allowed_targets"] = []
    missing_result = evaluate_core_policy(missing)
    cross_workspace = target_allowlist_context()
    cross_workspace["target_context"]["workspace_id"] = "44444444-4444-4444-8444-444444444444"
    cross_result = evaluate_core_policy(cross_workspace)

    assert allowed.effect is PolicyEffect.ALLOW
    assert missing_result.reason_codes == ("TARGET_ALLOWLIST_REQUIRED",)
    assert cross_result.reason_codes == ("POLICY_CONTEXT_INVALID",)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"active": False}, "SERVICE_AUTHORIZATION_INACTIVE"),
        ({"expires_at": "2026-08-18T12:00:00Z"}, "SERVICE_AUTHORIZATION_EXPIRED"),
        ({"allowed_actions": ["CURVE.OPERATION.READ"]}, "SERVICE_AUTHORIZATION_INVALID"),
    ],
)
def test_service_authorization_is_exact_and_time_bound(change, reason):
    context = service_transition_context()
    context["service_authorization"].update(change)

    result = evaluate_core_policy(context)

    assert result.effect is PolicyEffect.DENY
    assert result.reason_codes == (reason,)


def test_evaluation_is_deterministic_and_reads_no_clock():
    context = operation_context()

    first = evaluate_core_policy(context)
    second = evaluate_core_policy(deepcopy(context))

    assert first == second


@override_settings(
    CURVE_ENABLED=True,
    CURVE_ENVIRONMENT="LOCAL",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api",
)
def test_trusted_policy_configuration_is_explicit():
    validate_curve_policy_configuration()

    assert curve_environment() == "LOCAL"
    assert curve_policy_recorder() == {
        "actor_type": "SERVICE",
        "actor_id": "curve-api",
    }


@pytest.mark.parametrize(
    "settings_override",
    [
        {"CURVE_ENVIRONMENT": "", "CURVE_POLICY_RECORDER_ACTOR_ID": "curve-api"},
        {"CURVE_ENVIRONMENT": "DEVELOPMENT", "CURVE_POLICY_RECORDER_ACTOR_ID": "curve-api"},
        {"CURVE_ENVIRONMENT": "LOCAL", "CURVE_POLICY_RECORDER_ACTOR_ID": ""},
    ],
)
def test_enabled_policy_configuration_fails_closed(settings_override):
    with override_settings(CURVE_ENABLED=True, **settings_override):
        with pytest.raises(CurvePolicyConfigurationError):
            validate_curve_policy_configuration()


@override_settings(
    CURVE_ENABLED=False,
    CURVE_ENVIRONMENT="",
    CURVE_POLICY_RECORDER_ACTOR_ID="",
)
def test_disabled_curve_does_not_require_policy_configuration():
    validate_curve_policy_configuration()
