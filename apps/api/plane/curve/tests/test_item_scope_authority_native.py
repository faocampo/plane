# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Native authority/storage integration; command/HTTP qualification remains separate."""

from types import MappingProxyType
from uuid import uuid4

import pytest
from django.db import transaction

from plane.curve.item_creation_material import ItemScopeRequirement
from plane.curve.item_local_material import ItemMaterialUnavailable, LocalItemMaterialResolver
from plane.curve.item_scope_authority import resolve_item_scope_facts, scope_preparation_reason
from plane.curve.item_scope_preparation import prepare_scope_document
from plane.curve.models import Roadmap
from plane.curve.policy_services import CurvePolicyResourceNotFound
from plane.curve.tests.test_roadmap_commands import scope as roadmap_scope
from plane.curve.tests.test_item_scope_preparation import material as scope_material
from plane.db.models import WorkspaceMember

scope = roadmap_scope
material = scope_material
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def parent(scope):
    actor = {"actor_type": "HUMAN", "actor_id": str(scope.member.id)}
    # Native fixture only: deliberately distinct Product and Roadmap owners.
    return Roadmap.objects.create(
        workspace_id=scope.workspace.id,
        product_id=scope.product.id,
        name="Synthetic scope authority roadmap",
        owner_user_id=scope.member.id,
        created_by=actor,
        updated_by=actor,
    )


def resolve(scope, parent, user=None, **changes):
    arguments = dict(
        workspace_slug=scope.workspace.slug,
        product_id=scope.product.id,
        roadmap_id=parent.id,
        actor_id=(user or scope.member).id,
    )
    arguments.update(changes)
    return resolve_item_scope_facts(**arguments)


def capture(resolver, facts, reference):
    context = facts.storage_context()
    return resolver.capture(
        workspace_id=context.workspace_id,
        product_id=context.product_id,
        roadmap_id=context.roadmap_id,
        actor_id=context.actor_id,
        membership_id=context.membership_id,
        membership_generation=context.membership_generation,
        requirements=(ItemScopeRequirement(MappingProxyType(dict(reference))),),
    )


def test_native_current_roadmap_owner_is_distinct_from_product_owner(scope, parent):
    with transaction.atomic():
        facts = resolve(scope, parent)
        assert scope_preparation_reason(facts) == "ALLOW"
        assert facts.product.owner_id == scope.owner.id
        assert facts.roadmap_owner_id == scope.member.id
        assert facts.storage_context().membership_generation == 0
        assert facts.roadmap_version == parent.version


@pytest.mark.parametrize("actor", ["owner", "admin"])
def test_native_product_owner_and_admin_cannot_prepare_for_other_owner(scope, parent, actor):
    with transaction.atomic():
        facts = resolve(scope, parent, getattr(scope, actor))
        assert scope_preparation_reason(facts) == "ROADMAP_OWNER_REQUIRED"
        with pytest.raises(PermissionError):
            facts.storage_context()


def test_authority_requires_enclosing_transaction(scope, parent):
    with pytest.raises(RuntimeError, match="TRANSACTION_REQUIRED"):
        resolve(scope, parent)


@pytest.mark.parametrize("field", ["product_id", "roadmap_id", "workspace_slug"])
def test_foreign_scope_cannot_resolve_parent(scope, parent, field):
    value = "missing-synthetic-workspace" if field == "workspace_slug" else uuid4()
    with transaction.atomic(), pytest.raises(CurvePolicyResourceNotFound):
        resolve(scope, parent, **{field: value})


@pytest.mark.parametrize("field", ["is_active", "is_bot"])
def test_native_human_liveness_is_rechecked(scope, parent, field):
    setattr(scope.member, field, field == "is_bot")
    scope.member.save(update_fields=[field])
    with transaction.atomic():
        facts = resolve(scope, parent)
        assert scope_preparation_reason(facts) == "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"


def test_disabled_workspace_denies_preparation(scope, parent, settings):
    settings.CURVE_ENABLED = False
    with transaction.atomic():
        assert scope_preparation_reason(resolve(scope, parent)) == "FEATURE_DISABLED"


def test_restored_membership_cannot_read_original_prepared_scope(scope, parent, material):
    with transaction.atomic(), LocalItemMaterialResolver(str(material)) as resolver:
        before = resolve(scope, parent)
        reference = prepare_scope_document(resolver, context=before.storage_context(), payload={"body": "Original"})
        with resolver.lease():
            resolver.revalidate(capture(resolver, before, reference))
    membership = WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.member)
    membership.update(is_active=False)
    with transaction.atomic():
        removed = resolve(scope, parent)
        assert scope_preparation_reason(removed) == "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"
        with pytest.raises(PermissionError):
            removed.storage_context()
    membership.update(is_active=True)
    with transaction.atomic(), LocalItemMaterialResolver(str(material)) as resolver:
        restored = resolve(scope, parent)
        assert restored.product.membership_generation > before.product.membership_generation
        with resolver.lease(), pytest.raises(ItemMaterialUnavailable):
            capture(resolver, restored, reference)
        fresh = prepare_scope_document(resolver, context=restored.storage_context(), payload={"body": "Fresh"})
        assert fresh["object_id"] != reference["object_id"]
        with resolver.lease():
            resolver.revalidate(capture(resolver, restored, fresh))
            with pytest.raises(ItemMaterialUnavailable):
                capture(resolver, restored, reference)
