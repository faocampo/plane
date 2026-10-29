# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
from uuid import uuid4

import pytest
from django.db import transaction
from django.utils import timezone

from plane.curve.models import Initiative, RoadmapItem
from plane.curve.prd_commands import PrdCommandError
from plane.curve.tests.test_item_creation_commands import (
    scope as native_scope,
    prepared as native_prepared,
    material as native_material,
    command,
)
from plane.db.models import User, WorkspaceMember

from plane.curve.roadmap_local_context import require_roadmap_local_context as require_context

scope, prepared, material = native_scope, native_prepared, native_material
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def created(scope, prepared, material):
    result = command(scope, prepared, material)
    return Initiative.objects.get(id=result.resource_ref["initiative_ref"]["resource_id"])


def context(scope, created, actor=None, **overrides):
    return require_context(
        **(
            dict(
                workspace_id=scope.workspace.id,
                initiative_id=created.id,
                actor_id=(actor or scope.owner).id,
            )
            | overrides
        )
    )


@pytest.mark.parametrize("actor", ["owner", "member", "admin"])
def test_real_created_pair_exposes_exact_scope_and_two_current_reviewers(scope, created, material, actor):
    with transaction.atomic():
        observed = context(scope, created, getattr(scope, actor))
        assert observed.roadmap_item.id == created.roadmap_item_id
        assert observed.roadmap_item.defining_initiative_id == created.id
        assert observed.roadmap_item.scope_body == material.reference
        assert {row["gate_type"] for row in observed.reviewers} == {
            "PRD_APPROVAL",
            "PLAN_APPROVAL",
        }
        assert observed.head is None and observed.revision is None


def test_transaction_required(scope, created):
    with pytest.raises(PrdCommandError):
        context(scope, created)


@pytest.mark.parametrize("field", ["workspace_id", "initiative_id", "actor_id"])
def test_foreign_coordinates_are_unavailable(scope, created, field):
    with pytest.raises(PrdCommandError), transaction.atomic():
        context(scope, created, **{field: uuid4()})


@pytest.mark.parametrize("participant", ["owner", "member", "admin"])
def test_any_participant_membership_loss_blocks_document_context(scope, created, participant):
    WorkspaceMember.objects.filter(workspace=scope.workspace, member=getattr(scope, participant)).update(
        is_active=False
    )
    with pytest.raises(PrdCommandError), transaction.atomic():
        context(scope, created)


@pytest.mark.parametrize("field,value", [("is_active", False), ("is_bot", True)])
def test_reviewer_must_remain_an_active_human(scope, created, field, value):
    User.objects.filter(id=scope.member.id).update(**{field: value})
    with pytest.raises(PrdCommandError), transaction.atomic():
        context(scope, created)


def test_unassigned_workspace_member_cannot_read_review_context(scope, created):
    person = User.objects.create(email="unassigned@example.invalid", username="unassigned@example.invalid")
    WorkspaceMember.objects.create(workspace=scope.workspace, member=person, role=15, is_active=True)
    with pytest.raises(PrdCommandError), transaction.atomic():
        context(scope, created, person)


def test_membership_restoration_changes_the_authority_fence(scope, created):
    with transaction.atomic():
        original = context(scope, created).fence
    membership = WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.member)
    membership.update(is_active=False)
    membership.update(is_active=True)
    with transaction.atomic():
        restored = context(scope, created).fence
    assert restored != original


@pytest.mark.parametrize("resource", ["item", "roadmap", "feature", "milestone"])
def test_retired_linked_resources_block_review_context(scope, created, prepared, resource):
    item = RoadmapItem.objects.get(id=created.roadmap_item_id)
    row = {
        "item": item,
        "roadmap": prepared[0],
        "milestone": prepared[1],
        "feature": prepared[2],
    }[resource]
    row.tombstoned_at = timezone.now()
    row.tombstoned_by = {"actor_type": "HUMAN", "actor_id": str(scope.owner.id)}
    row.tombstone_reason = "Synthetic retirement"
    row.version += 1
    row.save()
    with pytest.raises(PrdCommandError), transaction.atomic():
        context(scope, created)
