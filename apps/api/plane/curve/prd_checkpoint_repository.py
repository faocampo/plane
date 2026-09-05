# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Atomic capture metadata dependency for the authenticated submission command.

Caller must authorize current actor/source/evidence/storage and revalidate those
observations at its commit fence. Wrap this helper in the command transaction
with Initiative transition/current pointer, idempotency result and audit/outbox.
This helper records metadata only; it enables no provider or storage capability.
"""

from django.db import transaction

from .models import DocumentCheckpoint, ExternalDocumentBinding, Initiative, InitiativeState
from .prd_metadata_repository import append_prd_submission_metadata
from .prd_metadata_validation import require_metadata


@transaction.atomic
def append_document_checkpoint_metadata(
    *,
    workspace_id,
    initiative_id,
    expected_initiative_version,
    artifact_id,
    expected_parent_version_id,
    expected_predecessor_id,
    snapshot,
    version,
    checkpoint,
):
    initiative = Initiative.objects.find_by_id(workspace_id=workspace_id, record_id=initiative_id, for_update=True)
    require_metadata(initiative is not None, "CHECKPOINT_INITIATIVE_UNAVAILABLE")
    require_metadata(
        type(expected_initiative_version) is int and initiative.version == expected_initiative_version,
        "CHECKPOINT_INITIATIVE_VERSION_CONFLICT",
    )
    require_metadata(initiative.state == InitiativeState.ALIGNING, "CHECKPOINT_INITIATIVE_STATE_CONFLICT")
    require_metadata(
        checkpoint.workspace_id == version.workspace_id == snapshot.workspace_id == initiative.workspace_id
        and checkpoint.initiative_id == version.initiative_id == snapshot.initiative_id == initiative.id
        and version.artifact_id == artifact_id
        and checkpoint.artifact_version_id == version.id
        and checkpoint.evidence_snapshot_id == snapshot.id
        and checkpoint.predecessor_id == expected_predecessor_id,
        "CHECKPOINT_SUBMISSION_LINKAGE_INVALID",
    )
    binding = ExternalDocumentBinding.objects.find_by_id(
        workspace_id=workspace_id, record_id=checkpoint.external_document_binding_id, for_update=True
    )
    require_metadata(binding is not None and binding.initiative_id == initiative.id, "CHECKPOINT_REFERENCE_UNAVAILABLE")
    previous = (
        DocumentCheckpoint.objects.for_workspace(workspace_id)
        .filter(external_document_binding_id=binding.id)
        .order_by("-checkpoint_number")
        .first()
    )
    require_metadata((previous.id if previous else None) == expected_predecessor_id, "CHECKPOINT_PREDECESSOR_CONFLICT")
    append_prd_submission_metadata(
        workspace_id=workspace_id,
        artifact_id=artifact_id,
        expected_parent_version_id=expected_parent_version_id,
        snapshot=snapshot,
        version=version,
    )
    checkpoint.save()
    return checkpoint
