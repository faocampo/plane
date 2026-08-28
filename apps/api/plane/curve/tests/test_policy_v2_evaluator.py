# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
import hashlib
import json

import pytest

from plane.curve.policy_evaluator import evaluate_core_policy
from plane.curve.policy_manifest import (
    CORE_POLICY_MANIFEST_DIGEST,
    CORE_POLICY_MANIFEST_PATH,
    CORE_POLICY_V2_MANIFEST_DIGEST,
    CORE_POLICY_V2_MANIFEST_PATH,
    PolicyManifestIntegrityError,
    clear_core_policy_manifest_cache,
    load_core_policy_manifest,
    load_core_policy_manifest_for_digest,
    load_core_policy_v2_manifest,
)
from plane.curve.policy_types import PolicyEffect


WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"
CONNECTION_ID = "22222222-2222-4222-8222-222222222222"
HUMAN = {"actor_type": "HUMAN", "actor_id": "user-123"}


def provider_registration_context():
    return {
        "schema_version": "1.0",
        "workspace_id": WORKSPACE_ID,
        "subject": deepcopy(HUMAN),
        "effective_principal": deepcopy(HUMAN),
        "membership": {
            "workspace_id": WORKSPACE_ID,
            "active": True,
            "plane_role": "ADMIN",
        },
        "roles": ["WORKSPACE_MEMBER", "PLATFORM_ADMINISTRATOR"],
        "action": "CURVE.PROVIDER_CONNECTION.REGISTER",
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
        "target_context": {
            "workspace_id": WORKSPACE_ID,
            "configuration_ref": {
                "resource_type": "PROVIDER_REGISTRY_MANIFEST",
                "resource_id": "M0-S9A",
                "resource_version": 1,
            },
            "target_type": "PROVIDER",
            "target_id": "curve.fake-local@1.0.0",
            "allowed_targets": ["curve.fake-local@1.0.0"],
        },
        "service_authorization": None,
        "evaluated_at": "2026-08-27T12:00:00Z",
        "policy_manifest_digest": CORE_POLICY_V2_MANIFEST_DIGEST,
        "correlation_id": "m0-s9a-policy-v2-test",
    }


def provider_administration_context():
    context = provider_registration_context()
    context["action"] = "CURVE.PROVIDER_CONNECTION.ADMINISTER"
    context["resource"] = {
        "workspace_id": WORKSPACE_ID,
        "ref": {
            "resource_type": "PROVIDER_CONNECTION",
            "resource_id": CONNECTION_ID,
            "resource_version": 3,
        },
        "exists": True,
        "owner": None,
    }
    return context


def test_policy_v2_manifest_is_exact_immutable_and_supersedes_v1():
    v1_bytes = CORE_POLICY_MANIFEST_PATH.read_bytes()
    v2_bytes = CORE_POLICY_V2_MANIFEST_PATH.read_bytes()
    manifest = load_core_policy_v2_manifest()

    assert f"sha256:{hashlib.sha256(v1_bytes).hexdigest()}" == CORE_POLICY_MANIFEST_DIGEST
    assert f"sha256:{hashlib.sha256(v2_bytes).hexdigest()}" == CORE_POLICY_V2_MANIFEST_DIGEST
    assert manifest["policy_version"] == 2
    assert manifest["supersedes"] == {
        "policy_version": 1,
        "manifest_digest": CORE_POLICY_MANIFEST_DIGEST,
    }
    assert load_core_policy_manifest_for_digest(CORE_POLICY_MANIFEST_DIGEST) is load_core_policy_manifest()
    assert load_core_policy_manifest_for_digest(CORE_POLICY_V2_MANIFEST_DIGEST) is manifest
    assert load_core_policy_manifest_for_digest("sha256:" + "0" * 64) is None
    with pytest.raises(TypeError):
        manifest["trusted_role_sources"][0]["plane_role"] = 15


def test_policy_v2_manifest_loader_rejects_changed_bytes(monkeypatch, tmp_path):
    changed = tmp_path / "core-policy-v2.json"
    changed.write_text(json.dumps({"policy_key": "changed"}), encoding="utf-8")
    monkeypatch.setattr("plane.curve.policy_manifest.CORE_POLICY_V2_MANIFEST_PATH", changed)
    clear_core_policy_manifest_cache()
    try:
        with pytest.raises(PolicyManifestIntegrityError, match="digest mismatch"):
            load_core_policy_v2_manifest()
    finally:
        clear_core_policy_manifest_cache()


def test_policy_v2_allows_exact_provider_registration_and_administration_contexts():
    registration = evaluate_core_policy(provider_registration_context())
    administration = evaluate_core_policy(provider_administration_context())

    assert registration.effect is PolicyEffect.ALLOW
    assert registration.reason_codes == ("POLICY_ALLOWED",)
    assert registration.permitted_projection == ("NO_BODY",)
    assert registration.policy_version == 2
    assert registration.policy_manifest_digest == CORE_POLICY_V2_MANIFEST_DIGEST
    assert administration.effect is PolicyEffect.ALLOW
    assert administration.policy_version == 2


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda value: value.update(roles=["WORKSPACE_MEMBER"]), "ROLE_NOT_ALLOWED"),
        (lambda value: value.update(environment="STAGING"), "ENVIRONMENT_NOT_ALLOWED"),
        (lambda value: value.update(classification="CONFIDENTIAL"), "CLASSIFICATION_NOT_ALLOWED"),
        (
            lambda value: value["target_context"].update(target_id="curve.unknown@1.0.0"),
            "TARGET_NOT_ALLOWED",
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
        (
            lambda value: value.update(
                subject={"actor_type": "SERVICE", "actor_id": "provider-service"},
                effective_principal={"actor_type": "SERVICE", "actor_id": "provider-service"},
                membership=None,
                roles=["TRUSTED_SERVICE"],
            ),
            "UNSUPPORTED_PRINCIPAL",
        ),
    ],
)
def test_policy_v2_provider_registration_denies_widened_authority(mutate, reason):
    context = provider_registration_context()
    mutate(context)

    result = evaluate_core_policy(context)

    assert result.effect is PolicyEffect.DENY
    assert reason in result.reason_codes
    assert result.policy_version == 2
    assert result.policy_manifest_digest == CORE_POLICY_V2_MANIFEST_DIGEST


def test_unknown_policy_digest_fails_closed_without_silent_v2_selection():
    context = provider_registration_context()
    context["policy_manifest_digest"] = "sha256:" + "0" * 64

    result = evaluate_core_policy(context)

    assert result.effect is PolicyEffect.DENY
    assert result.reason_codes == ("POLICY_CONTEXT_INVALID",)
    assert result.policy_version == 1
    assert result.policy_manifest_digest == CORE_POLICY_MANIFEST_DIGEST
