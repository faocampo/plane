# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Locked native context for the qualified Roadmap document-review edition."""

from dataclasses import dataclass
import uuid

from django.db import connection, transaction
from django.utils import timezone

from plane.db.models import User, Workspace, WorkspaceMember
from .item_creation_input import ItemCreationInputError
from .item_creation_material import normalize_scope_reference
from .local_initiative_context import LocalInitiativeContext
from .local_prd_review_models import LocalPrdSubmission
from .models import (
    Feature,
    GateAssignment,
    Initiative,
    Milestone,
    Product,
    Roadmap,
    RoadmapItem,
)
from .prd_commands import PrdCommandError
from .scope_proposal_models import ScopeProposal, ScopeProposalRevision


@dataclass(frozen=True, repr=False)
class RoadmapInitiativeContext(LocalInitiativeContext):
    roadmap_item: object = None


def _require(value):
    if not value:
        raise PrdCommandError("LOCAL_PRD_UNAVAILABLE", 404)


def require_roadmap_local_context(*, workspace_id, initiative_id, actor_id):
    """Resolve identity and live participants; caller owns policy and file leases.

    Qualification, feature activation, action-specific roles, protected document
    access and durable command effects remain the consuming command's duties.
    """
    _require(transaction.get_connection().in_atomic_block)
    try:
        actor_id = uuid.UUID(str(actor_id))
    except (ValueError, TypeError, AttributeError):
        raise PrdCommandError("LOCAL_PRD_UNAVAILABLE", 404) from None
    workspace = Workspace.objects.select_for_update().filter(id=workspace_id, deleted_at__isnull=True).first()
    _require(workspace is not None)
    initiative = Initiative.objects.find_by_id(workspace_id=workspace_id, record_id=initiative_id, for_update=True)
    _require(initiative is not None and initiative.schema_version == "1.2" and initiative.mode == "ROADMAP")
    _require(
        initiative.current_prd_checkpoint_id is None
        and initiative.controlling_prd_decision_id is None
        and initiative.pending_scope_reopening_id is None
    )
    for model in (ScopeProposal, ScopeProposalRevision):
        _require(not model.objects.filter(workspace_id=workspace_id, initiative_id=initiative_id).exists())
    _require(
        not LocalPrdSubmission.objects.filter(workspace_id=workspace_id, initiative_id=initiative_id)
        .exclude(payload__schema_version="curve.local-prd-submission/v3-roadmap-candidate")
        .exists()
    )
    product = Product.objects.find_by_id(workspace_id=workspace_id, record_id=initiative.product_id, for_update=True)
    _require(product is not None and product.state == "ACTIVE" and product.schema_version == "1.0")
    scoped = dict(
        workspace_id=workspace_id,
        product_id=product.id,
        schema_version="1.0",
        tombstoned_at__isnull=True,
    )
    item = (
        RoadmapItem.objects.select_for_update()
        .filter(
            **scoped,
            id=initiative.roadmap_item_id,
            defining_initiative_id=initiative.id,
        )
        .first()
    )
    _require(item is not None)
    roadmap = Roadmap.objects.select_for_update().filter(**scoped, id=item.roadmap_id).first()
    feature = Feature.objects.select_for_update().filter(**scoped, id=item.feature_id).first()
    milestone = (
        Milestone.objects.select_for_update().filter(**scoped, id=item.milestone_id, roadmap_id=item.roadmap_id).first()
    )
    _require(roadmap is not None and feature is not None and milestone is not None)
    try:
        scope = normalize_scope_reference(item.scope_body)
    except ItemCreationInputError:
        raise PrdCommandError("LOCAL_PRD_UNAVAILABLE", 404) from None
    now = timezone.now()
    assignments = list(
        GateAssignment.objects.select_for_update()
        .filter(
            workspace_id=workspace_id,
            initiative_id=initiative.id,
            gate_type__in=["PLAN_APPROVAL", "PRD_APPROVAL"],
        )
        .order_by("gate_type")
    )
    _require(len(assignments) == 2 and [row.gate_type for row in assignments] == ["PLAN_APPROVAL", "PRD_APPROVAL"])
    _require(all(row.valid_from <= now and (row.valid_until is None or now < row.valid_until) for row in assignments))
    _require(initiative.risk_tier in {"LOW", "STANDARD", "HIGH"})
    if initiative.risk_tier != "LOW":
        _require(assignments[0].approver_user_id != assignments[1].approver_user_id)
    participants = {
        initiative.creator_user_id,
        *(row.approver_user_id for row in assignments),
    }
    _require(actor_id in participants)
    users = list(
        User.objects.select_for_update().filter(id__in=participants, is_active=True, is_bot=False).order_by("id")
    )
    memberships = list(
        WorkspaceMember.objects.select_for_update()
        .filter(
            workspace_id=workspace_id,
            member_id__in=participants,
            is_active=True,
            deleted_at__isnull=True,
            role__in=[5, 15, 20],
        )
        .order_by("member_id")
    )
    _require(len(users) == len(memberships) == len(participants))
    lifetimes = []
    with connection.cursor() as cursor:
        for member in memberships:
            cursor.execute(
                "SELECT generation FROM curve_feature_membership_lifetime WHERE membership_id=%s FOR UPDATE",
                [member.id],
            )
            row = cursor.fetchone()
            _require(row is not None and type(row[0]) is int and row[0] >= 0)
            lifetimes.append((member.id, member.member_id, member.role, row[0]))
    reviewers = tuple(
        dict(
            gate_assignment_id=str(row.id),
            gate_type=row.gate_type,
            approver_user_id=str(row.approver_user_id),
        )
        for row in assignments
    )
    return RoadmapInitiativeContext(
        workspace=workspace,
        initiative=initiative,
        product=product,
        actor_id=actor_id,
        reviewers=reviewers,
        roadmap_item=item,
        fence=(
            "ROADMAP_DOCUMENT_REVIEW_V3",
            product.id,
            product.version,
            product.state,
            initiative.id,
            initiative.version,
            initiative.business_intent,
            initiative.risk_tier,
            initiative.creator_user_id,
            item.id,
            item.version,
            item.defining_initiative_id,
            tuple(sorted(scope.items())),
            roadmap.id,
            roadmap.version,
            feature.id,
            feature.version,
            milestone.id,
            milestone.version,
            tuple((row.id, row.approver_user_id, row.valid_from, row.valid_until) for row in assignments),
            tuple(lifetimes),
        ),
    )
