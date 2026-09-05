# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Transactional domain writes for the authenticated PRD command boundary.

These internal helpers require an outer transaction and server-derived inputs.
They grant no authorization, perform no provider/storage reads, and do not create
an Operation or audit. The consuming command must perform current authorization
and commit idempotency, result, audit and outbox in that same outer transaction.
"""

from copy import deepcopy

from django.db import transaction

from .models import Initiative
from .prd_checkpoint_repository import append_document_checkpoint_metadata
from .prd_metadata_validation import require_metadata


def _lock_subject(*, workspace_id, initiative_id, expected_version, expected_checkpoint_id):
    require_metadata(transaction.get_connection().in_atomic_block, "PRD_OUTER_TRANSACTION_REQUIRED")
    initiative = Initiative.objects.find_by_id(workspace_id=workspace_id, record_id=initiative_id, for_update=True)
    require_metadata(initiative is not None, "PRD_INITIATIVE_UNAVAILABLE")
    require_metadata(
        type(expected_version) is int and initiative.version == expected_version,
        "PRD_INITIATIVE_VERSION_CONFLICT",
    )
    require_metadata(initiative.current_prd_checkpoint_id == expected_checkpoint_id, "PRD_CURRENT_CHECKPOINT_CONFLICT")
    return initiative


def record_prd_submission_transition(
    *,
    workspace_id,
    initiative_id,
    expected_version,
    expected_checkpoint_id,
    actor,
    artifact_id,
    expected_parent_version_id,
    snapshot,
    version,
    checkpoint,
):
    initiative = _lock_subject(
        workspace_id=workspace_id,
        initiative_id=initiative_id,
        expected_version=expected_version,
        expected_checkpoint_id=expected_checkpoint_id,
    )
    require_metadata(initiative.state in {"ALIGNING", "PRD_REVIEW"}, "PRD_INITIATIVE_STATE_CONFLICT")
    require_metadata(
        actor == checkpoint.submitted_or_approved_by and actor.get("actor_type") == "HUMAN",
        "PRD_SUBMITTER_ATTRIBUTION_MISMATCH",
    )
    with transaction.atomic():
        append_document_checkpoint_metadata(
            workspace_id=workspace_id,
            initiative_id=initiative_id,
            expected_initiative_version=expected_version,
            artifact_id=artifact_id,
            expected_parent_version_id=expected_parent_version_id,
            expected_predecessor_id=expected_checkpoint_id,
            snapshot=snapshot,
            version=version,
            checkpoint=checkpoint,
        )
        initiative.current_prd_checkpoint_id = checkpoint.id
        initiative.controlling_prd_decision_id = None
        initiative.state = "PRD_REVIEW"
        initiative.version += 1
        initiative.updated_by = deepcopy(actor)
        initiative.save(
            update_fields=[
                "current_prd_checkpoint_id",
                "controlling_prd_decision_id",
                "state",
                "version",
                "updated_by",
                "updated_at",
            ]
        )
    return initiative


def record_prd_decision_transition(
    *,
    workspace_id,
    initiative_id,
    expected_version,
    expected_checkpoint_id,
    actor,
    decision,
):
    initiative = _lock_subject(
        workspace_id=workspace_id,
        initiative_id=initiative_id,
        expected_version=expected_version,
        expected_checkpoint_id=expected_checkpoint_id,
    )
    require_metadata(initiative.state == "PRD_REVIEW", "PRD_INITIATIVE_STATE_CONFLICT")
    require_metadata(
        decision.workspace_id == initiative.workspace_id
        and decision.initiative_id == initiative.id
        and decision.checkpoint_id == expected_checkpoint_id
        and actor == decision.decided_by,
        "PRD_DECISION_ATTRIBUTION_OR_SCOPE_MISMATCH",
    )
    with transaction.atomic():
        decision.save()
        initiative.controlling_prd_decision_id = decision.id
        initiative.state = "PLANNING" if decision.state == "APPROVED" else "ALIGNING"
        initiative.version += 1
        initiative.updated_by = deepcopy(actor)
        initiative.save(update_fields=["controlling_prd_decision_id", "state", "version", "updated_by", "updated_at"])
    return initiative
