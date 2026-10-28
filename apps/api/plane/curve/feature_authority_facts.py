# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Locked native Feature facts; the caller still owes policy and protected access.

No route accepts these facts. A qualified command must derive actor identity from
its authenticated session, record its decision and audit, and hold the enclosing
transaction through writes, protected-material revalidation and replay.
"""

from uuid import UUID

from django.db import connection, transaction

from plane.curve.config import is_curve_enabled_for_workspace
from plane.curve.feature_editor_rules import FeatureEditorFacts
from plane.curve.models import Product
from plane.curve.policy_services import CurvePolicyResourceNotFound
from plane.curve.product_format import (
    ProductFormatUnavailable,
    require_supported_product_format,
)
from plane.db.models import User, Workspace, WorkspaceMember


def resolve_feature_facts(*, workspace_slug, product_id, actor_id):
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("FEATURE_AUTHORITY_TRANSACTION_REQUIRED")
    try:
        product_id, actor_id = UUID(str(product_id)), UUID(str(actor_id))
    except (ValueError, TypeError, AttributeError) as error:
        raise CurvePolicyResourceNotFound from error
    workspace = Workspace.objects.select_for_update(no_key=True).filter(slug=workspace_slug).first()
    if workspace is None:
        raise CurvePolicyResourceNotFound
    member = (
        WorkspaceMember.objects.select_for_update(no_key=True)
        .filter(workspace_id=workspace.id, member_id=actor_id)
        .first()
    )
    human = User.objects.select_for_update(no_key=True).filter(id=actor_id).first()
    product = Product.objects.select_for_update(no_key=True).filter(workspace_id=workspace.id, id=product_id).first()
    if product is None:
        raise CurvePolicyResourceNotFound
    supported = True
    try:
        require_supported_product_format(product)
    except ProductFormatUnavailable:
        supported = False
    generation = grant = None
    active_member = member is not None and member.is_active and member.deleted_at is None
    if active_member:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT generation FROM curve_feature_membership_lifetime WHERE membership_id=%s FOR UPDATE",
                [member.id],
            )
            lifetime = cursor.fetchone()
            if lifetime is not None:
                generation = lifetime[0]
                cursor.execute(
                    "SELECT workspace_id, product_id, member_id, membership_id, membership_generation "
                    "FROM curve_feature_editor_grant WHERE workspace_id=%s AND product_id=%s AND member_id=%s "
                    "AND membership_id=%s AND membership_generation=%s AND revoked_at IS NULL FOR UPDATE",
                    [workspace.id, product.id, actor_id, member.id, generation],
                )
                grant = cursor.fetchone()
    return FeatureEditorFacts(
        workspace_id=workspace.id,
        product_id=product.id,
        actor_id=actor_id,
        owner_id=product.owner_user_id,
        actor_active_human=human is not None and human.is_active and not human.is_bot,
        actor_active_member=active_member,
        actor_administrator=active_member and member.role == 20,
        product_active=product.state == "ACTIVE",
        product_format_supported=supported,
        feature_enabled=is_curve_enabled_for_workspace(workspace.slug),
        membership_id=member.id if active_member else None,
        membership_generation=generation,
        grant_workspace_id=grant[0] if grant else None,
        grant_product_id=grant[1] if grant else None,
        grant_member_id=grant[2] if grant else None,
        grant_membership_id=grant[3] if grant else None,
        grant_membership_generation=grant[4] if grant else None,
        grant_active=grant is not None,
    )
