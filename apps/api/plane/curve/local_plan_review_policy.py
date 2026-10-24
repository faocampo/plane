# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Exact policy evidence for local Technical-review commands with fresh native authority."""

import hashlib
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from .config import curve_policy_recorder
from .local_new_work_policy import policy_identity
from .local_plan_authority import require_local_plan_authority
from .manual_plan_v3.policy import _observation_json
from .models import PolicyDecision
from .policy_services import _next_policy_sequence, correlation_id_for_request
from .prd_commands import PrdCommandError
from .services import canonical_json_bytes, sha256_digest

POLICY_KEY = "CURVE_LOCAL_PLAN_REVIEW_POLICY"
POLICY_DIGEST = "sha256:09b9ca473a2fb43d90b9e9438c0e22d4bdebd65a7eb769113ef202d0bd45dcfe"


def record_review_authorization(
    *, request, workspace_slug, initiative_id, request_digest, action, replay=False, **subject
):
    if not transaction.get_connection().in_atomic_block:
        raise PrdCommandError("LOCAL_PLAN_TRANSACTION_REQUIRED", 503)
    path = Path(__file__).parent / "two_stage_review/local-plan-review-policy-v1.json"
    if path.is_symlink() or "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != POLICY_DIGEST:
        raise PrdCommandError("LOCAL_PLAN_POLICY_UNAVAILABLE", 503)
    if action not in {"SUBMIT", "APPROVE", "REQUEST_CHANGES"}:
        raise PrdCommandError("LOCAL_PLAN_REVIEW_UNAVAILABLE", 404)
    authority = require_local_plan_authority(
        request=request,
        workspace_slug=workspace_slug,
        initiative_id=initiative_id,
        action="READ" if replay else action,
        **({} if replay else subject),
    )
    context = authority.context
    # A replay reports retained outcome only; it never grants a new decision.
    if replay:
        required_actor = (
            str(context.initiative.creator_user_id)
            if action == "SUBMIT"
            else next(row["approver_user_id"] for row in context.reviewers if row["gate_type"] == "PLAN_APPROVAL")
        )
        if str(context.actor_id) != required_actor:
            raise PrdCommandError("LOCAL_PLAN_REVIEW_UNAVAILABLE", 404)
    policy_version, policy_digest = policy_identity(context, POLICY_KEY, POLICY_DIGEST)
    actor = dict(actor_type="HUMAN", actor_id=str(context.actor_id))
    now = timezone.now()
    decision = PolicyDecision.objects.create(
        workspace_id=context.workspace.id,
        sequence=_next_policy_sequence(
            workspace_id=context.workspace.id, resource_type="INITIATIVE", resource_id=context.initiative.id
        ),
        action=f"CURVE.LOCAL_PLAN.{action}",
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
            canonical_json_bytes(dict(request_digest=request_digest, native_fence=_observation_json(authority.fence)))
        ),
        normalized_classification="INTERNAL",
        permitted_projection=["LOCAL_PLAN_REVIEW_METADATA_V1"],
        correlation_id=correlation_id_for_request(request),
        evaluated_at=now,
        recorded_at=now,
        recorded_by=curve_policy_recorder(),
    )
    return authority, decision
