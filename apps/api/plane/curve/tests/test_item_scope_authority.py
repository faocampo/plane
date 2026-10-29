# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from dataclasses import replace
from uuid import UUID

import pytest

from plane.curve.feature_editor_rules import FeatureEditorFacts
from plane.curve.item_scope_authority import ItemScopeFacts, scope_preparation_reason


IDS = [UUID(f"97000000-0000-4000-8000-{n:012d}") for n in range(1, 7)]


def facts():
    return ItemScopeFacts(
        product=FeatureEditorFacts(
            workspace_id=IDS[0],
            product_id=IDS[1],
            actor_id=IDS[2],
            owner_id=IDS[3],
            actor_active_human=True,
            actor_active_member=True,
            actor_administrator=False,
            product_active=True,
            product_format_supported=True,
            feature_enabled=True,
            membership_id=IDS[4],
            membership_generation=0,
        ),
        roadmap_id=IDS[5],
        roadmap_owner_id=IDS[2],
        roadmap_version=1,
        roadmap_active=True,
        roadmap_format_supported=True,
    )


def test_current_roadmap_owner_can_prepare_without_product_ownership_or_editor_grant():
    value = facts()
    assert scope_preparation_reason(value) == "ALLOW"
    context = value.storage_context()
    assert context.actor_id == str(IDS[2])
    assert context.membership_generation == 0
    assert context.roadmap_id == str(IDS[5])


@pytest.mark.parametrize(
    "field,changed,reason",
    [
        ("actor_active_human", False, "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"),
        ("actor_active_member", False, "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"),
        ("feature_enabled", False, "FEATURE_DISABLED"),
        ("product_active", False, "PRODUCT_UNAVAILABLE"),
        ("product_format_supported", False, "FORMAT_UNAVAILABLE"),
        ("membership_id", None, "CURRENT_MEMBERSHIP_LIFETIME_REQUIRED"),
        ("membership_generation", -1, "CURRENT_MEMBERSHIP_LIFETIME_REQUIRED"),
        ("membership_generation", True, "CURRENT_MEMBERSHIP_LIFETIME_REQUIRED"),
        ("membership_generation", None, "CURRENT_MEMBERSHIP_LIFETIME_REQUIRED"),
    ],
)
def test_current_native_facts_required(field, changed, reason):
    value = facts()
    value = replace(value, product=replace(value.product, **{field: changed}))
    assert scope_preparation_reason(value) == reason
    with pytest.raises(PermissionError):
        value.storage_context()


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"roadmap_owner_id": IDS[3]}, "ROADMAP_OWNER_REQUIRED"),
        ({"roadmap_active": False}, "RESOURCE_UNAVAILABLE"),
        ({"roadmap_format_supported": False}, "FORMAT_UNAVAILABLE"),
    ],
)
def test_roadmap_state_is_independently_required(change, reason):
    value = replace(facts(), **change)
    assert scope_preparation_reason(value) == reason
    with pytest.raises(PermissionError):
        value.storage_context()


@pytest.mark.parametrize("extra", [{"actor_administrator": True}, {"owner_id": IDS[2]}, {"grant_active": True}])
def test_administrator_product_owner_or_editor_alone_cannot_prepare(extra):
    value = facts()
    value = replace(value, roadmap_owner_id=IDS[3], product=replace(value.product, **extra))
    assert scope_preparation_reason(value) == "ROADMAP_OWNER_REQUIRED"


def test_untyped_facts_are_rejected():
    with pytest.raises(TypeError):
        scope_preparation_reason({"actor_id": str(IDS[2])})
