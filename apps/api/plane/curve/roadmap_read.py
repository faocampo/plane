# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Product-authorized safe Roadmap hierarchy metadata; no document/body projection."""

import uuid
from datetime import date, datetime

from django.db import transaction
from django.db.models import Q
from plane.curve.models import Milestone, Roadmap
from plane.curve.policy_services import CurvePolicyResourceNotFound
from plane.curve.product_policy import authorize_product_query
from plane.curve.roadmap_policy import RoadmapFormatUnavailable
from plane.curve.scope_reopening_qualification import require_roadmap_hierarchy_qualification
from plane.db.models import User, Workspace, WorkspaceMember


class RoadmapCursorStale(Exception):
    pass


def serialize_hierarchy(record):
    if record.schema_version != "1.0":
        raise RoadmapFormatUnavailable
    fields = ["id", "schema_version", "workspace_id", "product_id", "version", "name", "created_at", "updated_at"]
    fields += (
        ["roadmap_id", "type", "position", "target_start", "target_end"]
        if isinstance(record, Milestone)
        else ["owner_user_id", "horizon_start", "horizon_end"]
    )
    return {
        name: value.isoformat()
        if isinstance(value, (date, datetime))
        else str(value)
        if isinstance(value, uuid.UUID)
        else value
        for name in fields
        for value in [getattr(record, name)]
    }


def read_hierarchy(
    *,
    request,
    workspace_slug,
    product_id,
    roadmap_id=None,
    milestone_id=None,
    collection=False,
    page_size=50,
    after=None,
):
    with transaction.atomic():
        require_roadmap_hierarchy_qualification()
        workspace = Workspace.objects.select_for_update().filter(slug=workspace_slug).first()
        user = request.user
        if workspace is None or user is None or not getattr(user, "is_authenticated", False):
            raise CurvePolicyResourceNotFound
        membership = (
            WorkspaceMember.objects.select_for_update()
            .filter(workspace_id=workspace.id, member_id=user.id, is_active=True)
            .first()
        )
        if (
            membership is None
            or not User.objects.select_for_update().filter(id=user.id, is_active=True, is_bot=False).exists()
        ):
            raise CurvePolicyResourceNotFound
        authorization = authorize_product_query(request=request, workspace_slug=workspace_slug, product_id=product_id)
        product = authorization.product
        if product is None or product.state != "ACTIVE":
            raise CurvePolicyResourceNotFound
        scope = {"workspace_id": workspace.id, "product_id": product.id, "tombstoned_at__isnull": True}
        parent = None
        if roadmap_id is not None:
            parent = Roadmap.objects.filter(**scope, id=roadmap_id).first()
            if parent is None:
                raise CurvePolicyResourceNotFound
            if parent.schema_version != "1.0":
                raise RoadmapFormatUnavailable
        if milestone_id is not None:
            record = (
                Milestone.objects.filter(**scope, roadmap_id=parent.id, id=milestone_id).first() if parent else None
            )
            if record is None:
                raise CurvePolicyResourceNotFound
            return serialize_hierarchy(record)
        if not collection:
            if parent is None:
                raise CurvePolicyResourceNotFound
            return serialize_hierarchy(parent)
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("invalid page size")
        rows = Milestone.objects.filter(**scope, roadmap_id=parent.id) if parent else Roadmap.objects.filter(**scope)
        if parent is not None:
            if after is not None:
                version, position, identity = after
                if version != parent.version:
                    raise RoadmapCursorStale
                rows = rows.filter(Q(position__gt=position) | Q(position=position, id__gt=identity))
            rows = rows.order_by("position", "id")
        else:
            if after is not None:
                rows = rows.filter(id__gt=after)
            rows = rows.order_by("id")
        selected = list(rows[: page_size + 1])
        cursor = None
        if len(selected) > page_size:
            last = selected[page_size - 1]
            cursor = f"{parent.version}:{last.position}:{last.id}" if parent is not None else str(last.id)
        result = {"results": [serialize_hierarchy(row) for row in selected[:page_size]], "next_cursor": cursor}
        if parent is not None:
            result["roadmap_version"] = parent.version
        return result
