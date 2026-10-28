# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Owner/admin editor management projection with current membership status."""

from datetime import datetime
from uuid import UUID

from django.db import connection, transaction

from plane.curve.models import Product
from plane.curve.policy_services import CurvePolicyResourceNotFound
from plane.curve.product_policy import authorize_product_query
from plane.curve.scope_reopening_qualification import require_feature_editor_command_qualification
from plane.db.models import User, Workspace, WorkspaceMember


_COLUMNS = ("id", "version", "member_id", "granted_by", "granted_at", "revoked_by", "revoked_at", "status")


def read_feature_editors(*, request, workspace_slug, product_id, grant_id=None, page_size=50, after=None):
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise ValueError("invalid page size")
    try:
        product_id = UUID(str(product_id))
        grant_id = UUID(str(grant_id)) if grant_id is not None else None
        after = UUID(str(after)) if after is not None else None
    except (ValueError, TypeError, AttributeError) as error:
        raise CurvePolicyResourceNotFound from error
    with transaction.atomic():
        require_feature_editor_command_qualification()
        user = request.user
        if user is None or not getattr(user, "is_authenticated", False):
            raise CurvePolicyResourceNotFound
        # Keep authority rows stable while allowing deferred foreign-key checks
        # from a concurrent membership update to finish before we take its lock.
        workspace = Workspace.objects.select_for_update(no_key=True).filter(slug=workspace_slug).first()
        if workspace is None:
            raise CurvePolicyResourceNotFound
        membership = (
            WorkspaceMember.objects.select_for_update(no_key=True)
            .filter(workspace_id=workspace.id, member_id=user.id, is_active=True, deleted_at__isnull=True)
            .first()
        )
        human = User.objects.select_for_update(no_key=True).filter(id=user.id, is_active=True, is_bot=False).first()
        if membership is None or human is None:
            raise CurvePolicyResourceNotFound
        product = (
            Product.objects.select_for_update(no_key=True).filter(workspace_id=workspace.id, id=product_id).first()
        )
        if product is None or product.state != "ACTIVE":
            raise CurvePolicyResourceNotFound
        if product.owner_user_id != user.id and membership.role != 20:
            raise CurvePolicyResourceNotFound
        authorize_product_query(request=request, workspace_slug=workspace_slug, product_id=product_id)
        where = "g.workspace_id=%s AND g.product_id=%s"
        params = [workspace.id, product.id]
        if grant_id is not None:
            where += " AND g.id=%s"
            params.append(grant_id)
        elif after is not None:
            where += " AND g.id>%s"
            params.append(after)
        params.append(1 if grant_id else page_size + 1)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT g.id,g.version,g.member_id,g.granted_by,g.granted_at,g.revoked_by,g.revoked_at,"
                "CASE WHEN g.revoked_at IS NOT NULL THEN 'REVOKED' "
                "WHEN m.id IS NULL OR NOT m.is_active OR m.deleted_at IS NOT NULL "
                "OR u.id IS NULL OR NOT u.is_active OR u.is_bot "
                "OR l.generation IS DISTINCT FROM g.membership_generation THEN 'MEMBERSHIP_LOST' "
                "ELSE 'ACTIVE' END "
                "FROM curve_feature_editor_grant g "
                "LEFT JOIN workspace_members m ON m.id=g.membership_id "
                "AND m.workspace_id=g.workspace_id AND m.member_id=g.member_id "
                "LEFT JOIN users u ON u.id=g.member_id "
                "LEFT JOIN curve_feature_membership_lifetime l ON l.membership_id=g.membership_id "
                "WHERE " + where + " ORDER BY g.id LIMIT %s",
                params,
            )
            rows = [
                {
                    key: value.isoformat()
                    if isinstance(value, datetime)
                    else str(value)
                    if isinstance(value, UUID)
                    else value
                    for key, value in zip(_COLUMNS, row, strict=True)
                }
                for row in cursor.fetchall()
            ]
        if grant_id:
            if not rows:
                raise CurvePolicyResourceNotFound
            return rows[0]
        return {
            "results": rows[:page_size],
            "next_cursor": rows[page_size - 1]["id"] if len(rows) > page_size else None,
            "can_manage_editors": True,
        }
