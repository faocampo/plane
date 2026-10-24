# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Minimum current ProductApprover preconditions, without removed-member access."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.db import transaction
from jsonschema import Draft202012Validator, FormatChecker

from plane.db.models import WorkspaceMember
from .models import Product
from .policy_evaluator import evaluate_core_policy
from .policy_types import PolicyEffect
from .prd_policy_context import _build_gate_policy_context
from .prd_read_context import PrdReadUnavailable
from .scope_reopening_policy import reopening_enabled
from .scope_reopening_qualification import require_reopening_qualification
from .scoped_prd_scope import load_locked_scope

SCHEMA_VERSION = "curve.scope-reopening-precondition/v1-candidate"
POLICY_EDITION = "EXPLICIT_SCOPE_REOPENING_PRECONDITION_READ_V1"
ACTION = "CURVE.SCOPE.REOPEN_PRECONDITIONS.READ"
POLICY_DIGEST = "sha256:bff7796e940087af1d1150f142800204fa9c26786ed911c9f449c44a0515916a"
MANIFEST_DIGEST = "sha256:f272f465c5660eff2f8a4f95be1bbac69e162e3c50724c375629e71ab4fcc3de"
DIRECTORY = Path(__file__).parent / "scope_reopening_read_candidate"


def require_read_contract_integrity():
    raw = (DIRECTORY / "manifest-v1.json").read_bytes()
    if "sha256:" + hashlib.sha256(raw).hexdigest() != MANIFEST_DIGEST:
        raise PrdReadUnavailable
    for name, expected in json.loads(raw).items():
        if "sha256:" + hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest() != expected:
            raise PrdReadUnavailable


def read_scope_reopening_preconditions(*, request, workspace_slug, initiative_id):
    try:
        require_read_contract_integrity()
        if not reopening_enabled(workspace_slug):
            raise PrdReadUnavailable
        runtime = getattr(settings, "CURVE_PRD_ACCEPTANCE_RUNTIME", None)
        if not callable(getattr(runtime, "resolve_acl", None)):
            raise PrdReadUnavailable

        latest_acl = None

        def resolve_acl(**kwargs):
            nonlocal latest_acl
            latest_acl = deepcopy(runtime.resolve_acl(**kwargs))
            return deepcopy(latest_acl)

        def authorize(*, after_callbacks=False):
            policy = _build_gate_policy_context(
                request=request,
                workspace_slug=workspace_slug,
                initiative_id=initiative_id,
                action=ACTION,
                acl_resolver=(lambda **_: deepcopy(latest_acl)) if after_callbacks else resolve_acl,
                for_update=True,
                supported_actions=frozenset({ACTION}),
                manifest_digest=POLICY_DIGEST,
            )
            policy["feature_enabled"] = policy["feature_enabled"] and reopening_enabled(workspace_slug)
            if evaluate_core_policy(policy).effect is not PolicyEffect.ALLOW:
                raise PrdReadUnavailable
            assignments = policy["assignment_context"]["gate_assignments"]
            human_ids = {a["principal"]["actor_id"] for a in assignments}
            memberships = list(
                WorkspaceMember.objects.select_for_update()
                .filter(
                    workspace_id=policy["workspace_id"],
                    member_id__in=human_ids,
                    is_active=True,
                    role__in=[5, 15, 20],
                    member__is_active=True,
                    member__is_bot=False,
                )
                .order_by("member_id")
            )
            if len(memberships) != len(human_ids):
                raise PrdReadUnavailable
            return policy

        def snapshot(policy):
            require_reopening_qualification()
            initiative, head, revision, _ = load_locked_scope(
                workspace_id=policy["workspace_id"], initiative_id=initiative_id
            )
            if head is None or initiative.mode != "STANDALONE":
                raise PrdReadUnavailable
            product = Product.objects.find_by_id(
                workspace_id=initiative.workspace_id, record_id=initiative.product_id, for_update=True
            )
            if product is None:
                raise PrdReadUnavailable
            eligible = (
                initiative.state in {"ALIGNING", "PRD_REVIEW", "PLANNING"}
                and product.state == "ACTIVE"
                and initiative.schema_version == "1.1"
                and initiative.workflow_version_id is not None
                and initiative.first_external_resource_at is None
                and initiative.roadmap_item_id is None
            )
            data = dict(
                schema_version=SCHEMA_VERSION,
                policy_edition=POLICY_EDITION,
                workspace_id=str(initiative.workspace_id),
                initiative_id=str(initiative.id),
                initiative_version=initiative.version,
                expected_scope_revision=head.version,
                eligibility="REOPENABLE" if eligible else "STATE_BLOCKED",
                pending_reopening=initiative.pending_scope_reopening_id is not None,
            )
            fence = (
                initiative.id,
                initiative.version,
                initiative.state,
                initiative.paused_from_state,
                initiative.pending_scope_reopening_id,
                initiative.current_prd_checkpoint_id,
                initiative.controlling_prd_decision_id,
                product.id,
                product.version,
                product.state,
                head.id,
                head.current_revision_id,
                head.version,
                revision.membership_digest,
            )
            return data, fence

        with transaction.atomic():
            policy = authorize()
            data, fence = snapshot(policy)
            authorize()
            # Rebuild current DB human/assignment authority after the last ACL
            # callback, without invoking another callback after that fence.
            current_policy = authorize(after_callbacks=True)
            current, current_fence = snapshot(current_policy)
            if current != data or current_fence != fence:
                raise PrdReadUnavailable
            if (
                current_policy["subject"] != policy["subject"]
                or current_policy["assignment_context"] != policy["assignment_context"]
            ):
                raise PrdReadUnavailable
            schema = json.loads((DIRECTORY / "scope-reopening-precondition-v1.schema.json").read_bytes())
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(current)
            return current
    except Exception:
        raise PrdReadUnavailable from None
