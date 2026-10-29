# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Authority decision preparation; native facts and a real policy receipt remain required."""

from plane.curve.item_creation_facts import ItemCreationFacts
from plane.curve.item_creation_input import NormalizedItemCreation, normalize_item_creation


def item_creation_authority_reason(command, facts):
    if not isinstance(command, NormalizedItemCreation) or not isinstance(facts, ItemCreationFacts):
        raise TypeError("NORMALIZED_COMMAND_AND_NATIVE_FACTS_REQUIRED")
    payload = normalize_item_creation(command.as_payload(), command.expected_version).as_payload()
    if not facts.feature_enabled:
        return "FEATURE_DISABLED"
    if not facts.actor.active_human or not facts.actor.active_member:
        return "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"
    if not facts.product_active:
        return "PRODUCT_UNAVAILABLE"
    if not facts.formats_supported:
        return "FORMAT_UNAVAILABLE"
    if not facts.records_active:
        return "RESOURCE_UNAVAILABLE"
    if facts.actor.user_id != facts.roadmap_owner_id:
        return "ROADMAP_OWNER_REQUIRED"
    if type(facts.actor_membership_generation) is not int or facts.actor_membership_generation < 0:
        return "CURRENT_MEMBERSHIP_LIFETIME_REQUIRED"
    if str(facts.feature_id) != payload["feature_id"] or str(facts.milestone_id) != payload["milestone_id"]:
        return "RESOURCE_UNAVAILABLE"
    expected = {entry["gate_type"]: entry["approver_user_id"] for entry in payload["initiative"]["gate_assignments"]}
    actual = {gate: str(person.user_id) for gate, person in facts.reviewers}
    if len(facts.reviewers) != 2 or actual != expected:
        return "CURRENT_REVIEWERS_REQUIRED"
    if any(not person.active_human or not person.active_member for _, person in facts.reviewers):
        return "ACTIVE_HUMAN_REVIEWERS_REQUIRED"
    # A successful retained command may already have advanced related state.
    # Fresh authorization precedes receipt replay; version conflicts belong to
    # the new-command path after retained-result resolution.
    return "ALLOW"
