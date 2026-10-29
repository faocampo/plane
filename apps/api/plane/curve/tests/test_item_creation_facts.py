# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from uuid import uuid4

import pytest
from django.db import transaction
from django.utils import timezone

from plane.curve.models import Feature
from plane.curve.policy_services import CurvePolicyResourceNotFound
from plane.curve.tests.test_roadmap_commands import (
    scope as roadmap_scope,
    roadmap,
    milestone,
)
from plane.db.models import WorkspaceMember

from plane.curve.item_creation_facts import resolve_item_creation_facts
from plane.curve.item_creation_input import normalize_item_creation
from plane.curve.tests.test_item_creation_input import fixture as payload_fixture

scope = roadmap_scope
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def prepared(scope):
    parent = roadmap(scope)
    child = milestone(scope, parent, 0, "synthetic-item-milestone")
    parent.refresh_from_db()
    actor = {"actor_type": "HUMAN", "actor_id": str(scope.owner.id)}
    feature = Feature.objects.create(
        workspace_id=scope.workspace.id,
        product_id=scope.product.id,
        name="Synthetic capability",
        created_by=actor,
        updated_by=actor,
    )
    payload = payload_fixture()
    payload.update(feature_id=str(feature.id), milestone_id=str(child.id))
    payload["initiative"]["gate_assignments"] = [
        {"gate_type": "PRD_APPROVAL", "approver_user_id": str(scope.member.id)},
        {"gate_type": "PLAN_APPROVAL", "approver_user_id": str(scope.admin.id)},
    ]
    return parent, child, feature, payload


def resolve(scope, prepared, user=None, **overrides):
    parent, _, _, payload = prepared
    arguments = dict(
        workspace_slug=scope.workspace.slug,
        product_id=scope.product.id,
        roadmap_id=parent.id,
        actor_id=(user or scope.owner).id,
        command=normalize_item_creation(payload, parent.version),
    )
    arguments.update(overrides)
    return resolve_item_creation_facts(**arguments)


def test_current_native_scope_and_reviewers_are_observed(scope, prepared):
    with transaction.atomic():
        facts = resolve(scope, prepared)
        assert facts.actor.active_human and facts.actor.active_member
        assert facts.roadmap_owner_id == scope.owner.id
        assert facts.roadmap_version == prepared[0].version
        assert facts.product_active and facts.formats_supported and facts.records_active
        assert facts.actor_membership_generation is not None
        assert {gate for gate, _ in facts.reviewers} == {
            "PRD_APPROVAL",
            "PLAN_APPROVAL",
        }
        assert all(person.active_human and person.active_member for _, person in facts.reviewers)


def test_transaction_is_required(scope, prepared):
    with pytest.raises(RuntimeError, match="TRANSACTION_REQUIRED"):
        resolve(scope, prepared)


def test_admin_observation_preserves_distinct_roadmap_owner(scope, prepared):
    with transaction.atomic():
        facts = resolve(scope, prepared, user=scope.admin)
        assert facts.actor.active_member
        assert facts.actor.user_id != facts.roadmap_owner_id
        assert facts.roadmap_owner_id == scope.owner.id


def test_reviewer_membership_loss_is_observed_again(scope, prepared):
    WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.member).update(is_active=False)
    with transaction.atomic():
        facts = resolve(scope, prepared)
        product_reviewer = dict(facts.reviewers)["PRD_APPROVAL"]
        assert product_reviewer.active_human
        assert not product_reviewer.active_member


@pytest.mark.parametrize("field", ["is_active", "is_bot"])
def test_reviewer_human_liveness_is_independent(scope, prepared, field):
    setattr(scope.member, field, field == "is_bot")
    scope.member.save(update_fields=[field])
    with transaction.atomic():
        reviewer = dict(resolve(scope, prepared).reviewers)["PRD_APPROVAL"]
        assert not reviewer.active_human
        assert reviewer.active_member


def test_actor_restoration_has_new_membership_lifetime(scope, prepared):
    with transaction.atomic():
        before = resolve(scope, prepared)
    membership = WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.owner)
    membership.update(is_active=False)
    with transaction.atomic():
        removed = resolve(scope, prepared)
        assert not removed.actor.active_member
        assert removed.actor_membership_generation is None
    membership.update(is_active=True)
    with transaction.atomic():
        restored = resolve(scope, prepared)
        assert restored.actor.active_member
        assert restored.actor_membership_generation > before.actor_membership_generation


@pytest.mark.parametrize("field", ["product_id", "roadmap_id"])
def test_unknown_scoped_resource_is_unavailable(scope, prepared, field):
    with transaction.atomic(), pytest.raises(CurvePolicyResourceNotFound):
        resolve(scope, prepared, **{field: uuid4()})


def test_milestone_from_another_roadmap_is_unavailable(scope, prepared):
    other = roadmap(scope, key="synthetic-other-roadmap")
    child = milestone(scope, other, 0, "synthetic-other-milestone")
    prepared[3]["milestone_id"] = str(child.id)
    with transaction.atomic(), pytest.raises(CurvePolicyResourceNotFound):
        resolve(scope, prepared)


def test_retired_feature_and_disabled_workspace_remain_separate_facts(scope, prepared, settings):
    actor = {"actor_type": "HUMAN", "actor_id": str(scope.owner.id)}
    retired = Feature.objects.create(
        workspace_id=scope.workspace.id,
        product_id=scope.product.id,
        name="Retired synthetic capability",
        created_by=actor,
        updated_by=actor,
        tombstoned_at=timezone.now(),
        tombstoned_by=actor,
        tombstone_reason="Synthetic retirement",
    )
    prepared[3]["feature_id"] = str(retired.id)
    settings.CURVE_ENABLED = False
    with transaction.atomic():
        facts = resolve(scope, prepared)
        assert facts.feature_id == retired.id
        assert not facts.records_active
        assert not facts.feature_enabled
        assert facts.actor.active_member
