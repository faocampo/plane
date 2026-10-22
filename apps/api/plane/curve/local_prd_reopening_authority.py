# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Owner-only reopening of the exact current Product approval."""

import hashlib
from pathlib import Path
from django.db import transaction
from django.utils import timezone
from .config import curve_policy_recorder
from .local_new_work_policy import policy_identity
from .local_prd_review_authority import require_local_review_authority
from .local_prd_reopening_models import LocalPrdReopening
from .manual_plan_v3.policy import _observation_json
from .models import PolicyDecision
from .policy_services import _next_policy_sequence, correlation_id_for_request
from .prd_commands import PrdCommandError
from .services import canonical_json_bytes, sha256_digest

POLICY_KEY = "CURVE_LOCAL_PRD_REOPENING_POLICY"
POLICY_DIGEST = "sha256:ac4466f235b1f0baefe4ea35285f65cfe44e144ee7de3bbf89dda57af17a7616"


def require_local_reopening_authority(
    *,
    request,
    workspace_slug,
    initiative_id,
    replay=False,
    expected_version=None,
    source_id=None,
    source_digest=None,
    submission_id=None,
    submission_digest=None,
    decision_id=None,
    decision_digest=None,
):
    current = require_local_review_authority(
        request=request,
        workspace_slug=workspace_slug,
        initiative_id=initiative_id,
        action="READ",
        expected_version=None if replay else expected_version,
    )
    context = current.document.context
    init = context.initiative
    if context.actor_id != init.creator_user_id:
        raise PrdCommandError("LOCAL_REOPENING_UNAVAILABLE", 404)
    if replay:
        return current
    if type(expected_version) is not int or not 0 < expected_version < 9007199254740991:
        raise PrdCommandError("LOCAL_REOPENING_VERSION_REQUIRED", 428)
    source = current.document.current_source
    if (
        init.state != "PLANNING"
        or not current.submission_is_current
        or current.submission is None
        or current.decision is None
        or current.decision.state != "APPROVED"
        or source is None
        or init.current_local_prd_submission_id != current.submission.id
        or init.controlling_local_prd_decision_id != current.decision.id
        or source_id != str(source.id)
        or source_digest != source.digest
        or submission_id != str(current.submission.id)
        or submission_digest != current.submission.digest
        or decision_id != str(current.decision.id)
        or decision_digest != current.decision.digest
        or LocalPrdReopening.objects.filter(
            workspace_id=init.workspace_id, initiative_id=init.id, decision_id=current.decision.id
        ).exists()
    ):
        raise PrdCommandError("LOCAL_REOPENING_SUBJECT_CHANGED", 409)
    return current


def record_reopening_authorization(*, request, workspace_slug, initiative_id, request_digest, replay=False, **subject):
    if not transaction.get_connection().in_atomic_block:
        raise PrdCommandError("LOCAL_REOPENING_TRANSACTION_REQUIRED", 503)
    path = Path(__file__).parent / "two_stage_review/local-prd-reopening-policy-v1.json"
    if path.is_symlink() or "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != POLICY_DIGEST:
        raise PrdCommandError("LOCAL_REOPENING_POLICY_UNAVAILABLE", 503)
    current = require_local_reopening_authority(
        request=request, workspace_slug=workspace_slug, initiative_id=initiative_id, replay=replay, **subject
    )
    context = current.document.context
    policy_version, policy_digest = policy_identity(context, POLICY_KEY, POLICY_DIGEST)
    actor = dict(actor_type="HUMAN", actor_id=str(context.actor_id))
    now = timezone.now()
    policy = PolicyDecision.objects.create(
        workspace_id=context.workspace.id,
        sequence=_next_policy_sequence(
            workspace_id=context.workspace.id, resource_type="INITIATIVE", resource_id=context.initiative.id
        ),
        action="CURVE.LOCAL_PRD.REOPEN",
        resource_type="INITIATIVE",
        resource_id=context.initiative.id,
        resource_version=context.initiative.version,
        subject=actor,
        effective_principal=actor,
        effect="ALLOW",
        reason_codes=["AUTHORIZED_REPLAY" if replay else "ALLOW"],
        policy_key=POLICY_KEY,
        policy_version=policy_version,
        policy_manifest_digest=policy_digest,
        input_digest=sha256_digest(
            canonical_json_bytes(dict(request_digest=request_digest, native_fence=_observation_json(current.fence)))
        ),
        normalized_classification="INTERNAL",
        permitted_projection=["LOCAL_PRD_REOPENING_METADATA_V1"],
        correlation_id=correlation_id_for_request(request),
        evaluated_at=now,
        recorded_at=now,
        recorded_by=curve_policy_recorder(),
    )
    return current, policy
