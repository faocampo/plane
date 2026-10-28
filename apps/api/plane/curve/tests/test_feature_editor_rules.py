# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Decision-rule tests; transaction, storage and API qualification are separate."""

from dataclasses import replace
from uuid import UUID

import pytest

from plane.curve.feature_editor_rules import FeatureEditorAction, FeatureEditorFacts, feature_editor_reason


WORKSPACE, PRODUCT, ACTOR, OWNER, MEMBERSHIP, OTHER = (UUID(int=n) for n in range(1, 7))
BASE = FeatureEditorFacts(
    workspace_id=WORKSPACE,
    product_id=PRODUCT,
    actor_id=ACTOR,
    owner_id=OWNER,
    actor_active_human=True,
    actor_active_member=True,
    actor_administrator=False,
    product_active=True,
    product_format_supported=True,
    feature_enabled=True,
    membership_id=MEMBERSHIP,
    membership_generation=0,
)
GRANTED = replace(
    BASE,
    grant_workspace_id=WORKSPACE,
    grant_product_id=PRODUCT,
    grant_member_id=ACTOR,
    grant_membership_id=MEMBERSHIP,
    grant_membership_generation=0,
    grant_active=True,
)


@pytest.mark.parametrize("action", list(FeatureEditorAction))
def test_current_product_owner_can_manage_and_edit(action):
    assert feature_editor_reason(action, replace(BASE, owner_id=ACTOR)) == "ALLOW"


@pytest.mark.parametrize("action", [FeatureEditorAction.GRANT, FeatureEditorAction.REVOKE])
def test_administrator_manages_editors_but_editor_grant_does_not_manage_access(action):
    assert feature_editor_reason(action, replace(BASE, actor_administrator=True)) == "ALLOW"
    assert feature_editor_reason(action, GRANTED) == "PRODUCT_OWNER_OR_ADMINISTRATOR_REQUIRED"


@pytest.mark.parametrize("action", [FeatureEditorAction.CREATE_FEATURE, FeatureEditorAction.UPDATE_FEATURE])
def test_feature_editing_requires_ownership_or_current_grant_even_for_administrator(action):
    assert feature_editor_reason(action, BASE) == "PRODUCT_OWNER_OR_FEATURE_EDITOR_REQUIRED"
    assert (
        feature_editor_reason(action, replace(BASE, actor_administrator=True))
        == "PRODUCT_OWNER_OR_FEATURE_EDITOR_REQUIRED"
    )
    assert feature_editor_reason(action, GRANTED) == "ALLOW"
    assert feature_editor_reason(action, replace(GRANTED, actor_administrator=True)) == "ALLOW"


@pytest.mark.parametrize(
    "change",
    [
        {"grant_workspace_id": OTHER},
        {"grant_product_id": OTHER},
        {"grant_member_id": OTHER},
        {"grant_membership_id": OTHER},
        {"membership_id": None},
        {"grant_active": False},
        {"membership_generation": 1},
        {"membership_generation": None},
        {"membership_generation": -1, "grant_membership_generation": -1},
        {"membership_generation": True, "grant_membership_generation": True},
    ],
)
def test_foreign_revoked_or_earlier_membership_grants_fail_closed(change):
    assert (
        feature_editor_reason(FeatureEditorAction.UPDATE_FEATURE, replace(GRANTED, **change))
        == "PRODUCT_OWNER_OR_FEATURE_EDITOR_REQUIRED"
    )


def test_restored_membership_requires_new_grant_generation():
    removed = replace(GRANTED, actor_active_member=False, membership_generation=1)
    assert feature_editor_reason(FeatureEditorAction.UPDATE_FEATURE, removed) == "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"
    restored = replace(removed, actor_active_member=True)
    assert (
        feature_editor_reason(FeatureEditorAction.UPDATE_FEATURE, restored)
        == "PRODUCT_OWNER_OR_FEATURE_EDITOR_REQUIRED"
    )
    fresh = replace(restored, grant_membership_generation=1)
    assert feature_editor_reason(FeatureEditorAction.UPDATE_FEATURE, fresh) == "ALLOW"


@pytest.mark.parametrize("action", list(FeatureEditorAction))
@pytest.mark.parametrize(
    "change, reason",
    [
        ({"feature_enabled": False}, "FEATURE_DISABLED"),
        ({"actor_active_human": False}, "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"),
        ({"actor_active_member": False}, "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"),
        ({"product_active": False}, "PRODUCT_UNAVAILABLE"),
        ({"product_format_supported": False}, "PRODUCT_FORMAT_UNAVAILABLE"),
    ],
)
def test_current_scope_denial_precedes_owner_admin_or_grant(action, change, reason):
    facts = replace(GRANTED, owner_id=ACTOR, actor_administrator=True, **change)
    assert feature_editor_reason(action, facts) == reason


def test_unknown_action_and_former_owner_have_no_implicit_authority():
    assert feature_editor_reason("CHANGE_REVIEWER", GRANTED) == "UNKNOWN_ACTION"
    assert feature_editor_reason(FeatureEditorAction.UPDATE_FEATURE, BASE) == "PRODUCT_OWNER_OR_FEATURE_EDITOR_REQUIRED"
