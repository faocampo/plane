# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Receipt reads require current access; an old creation role supplies no authority."""


def recovery_read_reason(facts, *, enabled, local):
    if not enabled or not facts.product.feature_enabled:
        return "FEATURE_DISABLED"
    if not local:
        return "LOCAL_ITEM_PROFILE_REQUIRED"
    if not facts.product.actor_active_human or not facts.product.actor_active_member:
        return "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"
    if not facts.product.product_active:
        return "PRODUCT_UNAVAILABLE"
    if not facts.product.product_format_supported or not facts.roadmap_format_supported:
        return "FORMAT_UNAVAILABLE"
    if not facts.roadmap_active:
        return "RESOURCE_UNAVAILABLE"
    if (
        facts.product.membership_id is None
        or type(facts.product.membership_generation) is not int
        or facts.product.membership_generation < 0
    ):
        return "CURRENT_MEMBERSHIP_LIFETIME_REQUIRED"
    return "ALLOW"
