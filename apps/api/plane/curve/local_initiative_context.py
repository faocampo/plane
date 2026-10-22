# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Fresh local document access for new Initiatives and retained scoped work."""

from dataclasses import dataclass
import uuid
from django.db import transaction
from django.utils import timezone
from plane.db.models import User, Workspace, WorkspaceMember
from .models import GateAssignment, Initiative, Product
from .prd_commands import PrdCommandError
from .scope_proposal_models import ScopeProposal, ScopeProposalRevision
from .scoped_prd_policy import require_scoped_current
from .local_prd_review_models import LocalPrdSubmission


@dataclass(frozen=True, repr=False)
class LocalInitiativeContext:
    workspace: object
    initiative: object
    product: object
    actor_id: uuid.UUID
    reviewers: tuple
    fence: tuple
    head: object = None
    revision: object = None


def _require(value):
    if not value:
        raise PrdCommandError("LOCAL_PRD_UNAVAILABLE", 404)


def require_local_initiative_context(*, workspace_id, initiative_id, actor_id):
    _require(transaction.get_connection().in_atomic_block)
    workspace = Workspace.objects.select_for_update().filter(id=workspace_id).first()
    _require(workspace is not None)
    initiative = Initiative.objects.find_by_id(workspace_id=workspace_id, record_id=initiative_id, for_update=True)
    _require(initiative is not None and initiative.schema_version == "1.2" and initiative.mode == "STANDALONE")
    # A retained scope always retains its original per-source authorization.
    if (
        ScopeProposal.objects.select_for_update()
        .filter(workspace_id=workspace_id, initiative_id=initiative_id)
        .exists()
    ):
        return require_scoped_current(workspace_id=workspace_id, initiative_id=initiative_id, actor_id=actor_id)
    _require(not ScopeProposalRevision.objects.filter(workspace_id=workspace_id, initiative_id=initiative_id).exists())
    _require(
        not LocalPrdSubmission.objects.filter(
            workspace_id=workspace_id,
            initiative_id=initiative_id,
            payload__schema_version="curve.local-prd-submission/v1-candidate",
        ).exists()
    )
    _require(
        initiative.current_prd_checkpoint_id is None
        and initiative.controlling_prd_decision_id is None
        and initiative.pending_scope_reopening_id is None
    )
    product = Product.objects.find_by_id(workspace_id=workspace_id, record_id=initiative.product_id, for_update=True)
    _require(product is not None and product.state == "ACTIVE")
    now = timezone.now()
    assignments = list(
        GateAssignment.objects.select_for_update()
        .filter(workspace_id=workspace_id, initiative_id=initiative_id, gate_type__in=["PLAN_APPROVAL", "PRD_APPROVAL"])
        .order_by("gate_type")
    )
    _require(len(assignments) == 2 and [a.gate_type for a in assignments] == ["PLAN_APPROVAL", "PRD_APPROVAL"])
    _require(all(a.valid_from <= now and (a.valid_until is None or now < a.valid_until) for a in assignments))
    _require(initiative.risk_tier in {"LOW", "STANDARD", "HIGH"})
    if initiative.risk_tier != "LOW":
        _require(assignments[0].approver_user_id != assignments[1].approver_user_id)
    actor_id = uuid.UUID(str(actor_id))
    # Include the owner even when a reviewer reads: every participant must retain access.
    user_ids = sorted({actor_id, initiative.creator_user_id, *(a.approver_user_id for a in assignments)})
    users = list(User.objects.select_for_update().filter(id__in=user_ids, is_active=True, is_bot=False).order_by("id"))
    memberships = list(
        WorkspaceMember.objects.select_for_update()
        .filter(workspace_id=workspace_id, member_id__in=user_ids, is_active=True, role__in=[5, 15, 20])
        .order_by("member_id")
    )
    _require(len(users) == len(user_ids) == len(memberships))
    reviewers = tuple(
        dict(gate_assignment_id=str(a.id), gate_type=a.gate_type, approver_user_id=str(a.approver_user_id))
        for a in assignments
    )
    return LocalInitiativeContext(
        workspace,
        initiative,
        product,
        actor_id,
        reviewers,
        (
            "NEW_INITIATIVE_DOCUMENT_REVIEW_V2",
            product.id,
            product.version,
            product.state,
            initiative.business_intent,
            initiative.risk_tier,
            initiative.creator_user_id,
            tuple((a.id, a.approver_user_id, a.valid_from, a.valid_until) for a in assignments),
            tuple((m.id, m.member_id, m.role, m.is_active) for m in memberships),
        ),
    )
