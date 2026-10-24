# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Internal metadata commit seam for the future authenticated PRD command.

Call only after current source/body/evidence authorization and storage checks.
This primitive grants no permission, records no human gate decision, and does
not change Initiative state. The command must wrap it with its audit/outbox,
idempotency result and Initiative version change in the same outer transaction.
"""

from django.db import transaction

from .models import PrdArtifact
from .prd_metadata_validation import require_metadata


@transaction.atomic
def append_prd_submission_metadata(*, workspace_id, artifact_id, expected_parent_version_id, snapshot, version):
    artifact = PrdArtifact.objects.find_by_id(workspace_id=workspace_id, record_id=artifact_id, for_update=True)
    require_metadata(artifact is not None, "PRD_ARTIFACT_NOT_FOUND")
    require_metadata(artifact.current_version_id == expected_parent_version_id, "PRD_PARENT_VERSION_CONFLICT")
    require_metadata(
        version.workspace_id == artifact.workspace_id == snapshot.workspace_id
        and version.initiative_id == artifact.initiative_id == snapshot.initiative_id
        and version.artifact_id == artifact.id
        and version.parent_version_id == expected_parent_version_id
        and snapshot.artifact_version_id == version.id
        and version.evidence_snapshot_id == snapshot.id,
        "PRD_SUBMISSION_METADATA_LINKAGE_INVALID",
    )
    snapshot.save()
    version.save()
    artifact.current_version = version
    artifact.save()
    return artifact
