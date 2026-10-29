# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from dataclasses import replace
from uuid import UUID

import pytest

from plane.curve.item_creation_facts import HumanMembershipFact, ItemCreationFacts
from plane.curve.item_creation_input import normalize_item_creation
from plane.curve.item_creation_rules import item_creation_authority_reason
from plane.curve.tests.test_item_creation_input import fixture


def valid():
    payload = fixture()
    command = normalize_item_creation(payload, 1)
    actor_id = UUID("93000000-0000-4000-8000-000000000010")
    facts = ItemCreationFacts(
        workspace_id=UUID("93000000-0000-4000-8000-000000000011"),
        product_id=UUID("93000000-0000-4000-8000-000000000012"),
        roadmap_id=UUID("93000000-0000-4000-8000-000000000013"),
        milestone_id=UUID(payload["milestone_id"]),
        feature_id=UUID(payload["feature_id"]),
        roadmap_owner_id=actor_id,
        roadmap_version=1,
        feature_enabled=True,
        product_active=True,
        formats_supported=True,
        records_active=True,
        actor=HumanMembershipFact(actor_id, True, True, actor_id),
        actor_membership_generation=1,
        reviewers=tuple(
            (
                entry["gate_type"],
                HumanMembershipFact(
                    UUID(entry["approver_user_id"]),
                    True,
                    True,
                    UUID(entry["approver_user_id"]),
                ),
            )
            for entry in payload["initiative"]["gate_assignments"]
        ),
    )
    return command, facts


def test_current_owner_and_exact_live_reviewers_are_required():
    command, facts = valid()
    assert item_creation_authority_reason(command, facts) == "ALLOW"
    assert (
        item_creation_authority_reason(command, replace(facts, roadmap_owner_id=facts.product_id))
        == "ROADMAP_OWNER_REQUIRED"
    )


@pytest.mark.parametrize(
    "field,expected",
    [
        ("feature_enabled", "FEATURE_DISABLED"),
        ("product_active", "PRODUCT_UNAVAILABLE"),
        ("formats_supported", "FORMAT_UNAVAILABLE"),
        ("records_active", "RESOURCE_UNAVAILABLE"),
    ],
)
def test_current_resource_conditions_fail_closed(field, expected):
    command, facts = valid()
    assert item_creation_authority_reason(command, replace(facts, **{field: False})) == expected


@pytest.mark.parametrize("field", ["active_human", "active_member"])
def test_actor_and_reviewers_each_require_current_liveness(field):
    command, facts = valid()
    assert (
        item_creation_authority_reason(command, replace(facts, actor=replace(facts.actor, **{field: False})))
        == "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"
    )
    gate, reviewer = facts.reviewers[0]
    changed = ((gate, replace(reviewer, **{field: False})), facts.reviewers[1])
    assert (
        item_creation_authority_reason(command, replace(facts, reviewers=changed)) == "ACTIVE_HUMAN_REVIEWERS_REQUIRED"
    )


@pytest.mark.parametrize("generation", [None, True, -1, "1"])
def test_missing_or_invalid_membership_lifetime_cannot_authorize(generation):
    command, facts = valid()
    assert (
        item_creation_authority_reason(command, replace(facts, actor_membership_generation=generation))
        == "CURRENT_MEMBERSHIP_LIFETIME_REQUIRED"
    )


def test_facts_for_different_material_relationships_cannot_authorize():
    command, facts = valid()
    for field in ("feature_id", "milestone_id"):
        assert (
            item_creation_authority_reason(command, replace(facts, **{field: facts.product_id}))
            == "RESOURCE_UNAVAILABLE"
        )


def test_reviewers_must_match_the_exact_normalized_assignment_pair():
    command, facts = valid()
    gate, person = facts.reviewers[0]
    for reviewers in (
        (),
        (facts.reviewers[0],) * 2,
        ((gate, replace(person, user_id=facts.actor.user_id)), facts.reviewers[1]),
    ):
        assert (
            item_creation_authority_reason(command, replace(facts, reviewers=reviewers)) == "CURRENT_REVIEWERS_REQUIRED"
        )


def test_authorization_precedes_new_command_version_conflict():
    command, facts = valid()
    assert item_creation_authority_reason(command, replace(facts, roadmap_version=2)) == "ALLOW"
    assert (
        item_creation_authority_reason(
            command,
            replace(
                facts,
                roadmap_version=2,
                actor=replace(facts.actor, active_member=False),
            ),
        )
        == "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"
    )


def test_initial_zero_membership_lifetime_is_current():
    command, facts = valid()
    assert item_creation_authority_reason(command, replace(facts, actor_membership_generation=0)) == "ALLOW"
