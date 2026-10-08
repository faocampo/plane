# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from plane.curve.models import GateAssignment, Initiative
from plane.curve.product_serialization import human_actor


def serialize_gate_assignment(assignment: GateAssignment) -> dict:
    return {
        "id": str(assignment.id),
        "workspace_id": str(assignment.workspace_id),
        "initiative_id": str(assignment.initiative_id),
        "gate_type": assignment.gate_type,
        "approver": human_actor(assignment.approver_user_id),
        "valid_from": assignment.valid_from.isoformat(),
        "valid_until": assignment.valid_until.isoformat() if assignment.valid_until else None,
        "delegation_reason": assignment.delegation_reason,
    }


def serialize_initiative(initiative: Initiative) -> dict:
    assignments = initiative.gate_assignments.all().order_by("gate_type", "id")
    serialized = {
        "schema_version": initiative.schema_version,
        "id": str(initiative.id),
        "workspace_id": str(initiative.workspace_id),
        "product_id": str(initiative.product_id),
        "mode": initiative.mode,
        "roadmap_item_id": str(initiative.roadmap_item_id) if initiative.roadmap_item_id else None,
        "keyword": initiative.keyword,
        "title": initiative.title,
        "description": initiative.description,
        "risk_tier": initiative.risk_tier,
        "state": initiative.state,
        "paused_from_state": initiative.paused_from_state,
        "workflow_version_id": str(initiative.workflow_version_id) if initiative.workflow_version_id else None,
        "creator": human_actor(initiative.creator_user_id),
        "gate_assignments": [serialize_gate_assignment(assignment) for assignment in assignments],
        "first_external_resource_at": (
            initiative.first_external_resource_at.isoformat() if initiative.first_external_resource_at else None
        ),
        "version": initiative.version,
        "created_at": initiative.created_at.isoformat(),
        "updated_at": initiative.updated_at.isoformat(),
        "updated_by": initiative.updated_by,
    }
    if initiative.schema_version == "1.1":
        serialized["business_intent"] = initiative.business_intent
    return serialized


def initiative_etag(initiative: Initiative) -> str:
    return f'"curve-initiative:{initiative.id}:v{initiative.version}"'
