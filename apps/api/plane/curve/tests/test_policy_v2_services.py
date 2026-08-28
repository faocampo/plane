# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from types import MappingProxyType, SimpleNamespace
import uuid

import pytest
from django.db import transaction
from django.test import override_settings

from plane.curve.models import (
    AuditOutcome,
    PolicyDecision,
    ProviderConnection,
    ProviderConnectionStatus,
    ProviderEnvironment,
    ProviderType,
)
from plane.curve.policy_evaluator import evaluate_core_policy
from plane.curve.policy_manifest import (
    CORE_POLICY_MANIFEST_DIGEST,
    CORE_POLICY_V2_MANIFEST_DIGEST,
)
from plane.curve.policy_services import (
    AuthorizedPolicyReceipt,
    CurvePolicyResourceNotFound,
    assert_active_mutation_receipt,
    build_provider_administration_context,
    build_provider_registration_context,
    execute_authorized_mutation,
    policy_decision_ref_for_receipt,
)
from plane.curve.policy_types import PolicyEffect
from plane.db.models import User, Workspace, WorkspaceMember
import plane.curve.policy_services as policy_services
import plane.curve.services as curve_services


pytestmark = [pytest.mark.unit, pytest.mark.django_db]


def _user(email):
    return User.objects.create(email=email, username=email)


def _workspace(name, slug, owner, *, role=20, is_active=True):
    workspace = Workspace.objects.create(name=name, slug=slug, owner=owner)
    WorkspaceMember.objects.create(
        workspace=workspace,
        member=owner,
        role=role,
        is_active=is_active,
    )
    return workspace


def _request(user):
    return SimpleNamespace(
        user=user,
        roles=["PLATFORM_ADMINISTRATOR"],
        target_id="curve.untrusted@9.9.9",
    )


def _connection(workspace, actor):
    return ProviderConnection.objects.create(
        workspace_id=workspace.id,
        provider_type=ProviderType.FAKE_LOCAL,
        adapter_key="curve.fake-local",
        adapter_version="1.0.0",
        environment=ProviderEnvironment.LOCAL,
        display_name="Synthetic local provider",
        configuration_digest="sha256:" + "a" * 64,
        allowed_classifications=["INTERNAL"],
        status=ProviderConnectionStatus.PENDING_VALIDATION,
        created_by=actor,
        updated_by=actor,
    )


@override_settings(
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha"}),
    CURVE_ENVIRONMENT="LOCAL",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api-test",
)
def test_registration_context_derives_role_and_target_from_trusted_sources():
    user = _user("provider-admin@example.com")
    workspace = _workspace("Alpha", "alpha", user, role=20)

    with transaction.atomic():
        context = build_provider_registration_context(
            request=_request(user),
            workspace_slug="alpha",
            correlation_id="provider-registration",
        )

    assert context["workspace_id"] == str(workspace.id)
    assert context["action"] == "CURVE.PROVIDER_CONNECTION.REGISTER"
    assert context["roles"] == ["WORKSPACE_MEMBER", "PLATFORM_ADMINISTRATOR"]
    assert context["membership"]["plane_role"] == "ADMIN"
    assert context["resource"] == {
        "workspace_id": str(workspace.id),
        "ref": {
            "resource_type": "WORKSPACE",
            "resource_id": str(workspace.id),
            "resource_version": 1,
        },
        "exists": True,
        "owner": {"actor_type": "HUMAN", "actor_id": str(user.id)},
    }
    assert context["target_context"] == {
        "workspace_id": str(workspace.id),
        "configuration_ref": {
            "resource_type": "PROVIDER_REGISTRY_MANIFEST",
            "resource_id": "M0-S9A",
            "resource_version": 1,
        },
        "target_type": "PROVIDER",
        "target_id": "curve.fake-local@1.0.0",
        "allowed_targets": ["curve.fake-local@1.0.0"],
    }
    assert context["policy_manifest_digest"] == CORE_POLICY_V2_MANIFEST_DIGEST
    assert evaluate_core_policy(context).effect is PolicyEffect.ALLOW


@pytest.mark.parametrize("role", [15, 5])
@override_settings(
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha"}),
    CURVE_ENVIRONMENT="LOCAL",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api-test",
)
def test_registration_context_does_not_widen_non_admin_plane_roles(role):
    user = _user(f"provider-role-{role}@example.com")
    _workspace("Alpha", "alpha", user, role=role)

    with transaction.atomic():
        context = build_provider_registration_context(
            request=_request(user),
            workspace_slug="alpha",
            correlation_id=f"provider-role-{role}",
        )

    assert context["roles"] == ["WORKSPACE_MEMBER"]
    result = evaluate_core_policy(context)
    assert result.effect is PolicyEffect.DENY
    assert result.reason_codes == ("ROLE_NOT_ALLOWED",)


@override_settings(
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha"}),
    CURVE_ENVIRONMENT="LOCAL",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api-test",
)
def test_provider_role_is_action_scoped_and_caller_authority_is_ignored():
    user = _user("action-scope@example.com")
    workspace = _workspace("Alpha", "alpha", user, role=20)

    membership, roles = policy_services._workspace_membership(
        workspace_id=workspace.id,
        user=user,
        action="CURVE.FOUNDATION_PROBE.START",
    )
    query_context = policy_services._build_query_context(
        workspace=workspace,
        user=user,
        action="CURVE.FOUNDATION_PROBE.START",
        resource=policy_services._workspace_resource(workspace),
        correlation_id="unrelated-action",
        membership=membership,
        roles=roles,
    )

    assert roles == ["WORKSPACE_MEMBER"]
    assert query_context["policy_manifest_digest"] == CORE_POLICY_MANIFEST_DIGEST
    assert "PLATFORM_ADMINISTRATOR" not in query_context["roles"]
    with pytest.raises(TypeError):
        build_provider_registration_context(
            request=_request(user),
            workspace_slug="alpha",
            correlation_id="caller-forgery",
            roles=["PLATFORM_ADMINISTRATOR"],
            target_id="curve.untrusted@9.9.9",
        )


@override_settings(
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha"}),
    CURVE_ENVIRONMENT="LOCAL",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api-test",
)
def test_inactive_or_wrong_workspace_membership_cannot_register():
    owner = _user("alpha-owner@example.com")
    alpha = _workspace("Alpha", "alpha", owner, role=20)
    inactive = _user("inactive-admin@example.com")
    WorkspaceMember.objects.create(workspace=alpha, member=inactive, role=20, is_active=False)
    beta_admin = _user("beta-admin@example.com")
    _workspace("Beta", "beta", beta_admin, role=20)

    for user in (inactive, beta_admin):
        with transaction.atomic():
            context = build_provider_registration_context(
                request=_request(user),
                workspace_slug="alpha",
                correlation_id=f"membership-{user.id}",
            )
        assert context["membership"] is None
        assert context["roles"] == []
        result = evaluate_core_policy(context)
        assert result.effect is PolicyEffect.DENY
        assert result.reason_codes[0] == "INACTIVE_MEMBERSHIP"


@override_settings(
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha", "beta"}),
    CURVE_ENVIRONMENT="LOCAL",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api-test",
)
def test_administration_context_resolves_only_the_workspace_scoped_connection():
    alpha_admin = _user("alpha-admin@example.com")
    beta_admin = _user("beta-owner@example.com")
    alpha = _workspace("Alpha", "alpha", alpha_admin, role=20)
    beta = _workspace("Beta", "beta", beta_admin, role=20)
    actor = {"actor_type": "HUMAN", "actor_id": str(alpha_admin.id)}
    alpha_connection = _connection(alpha, actor)
    beta_connection = _connection(beta, {"actor_type": "HUMAN", "actor_id": str(beta_admin.id)})

    with transaction.atomic():
        local = build_provider_administration_context(
            request=_request(alpha_admin),
            workspace_slug="alpha",
            connection_id=alpha_connection.id,
            correlation_id="admin-local",
        )
        foreign = build_provider_administration_context(
            request=_request(alpha_admin),
            workspace_slug="alpha",
            connection_id=beta_connection.id,
            correlation_id="admin-foreign",
        )

    assert local["resource"]["exists"] is True
    assert local["resource"]["ref"]["resource_version"] == 1
    assert evaluate_core_policy(local).effect is PolicyEffect.ALLOW
    assert foreign["resource"] == {
        "workspace_id": str(alpha.id),
        "ref": {
            "resource_type": "PROVIDER_CONNECTION",
            "resource_id": str(beta_connection.id),
        },
        "exists": False,
        "owner": None,
    }
    assert evaluate_core_policy(foreign).reason_codes == ("RESOURCE_NOT_FOUND",)


@override_settings(
    CURVE_ENABLED=True,
    CURVE_ENABLED_WORKSPACE_SLUGS=frozenset({"alpha"}),
    CURVE_ENVIRONMENT="LOCAL",
    CURVE_POLICY_RECORDER_ACTOR_ID="curve-api-test",
)
def test_policy_v2_receipt_is_persisted_and_active_only_inside_the_authorized_callback():
    user = _user("receipt-v2@example.com")
    workspace = _workspace("Alpha", "alpha", user, role=20)
    request = _request(user)
    captured = {}

    def context_builder():
        return build_provider_registration_context(
            request=request,
            workspace_slug="alpha",
            correlation_id="provider-v2-receipt",
        )

    def mutation_callback(receipt, _observation):
        resource_ref = {
            "resource_type": "WORKSPACE",
            "resource_id": str(workspace.id),
            "resource_version": 1,
        }
        assert_active_mutation_receipt(
            receipt,
            action="CURVE.PROVIDER_CONNECTION.REGISTER",
            workspace_id=workspace.id,
            resource_ref=resource_ref,
        )
        captured["receipt"] = receipt
        curve_services._append_audit_event(
            workspace_id=workspace.id,
            action="CURVE.PROVIDER_CONNECTION.REGISTER",
            target_ref=resource_ref,
            outcome=AuditOutcome.SUCCEEDED,
            actor={"actor_type": "HUMAN", "actor_id": str(user.id)},
            effective_principal={"actor_type": "HUMAN", "actor_id": str(user.id)},
            correlation_id="provider-v2-receipt",
            policy_decision_ref=policy_decision_ref_for_receipt(receipt),
        )
        return resource_ref

    execute_authorized_mutation(
        context_builder=context_builder,
        mutation_callback=mutation_callback,
    )

    decision = PolicyDecision.objects.get(workspace_id=workspace.id)
    assert decision.policy_version == 2
    assert decision.policy_manifest_digest == CORE_POLICY_V2_MANIFEST_DIGEST
    assert decision.action == "CURVE.PROVIDER_CONNECTION.REGISTER"
    with pytest.raises(PermissionError, match="active Curve mutation"):
        assert_active_mutation_receipt(
            captured["receipt"],
            action="CURVE.PROVIDER_CONNECTION.REGISTER",
            workspace_id=workspace.id,
            resource_ref={
                "resource_type": "WORKSPACE",
                "resource_id": str(workspace.id),
                "resource_version": 1,
            },
        )


def test_mutation_receipt_requires_the_exact_action_policy_binding():
    workspace_id = uuid.uuid4()
    resource_ref = {
        "resource_type": "WORKSPACE",
        "resource_id": str(workspace_id),
        "resource_version": 1,
    }

    def receipt(*, action, version, digest):
        return AuthorizedPolicyReceipt(
            decision_id=uuid.uuid4(),
            action=action,
            workspace_id=workspace_id,
            resource_ref=MappingProxyType(dict(resource_ref)),
            effect=PolicyEffect.ALLOW,
            permitted_projection=("NO_BODY",),
            policy_manifest_digest=digest,
            policy_version=version,
            evaluated_at="2026-08-27T12:00:00Z",
            _constructor_token=policy_services._RECEIPT_CONSTRUCTOR_TOKEN,
        )

    provider_v1 = receipt(
        action="CURVE.PROVIDER_CONNECTION.REGISTER",
        version=1,
        digest=CORE_POLICY_MANIFEST_DIGEST,
    )
    provider_v2 = receipt(
        action="CURVE.PROVIDER_CONNECTION.REGISTER",
        version=2,
        digest=CORE_POLICY_V2_MANIFEST_DIGEST,
    )
    foundation_v2 = receipt(
        action="CURVE.FOUNDATION_PROBE.START",
        version=2,
        digest=CORE_POLICY_V2_MANIFEST_DIGEST,
    )

    with transaction.atomic():
        for rejected in (provider_v1, foundation_v2):
            token = policy_services._ACTIVE_MUTATION_RECEIPT.set(rejected)
            try:
                with pytest.raises(PermissionError, match="active Curve mutation"):
                    assert_active_mutation_receipt(
                        rejected,
                        action=rejected.action,
                        workspace_id=workspace_id,
                        resource_ref=resource_ref,
                    )
            finally:
                policy_services._ACTIVE_MUTATION_RECEIPT.reset(token)

        token = policy_services._ACTIVE_MUTATION_RECEIPT.set(provider_v2)
        try:
            assert_active_mutation_receipt(
                provider_v2,
                action="CURVE.PROVIDER_CONNECTION.REGISTER",
                workspace_id=workspace_id,
                resource_ref=resource_ref,
            )
        finally:
            policy_services._ACTIVE_MUTATION_RECEIPT.reset(token)


def test_provider_context_rejects_invalid_workspace_or_connection_identifiers():
    user = _user("invalid-resource@example.com")
    _workspace("Alpha", "alpha", user, role=20)

    with transaction.atomic():
        with pytest.raises(CurvePolicyResourceNotFound):
            build_provider_registration_context(
                request=_request(user),
                workspace_slug="missing",
                correlation_id="missing-workspace",
            )
        with pytest.raises(CurvePolicyResourceNotFound):
            build_provider_administration_context(
                request=_request(user),
                workspace_slug="alpha",
                connection_id="not-a-uuid",
                correlation_id="invalid-connection",
            )
