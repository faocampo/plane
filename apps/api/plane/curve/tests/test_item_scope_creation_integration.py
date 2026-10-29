# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
from types import SimpleNamespace

import pytest

from plane.curve.item_creation_services import execute_item_creation
from plane.curve.item_scope_services import execute_item_scope_preparation
from plane.curve.models import GateAssignment, Initiative, RoadmapItem
from plane.curve.tests.test_item_creation_facts import scope as native_scope, prepared as native_prepared
from plane.curve.tests.test_item_scope_preparation import material as native_material

scope, prepared, material = native_scope, native_prepared, native_material
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def test_prepared_scope_creates_reciprocal_item_initiative_with_exactly_two_review_stages(
    scope, prepared, material, settings
):
    settings.CURVE_ITEM_SCOPE_PREPARATION_ENABLED = True
    settings.CURVE_LOCAL_ITEM_MATERIAL_ENABLED = True
    settings.CURVE_LOCAL_ITEM_MATERIAL_ROOT = str(material)
    parent, _, _, original = prepared
    request = SimpleNamespace(user=scope.owner, headers={})
    coordinates = dict(
        request=request,
        workspace_slug=scope.workspace.slug,
        product_id=scope.product.id,
        roadmap_id=parent.id,
        expected_version=parent.version,
    )
    document = execute_item_scope_preparation(
        **coordinates,
        payload={"body": "Synthetic delivery scope"},
        raw_idempotency_key="synthetic-prepare-before-create",
    )
    payload = deepcopy(original)
    payload["scope_body"] = document.resource_ref["scope_body"]
    created = execute_item_creation(
        **coordinates, payload=payload, raw_idempotency_key="synthetic-create-after-prepare"
    )
    item = RoadmapItem.objects.get(id=created.resource_ref["resource_id"])
    initiative = Initiative.objects.get(id=created.resource_ref["initiative_ref"]["resource_id"])
    assert item.defining_initiative_id == initiative.id and initiative.roadmap_item_id == item.id
    assert item.scope_body == document.resource_ref["scope_body"]
    assert initiative.state == "DRAFT" and item.status == "PROPOSED"
    assert item.approved_prd_version_id is None and item.declared_progress == 0
    assert set(GateAssignment.objects.filter(initiative=initiative).values_list("gate_type", "approver_user_id")) == {
        ("PRD_APPROVAL", scope.member.id),
        ("PLAN_APPROVAL", scope.admin.id),
    }
    replayed_document = execute_item_scope_preparation(
        **coordinates,
        payload={"body": "Synthetic delivery scope"},
        raw_idempotency_key="synthetic-prepare-before-create",
    )
    replayed_item = execute_item_creation(
        **coordinates, payload=payload, raw_idempotency_key="synthetic-create-after-prepare"
    )
    assert replayed_document.replayed and replayed_item.replayed
    assert replayed_document.resource_ref == document.resource_ref
    assert replayed_item.resource_ref == created.resource_ref
    assert Initiative.objects.count() == RoadmapItem.objects.count() == 1
    parent.refresh_from_db()
    assert parent.version == coordinates["expected_version"]
