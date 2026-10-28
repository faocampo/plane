# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Feature editor decision rules over freshly resolved, locked server facts.

This module produces reason codes, never an authorization receipt. The command
adapter must resolve and lock membership, Product and grant state, record the
policy decision, and issue a scoped receipt before allowing any write or replay.
No HTTP endpoint accepts these facts from a client.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class FeatureEditorAction(StrEnum):
    GRANT = "GRANT_FEATURE_EDITOR"
    REVOKE = "REVOKE_FEATURE_EDITOR"
    CREATE_FEATURE = "CREATE_FEATURE"
    UPDATE_FEATURE = "UPDATE_FEATURE"


@dataclass(frozen=True, slots=True)
class FeatureEditorFacts:
    workspace_id: UUID
    product_id: UUID
    actor_id: UUID
    owner_id: UUID
    actor_active_human: bool
    actor_active_member: bool
    actor_administrator: bool
    product_active: bool
    product_format_supported: bool
    feature_enabled: bool
    # A grant is valid only in the exact membership generation that issued it.
    membership_id: UUID | None = None
    membership_generation: int | None = None
    grant_workspace_id: UUID | None = None
    grant_product_id: UUID | None = None
    grant_member_id: UUID | None = None
    grant_membership_id: UUID | None = None
    grant_membership_generation: int | None = None
    grant_active: bool = False


def has_current_editor_grant(facts: FeatureEditorFacts) -> bool:
    """Revoked grants and grants from earlier membership lifetimes never revive."""
    return (
        facts.grant_active is True
        and facts.grant_workspace_id == facts.workspace_id
        and facts.grant_product_id == facts.product_id
        and facts.grant_member_id == facts.actor_id
        and facts.membership_id is not None
        and facts.grant_membership_id == facts.membership_id
        and type(facts.membership_generation) is int
        and facts.membership_generation >= 0
        and type(facts.grant_membership_generation) is int
        and facts.grant_membership_generation == facts.membership_generation
    )


def feature_editor_reason(action: FeatureEditorAction | str, facts: FeatureEditorFacts) -> str:
    """Return one deterministic reason for both original writes and replay checks."""
    if action not in {value.value for value in FeatureEditorAction}:
        return "UNKNOWN_ACTION"
    if not facts.feature_enabled:
        return "FEATURE_DISABLED"
    if not facts.actor_active_human or not facts.actor_active_member:
        return "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"
    if not facts.product_active:
        return "PRODUCT_UNAVAILABLE"
    if not facts.product_format_supported:
        return "PRODUCT_FORMAT_UNAVAILABLE"
    owner = facts.actor_id == facts.owner_id
    if action in {FeatureEditorAction.GRANT, FeatureEditorAction.REVOKE}:
        return "ALLOW" if owner or facts.actor_administrator else "PRODUCT_OWNER_OR_ADMINISTRATOR_REQUIRED"
    return "ALLOW" if owner or has_current_editor_grant(facts) else "PRODUCT_OWNER_OR_FEATURE_EDITOR_REQUIRED"
