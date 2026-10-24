# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Exact policy evidence for local-upload commands with fresh native authority."""

import hashlib
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from .config import curve_policy_recorder
from .local_new_work_policy import policy_identity
from .local_document_authority import require_local_document_authority
from .manual_plan_v3.policy import _observation_json
from .models import PolicyDecision
from .policy_services import _next_policy_sequence, correlation_id_for_request
from .prd_commands import PrdCommandError
from .services import canonical_json_bytes, sha256_digest

POLICY_KEY = "CURVE_LOCAL_PRD_POLICY"
POLICY_DIGEST = "sha256:bfded3fd13b5dd90bb45aa7fc3681b9836b0adf63c7b64d6f7838e8d14ee9c30"


def record_upload_authorization(*, request, workspace_slug, initiative_id, expected_version, request_digest):
    if not transaction.get_connection().in_atomic_block:
        raise PrdCommandError("LOCAL_PRD_TRANSACTION_REQUIRED", 503)
    path = Path(__file__).parent / "two_stage_review/local-prd-policy-v1.json"
    if path.is_symlink() or "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != POLICY_DIGEST:
        raise PrdCommandError("LOCAL_PRD_POLICY_UNAVAILABLE", 503)
    authority = require_local_document_authority(
        request=request,
        workspace_slug=workspace_slug,
        initiative_id=initiative_id,
        action="UPLOAD",
        expected_version=expected_version,
    )
    context = authority.context
    policy_version, policy_digest = policy_identity(context, POLICY_KEY, POLICY_DIGEST)
    actor = dict(actor_type="HUMAN", actor_id=str(context.actor_id))
    now = timezone.now()
    decision = PolicyDecision.objects.create(
        workspace_id=context.workspace.id,
        sequence=_next_policy_sequence(
            workspace_id=context.workspace.id, resource_type="INITIATIVE", resource_id=context.initiative.id
        ),
        action="CURVE.LOCAL_PRD.UPLOAD",
        resource_type="INITIATIVE",
        resource_id=context.initiative.id,
        resource_version=context.initiative.version,
        subject=actor,
        effective_principal=actor,
        effect="ALLOW",
        reason_codes=["ALLOW"],
        policy_key=POLICY_KEY,
        policy_version=policy_version,
        policy_manifest_digest=policy_digest,
        input_digest=sha256_digest(
            canonical_json_bytes(dict(request_digest=request_digest, native_fence=_observation_json(authority.fence)))
        ),
        normalized_classification="INTERNAL",
        permitted_projection=["LOCAL_PRD_SOURCE_METADATA_V1"],
        correlation_id=correlation_id_for_request(request),
        evaluated_at=now,
        recorded_at=now,
        recorded_by=curve_policy_recorder(),
    )
    return authority, decision
