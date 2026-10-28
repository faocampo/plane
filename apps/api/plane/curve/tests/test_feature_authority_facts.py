# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from uuid import uuid4
from types import SimpleNamespace

import pytest
from django.db import transaction

from plane.curve.feature_authority_facts import resolve_feature_facts
from plane.curve.feature_editor_rules import feature_editor_reason
from plane.curve.product_services import reassign_product_owner
from plane.curve.models import Product
from plane.curve.policy_services import CurvePolicyResourceNotFound
from plane.curve.tests.test_feature_editor_commands import command
from plane.curve.tests.test_roadmap_commands import scope as roadmap_scope
from plane.db.models import WorkspaceMember, Workspace

scope = roadmap_scope
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def reason(scope, user):
    with transaction.atomic():
        facts = resolve_feature_facts(
            workspace_slug=scope.workspace.slug,
            product_id=scope.product.id,
            actor_id=user.id,
        )
        return feature_editor_reason("CREATE_FEATURE", facts)


def test_owner_and_administrator_editing_are_distinct(scope):
    assert reason(scope, scope.owner) == "ALLOW"
    assert reason(scope, scope.admin) == "PRODUCT_OWNER_OR_FEATURE_EDITOR_REQUIRED"
    command(scope, target=scope.admin)
    assert reason(scope, scope.admin) == "ALLOW"


def test_grant_revoke_rechecks_native_records(scope):
    assert reason(scope, scope.member) == "PRODUCT_OWNER_OR_FEATURE_EDITOR_REQUIRED"
    granted = command(scope)
    assert reason(scope, scope.member) == "ALLOW"
    command(
        scope,
        grant_id=granted.resource_ref["resource_id"],
        version=1,
        key="synthetic-revoke",
    )
    assert reason(scope, scope.member) == "PRODUCT_OWNER_OR_FEATURE_EDITOR_REQUIRED"


def test_membership_restoration_requires_new_generation_grant(scope):
    command(scope)
    membership = WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.member)
    membership.update(is_active=False)
    assert reason(scope, scope.member) == "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"
    membership.update(is_active=True)
    assert reason(scope, scope.member) == "PRODUCT_OWNER_OR_FEATURE_EDITOR_REQUIRED"
    command(scope, key="synthetic-restored-grant")
    assert reason(scope, scope.member) == "ALLOW"


def test_current_product_owner_controls_implicit_authority(scope):
    reassign_product_owner(
        request=SimpleNamespace(user=scope.admin, headers={}),
        workspace_slug=scope.workspace.slug,
        product_id=scope.product.id,
        expected_version=scope.product.version,
        payload={"owner_user_id": str(scope.member.id)},
        raw_idempotency_key="synthetic-owner-change",
    )
    assert reason(scope, scope.owner) == "PRODUCT_OWNER_OR_FEATURE_EDITOR_REQUIRED"
    assert reason(scope, scope.member) == "ALLOW"


def test_unknown_product_is_unavailable(scope):
    with transaction.atomic(), pytest.raises(CurvePolicyResourceNotFound):
        resolve_feature_facts(
            workspace_slug=scope.workspace.slug,
            product_id=uuid4(),
            actor_id=scope.owner.id,
        )


def test_requires_caller_owned_transaction(scope):
    with pytest.raises(RuntimeError, match="TRANSACTION_REQUIRED"):
        resolve_feature_facts(
            workspace_slug=scope.workspace.slug,
            product_id=scope.product.id,
            actor_id=scope.owner.id,
        )


def test_disabled_workspace_and_inactive_human_are_rechecked(scope, settings):
    settings.CURVE_ENABLED = False
    assert reason(scope, scope.owner) == "FEATURE_DISABLED"
    settings.CURVE_ENABLED = True
    scope.owner.is_active = False
    scope.owner.save(update_fields=["is_active"])
    assert reason(scope, scope.owner) == "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"


def test_product_from_another_workspace_is_unavailable(scope):
    other_workspace = Workspace.objects.create(name="Synthetic other workspace", slug="other", owner=scope.admin)
    actor = {"actor_type": "HUMAN", "actor_id": str(scope.admin.id)}
    other = Product.objects.create(
        workspace_id=other_workspace.id,
        key="other",
        name="Synthetic other Product",
        timezone="UTC",
        owner_user_id=scope.admin.id,
        created_by=actor,
        updated_by=actor,
    )
    with transaction.atomic(), pytest.raises(CurvePolicyResourceNotFound):
        resolve_feature_facts(
            workspace_slug=scope.workspace.slug,
            product_id=other.id,
            actor_id=scope.owner.id,
        )


def test_editor_grant_does_not_cross_products(scope):
    command(scope)
    actor = {"actor_type": "HUMAN", "actor_id": str(scope.admin.id)}
    other = Product.objects.create(
        workspace_id=scope.workspace.id,
        key="other",
        name="Synthetic other Product",
        timezone="UTC",
        owner_user_id=scope.admin.id,
        created_by=actor,
        updated_by=actor,
    )
    with transaction.atomic():
        facts = resolve_feature_facts(
            workspace_slug=scope.workspace.slug,
            product_id=other.id,
            actor_id=scope.member.id,
        )
        assert feature_editor_reason("UPDATE_FEATURE", facts) == "PRODUCT_OWNER_OR_FEATURE_EDITOR_REQUIRED"
