# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Server-owned current PRD policy input; never accept this context over HTTP.

The caller supplies a trusted local object-policy resolver, not a provider read.
For command acceptance/commit use for_update=True in the policy-owned transaction.
Provider and protected-body access are separate current checks outside DB locks.
"""

from copy import deepcopy
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from plane.db.models import Workspace, WorkspaceMember
from .config import curve_environment, is_curve_enabled_for_workspace
from .models import GateAssignment, Initiative
from .policy_manifest import PRD_POLICY_MANIFEST_DIGEST
from .prd_metadata_validation import validate_prd_object_acl
from .policy_services import CurvePolicyResourceNotFound, _human_actor, correlation_id_for_request


PRD_ACTIONS = frozenset(f"CURVE.PRD.{name}" for name in ("SUBMIT", "APPROVE", "REQUEST_CHANGES", "REJECT"))
_ROLES = {"PRD_APPROVAL": "PRODUCT_APPROVER", "PLAN_APPROVAL": "TECHNICAL_APPROVER", "CODE_READINESS": "CODE_APPROVER"}


class PrdAuthorityUnavailable(PermissionError):
    def __init__(self):
        super().__init__("PRD_AUTHORITY_UNAVAILABLE")


def build_prd_policy_context(*, request, workspace_slug, initiative_id, action, acl_resolver, for_update=False):
    if for_update and not transaction.get_connection().in_atomic_block:
        raise PermissionError("PRD_AUTHORIZATION_TRANSACTION_REQUIRED")
    try:
        resolved_id = uuid.UUID(str(initiative_id))
    except (TypeError, ValueError):
        raise CurvePolicyResourceNotFound from None
    workspaces = Workspace.objects.select_for_update() if for_update else Workspace.objects
    try:
        workspace = workspaces.only("id", "slug").get(slug=workspace_slug)
    except Workspace.DoesNotExist:
        raise CurvePolicyResourceNotFound from None
    actor = _human_actor(getattr(request, "user", None))
    members = WorkspaceMember.objects.filter(
        workspace_id=workspace.id,
        is_active=True,
        member__is_active=True,
        member__is_bot=False,
    ).order_by("member_id")
    if for_update:
        members = members.select_for_update()
    try:
        actor_id = uuid.UUID(actor["actor_id"]) if actor["actor_type"] == "HUMAN" else None
    except ValueError:
        actor_id = None
    membership = members.filter(member_id=actor_id).first() if actor_id else None
    enabled = (
        is_curve_enabled_for_workspace(workspace.slug)
        and getattr(settings, "CURVE_PRD_COMMANDS_ENABLED", False) is True
    )
    initiative = None
    if membership is not None and enabled and action in PRD_ACTIONS:
        initiative = Initiative.objects.find_by_id(
            workspace_id=workspace.id, record_id=resolved_id, for_update=for_update
        )
    resource_ref = {"resource_type": "INITIATIVE", "resource_id": str(resolved_id)}
    roles = ["WORKSPACE_MEMBER"] if membership else []
    assignment_context = None
    object_acl = None
    classification = "UNKNOWN"
    owner = None
    now = timezone.now()
    if initiative is not None:
        resource_ref["resource_version"] = initiative.version
        owner = {"actor_type": "HUMAN", "actor_id": str(initiative.creator_user_id)}
        assignments = GateAssignment.objects.filter(workspace_id=workspace.id, initiative_id=initiative.id).order_by(
            "id"
        )
        if for_update:
            assignments = assignments.select_for_update()
        assignments = list(assignments)
        approver_ids = [assignment.approver_user_id for assignment in assignments]
        current_members = {str(member.member_id): member for member in members.filter(member_id__in=approver_ids)}
        now = timezone.now()  # Evaluate validity after any wait for row locks.
        gates = []
        for assignment in assignments:
            principal = {"actor_type": "HUMAN", "actor_id": str(assignment.approver_user_id)}
            active = (
                principal["actor_id"] in current_members
                and assignment.valid_from <= now
                and (assignment.valid_until is None or now < assignment.valid_until)
            )
            role = _ROLES.get(assignment.gate_type, "UNKNOWN")
            gates.append(dict(role=role, principal=principal, active=active))
            if active and principal == actor:
                roles.append(role)
        assignment_context = dict(
            workspace_id=str(workspace.id),
            subject_ref=deepcopy(resource_ref),
            assignment_version=initiative.version,
            risk_tier=initiative.risk_tier,
            gate_assignments=gates,
            material_contributors=[],
            overlap_exception_ref=None,
            low_risk_overlap_allowed=initiative.risk_tier == "LOW",
        )
        # A resolver failure must also deny the creator: None cannot stand in for
        # a failed lookup because it would suppress an explicit object denial.
        if not callable(acl_resolver):
            raise PrdAuthorityUnavailable
        try:
            observed = acl_resolver(
                workspace_id=workspace.id,
                actor=deepcopy(actor),
                action=action,
                resource_ref=deepcopy(resource_ref),
                evaluated_at=now,
            )
            if not isinstance(observed, dict) or set(observed) != {"classification", "object_acl"}:
                raise ValueError
            classification = observed["classification"]
            if not isinstance(classification, str) or classification not in {
                "INTERNAL",
                "CONFIDENTIAL",
                "RESTRICTED",
                "UNKNOWN",
            }:
                raise ValueError
            object_acl = deepcopy(observed["object_acl"])
            if object_acl is not None:
                validate_prd_object_acl(object_acl)
        except Exception:
            raise PrdAuthorityUnavailable from None
    return dict(
        schema_version="1.0",
        workspace_id=str(workspace.id),
        subject=actor,
        effective_principal=deepcopy(actor),
        membership=(
            dict(
                workspace_id=str(workspace.id),
                active=True,
                plane_role={5: "GUEST", 15: "MEMBER", 20: "ADMIN"}.get(membership.role),
            )
            if membership
            else None
        ),
        roles=sorted(set(roles)),
        action=action,
        resource=dict(workspace_id=str(workspace.id), ref=resource_ref, exists=initiative is not None, owner=owner),
        classification=classification,
        environment=curve_environment(),
        feature_enabled=enabled,
        object_acl=object_acl,
        assignment_context=assignment_context,
        target_context=None,
        service_authorization=None,
        evaluated_at=now.isoformat(),
        policy_manifest_digest=PRD_POLICY_MANIFEST_DIGEST,
        correlation_id=correlation_id_for_request(request),
    )
