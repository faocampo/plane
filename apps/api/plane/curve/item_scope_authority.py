# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Locked current-owner facts for scope preparation; command policy remains separate."""

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction

from plane.curve.feature_authority_facts import resolve_feature_facts
from plane.curve.feature_editor_rules import FeatureEditorFacts
from plane.curve.models import Roadmap
from plane.curve.policy_services import CurvePolicyResourceNotFound
from plane.curve.item_scope_preparation import ItemScopeStorageContext


@dataclass(frozen=True, slots=True)
class ItemScopeFacts:
    product: FeatureEditorFacts
    roadmap_id: UUID
    roadmap_owner_id: UUID
    roadmap_version: int
    roadmap_active: bool
    roadmap_format_supported: bool

    def storage_context(self):
        if scope_preparation_reason(self) != "ALLOW":
            raise PermissionError("current Roadmap owner required")
        return ItemScopeStorageContext(
            workspace_id=str(self.product.workspace_id),
            product_id=str(self.product.product_id),
            roadmap_id=str(self.roadmap_id),
            actor_id=str(self.product.actor_id),
            membership_id=str(self.product.membership_id),
            membership_generation=self.product.membership_generation,
        )


def scope_preparation_reason(facts):
    if type(facts) is not ItemScopeFacts:
        raise TypeError("NATIVE_ITEM_SCOPE_FACTS_REQUIRED")
    product = facts.product
    if not product.feature_enabled:
        return "FEATURE_DISABLED"
    if not product.actor_active_human or not product.actor_active_member:
        return "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"
    if not product.product_active:
        return "PRODUCT_UNAVAILABLE"
    if not product.product_format_supported or not facts.roadmap_format_supported:
        return "FORMAT_UNAVAILABLE"
    if not facts.roadmap_active:
        return "RESOURCE_UNAVAILABLE"
    if product.actor_id != facts.roadmap_owner_id:
        return "ROADMAP_OWNER_REQUIRED"
    if (
        product.membership_id is None
        or type(product.membership_generation) is not int
        or product.membership_generation < 0
    ):
        return "CURRENT_MEMBERSHIP_LIFETIME_REQUIRED"
    return "ALLOW"


def resolve_item_scope_facts(*, workspace_slug, product_id, roadmap_id, actor_id):
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("ITEM_SCOPE_AUTHORITY_TRANSACTION_REQUIRED")
    product = resolve_feature_facts(workspace_slug=workspace_slug, product_id=product_id, actor_id=actor_id)
    try:
        identity = UUID(str(roadmap_id))
    except (ValueError, TypeError, AttributeError):
        raise CurvePolicyResourceNotFound from None
    roadmap = (
        Roadmap.objects.select_for_update(no_key=True)
        .filter(workspace_id=product.workspace_id, product_id=product.product_id, id=identity)
        .first()
    )
    if roadmap is None:
        raise CurvePolicyResourceNotFound
    return ItemScopeFacts(
        product=product,
        roadmap_id=roadmap.id,
        roadmap_owner_id=roadmap.owner_user_id,
        roadmap_version=roadmap.version,
        roadmap_active=roadmap.tombstoned_at is None,
        roadmap_format_supported=roadmap.schema_version == "1.0",
    )
