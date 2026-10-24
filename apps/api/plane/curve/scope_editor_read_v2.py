# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Metadata-only scope discovery requiring the exact manual and read successors.

Native task visibility is not a metadata grant. Every historical revision is
bounded and checked; no task body or write authority is returned.
"""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

MAX_REVISIONS = 1000
MAX_SAFE_INTEGER = 9007199254740991
SCHEMA_VERSION = "curve.scope-editor-precondition/v2-candidate"
POLICY_EDITION = "LOCAL_SCOPE_EDITOR_PRECONDITION_RECONSTRUCTION_V2"
DIRECTORY = Path(__file__).parent / "scope_editor_read_v2_candidate"
MANIFEST_DIGEST = "sha256:8957c74f0999aa101021f96afe7e91090308469c977d704709f64418dec20209"
HEAD_FIELDS = ("id", "workspace_id", "initiative_id", "product_id", "version", "current_revision_id")
REVISION_FIELDS = (
    "id",
    "workspace_id",
    "initiative_id",
    "product_id",
    "proposal_id",
    "version",
    "initiative_version",
    "predecessor_id",
    "item_count",
    "delivery_count",
    "membership_digest",
    "created_by",
    "recorded_at",
    "policy_edition",
    "command_receipt_id",
)
REVISION_EDITIONS = frozenset(
    {
        "EXPLICIT_EXISTING_WORK_SCOPE_PROPOSAL_V1",
        "REOPENED_EXISTING_WORK_SCOPE_PROPOSAL_V1",
    }
)
CONTRACT_FILES = frozenset(
    {
        "openapi-v2.json",
        "policy-v2.json",
        "scope-editor-error-v2.schema.json",
        "scope-editor-precondition-v2.schema.json",
    }
)


class ScopeEditorUnavailable(Exception):
    """Every unavailable read maps to the same public response."""


def _require(condition):
    if not condition:
        raise ScopeEditorUnavailable


def _integer(value, minimum=1, maximum=MAX_SAFE_INTEGER):
    return type(value) is int and minimum <= value <= maximum


def _uuid(value):
    result = uuid.UUID(str(value))
    _require(str(result) == str(value))
    return result


def require_contract_integrity():
    raw = (DIRECTORY / "manifest-v2.json").read_bytes()
    _require("sha256:" + hashlib.sha256(raw).hexdigest() == MANIFEST_DIGEST)
    manifest = json.loads(raw)
    _require(type(manifest) is dict and set(manifest) == CONTRACT_FILES)
    for name, expected in manifest.items():
        _require("sha256:" + hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest() == expected)


@dataclass(frozen=True)
class ScopeSnapshot:
    status: str
    version: int
    fence: tuple


def validate_lineage(initiative, heads, revisions):
    """Validate all bounded revision metadata, without reading native tasks.

    Inputs are database value dictionaries. The caller fetches no more than
    1,001 rows before any broad catalog or current-member integrity work.
    Initiative version gaps are expected when other commands have occurred.
    """
    _require(_integer(initiative.version))
    _require(len(heads) <= 1 and len(revisions) <= MAX_REVISIONS)
    _require(all(isinstance(getattr(initiative, key), uuid.UUID) for key in ("id", "workspace_id", "product_id")))
    if not heads:
        _require(not revisions)
        return ScopeSnapshot("ABSENT", 0, ())
    head = heads[0]
    _require(set(head) == set(HEAD_FIELDS))
    _require(all(isinstance(head[key], uuid.UUID) for key in HEAD_FIELDS if key != "version"))
    _require(
        head["workspace_id"] == initiative.workspace_id
        and head["initiative_id"] == initiative.id
        and head["product_id"] == initiative.product_id
        and _integer(head["version"], maximum=MAX_REVISIONS)
        and len(revisions) == head["version"]
    )
    previous = None
    seen = set()
    for sequence, revision in enumerate(revisions, start=1):
        _require(set(revision) == set(REVISION_FIELDS))
        _require(
            all(
                isinstance(revision[key], uuid.UUID)
                for key in (
                    "id",
                    "workspace_id",
                    "initiative_id",
                    "product_id",
                    "proposal_id",
                    "created_by",
                    "command_receipt_id",
                )
            )
        )
        _require(
            revision["workspace_id"] == initiative.workspace_id
            and revision["initiative_id"] == initiative.id
            and revision["product_id"] == initiative.product_id
            and revision["proposal_id"] == head["id"]
            and _integer(revision["version"], maximum=MAX_REVISIONS)
            and revision["version"] == sequence
            and _integer(revision["initiative_version"], minimum=sequence + 1, maximum=initiative.version)
            and revision["policy_edition"] in REVISION_EDITIONS
            and _integer(revision["item_count"], minimum=0, maximum=100)
            and _integer(revision["delivery_count"], minimum=0, maximum=revision["item_count"])
            and isinstance(revision["membership_digest"], str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", revision["membership_digest"]) is not None
            and isinstance(revision["recorded_at"], datetime)
            and revision["recorded_at"].utcoffset() is not None
            and revision["id"] not in seen
        )
        if previous is None:
            _require(revision["predecessor_id"] is None)
        else:
            _require(
                revision["predecessor_id"] == previous["id"]
                and revision["initiative_version"] > previous["initiative_version"]
                and revision["recorded_at"] >= previous["recorded_at"]
            )
        previous = revision
        seen.add(revision["id"])
    _require(previous is not None and previous["id"] == head["current_revision_id"])
    fence = (
        tuple(head[key] for key in HEAD_FIELDS),
        tuple(tuple(row[key] for key in REVISION_FIELDS) for row in revisions),
    )
    return ScopeSnapshot("PRESENT", head["version"], fence)


def _metadata_snapshot(initiative):
    from django.db.models import Q
    from .scope_proposal_models import ScopeProposal, ScopeProposalRevision

    # Do not workspace-filter corruption into apparently intact absence.
    heads = list(
        ScopeProposal.objects.select_for_update()
        .filter(
            initiative_id=initiative.id,
        )
        .values(*HEAD_FIELDS)[:2]
    )
    _require(len(heads) <= 1)
    related = Q(initiative_id=initiative.id)
    if heads:
        related |= Q(proposal_id=heads[0]["id"]) | Q(id=heads[0]["current_revision_id"])
    revisions = list(
        ScopeProposalRevision.objects.select_for_update()
        .filter(related)
        .order_by("version", "id")
        .values(*REVISION_FIELDS)[: MAX_REVISIONS + 1]
    )
    return validate_lineage(initiative, heads, revisions)


def _authorize(*, request, workspace_slug, initiative_id):
    from django.conf import settings
    from plane.db.models import User, Workspace, WorkspaceMember
    from .config import is_curve_enabled_for_workspace
    from .models import Initiative, Product

    _require(
        getattr(settings, "CURVE_SCOPE_EDITOR_READ_V2_ENABLED", False) is True
        and getattr(settings, "CURVE_ENVIRONMENT", None) == "LOCAL"
        and is_curve_enabled_for_workspace(workspace_slug)
        and getattr(request.user, "is_authenticated", False)
    )
    installation = _uuid(getattr(settings, "CURVE_LOCAL_PLANE_INSTALLATION_ID", None))
    workspace = Workspace.objects.select_for_update().filter(slug=workspace_slug).first()
    _require(workspace is not None)
    user = User.objects.select_for_update().filter(id=request.user.id, is_active=True, is_bot=False).first()
    memberships = list(
        WorkspaceMember.objects.select_for_update().filter(
            workspace_id=workspace.id,
            member_id=request.user.id,
            is_active=True,
            role__in=[5, 15, 20],
        )[:2]
    )
    _require(user is not None and len(memberships) == 1)
    membership = memberships[0]
    initiative = Initiative.objects.find_by_id(workspace_id=workspace.id, record_id=initiative_id, for_update=True)
    _require(
        initiative is not None
        and initiative.mode == "STANDALONE"
        and initiative.state == "DRAFT"
        and (initiative.creator_user_id == user.id or membership.role == 20)
    )
    product = Product.objects.find_by_id(workspace_id=workspace.id, record_id=initiative.product_id, for_update=True)
    _require(product is not None and product.state == "ACTIVE")
    fence = (
        workspace.id,
        workspace.slug,
        workspace.owner_id,
        workspace.updated_at,
        user.id,
        user.is_active,
        user.is_bot,
        user.updated_at,
        membership.id,
        membership.role,
        membership.is_active,
        membership.updated_at,
        initiative.id,
        initiative.workspace_id,
        initiative.product_id,
        initiative.mode,
        initiative.state,
        initiative.creator_user_id,
        initiative.version,
        initiative.updated_at,
        initiative.pending_scope_reopening_id,
        product.id,
        product.state,
        product.version,
        product.owner_user_id,
        product.updated_at,
        installation,
    )
    return initiative, fence


def _require_qualified_successor():
    # This distinct reader requires its own exact proof after the manual writer;
    # the predecessor seal alone cannot authorize the added runtime sources.
    from .scope_reopening_qualification import require_scope_editor_read_v2_qualification

    require_scope_editor_read_v2_qualification()


def _verify_current_scope(initiative):
    from .scoped_prd_scope import load_locked_scope

    # Stored metadata integrity only: this does not consult old task visibility
    # or write an audit/policy/operation row. The lineage bound was already checked.
    load_locked_scope(workspace_id=initiative.workspace_id, initiative_id=initiative.id)


def read_scope_editor_preconditions(*, request, workspace_slug, initiative_id):
    from django.db import transaction
    from jsonschema import Draft202012Validator, FormatChecker

    try:
        _require(not request.query_params)
        require_contract_integrity()
        initiative_id = _uuid(initiative_id)
        with transaction.atomic():
            initiative, authority = _authorize(
                request=request, workspace_slug=workspace_slug, initiative_id=initiative_id
            )
            initial = _metadata_snapshot(initiative)
            _require_qualified_successor()
            _verify_current_scope(initiative)
            current, final_authority = _authorize(
                request=request, workspace_slug=workspace_slug, initiative_id=initiative_id
            )
            final = _metadata_snapshot(current)
            _require(authority == final_authority and initial == final)
            data = dict(
                schema_version=SCHEMA_VERSION,
                policy_edition=POLICY_EDITION,
                workspace_id=str(current.workspace_id),
                product_id=str(current.product_id),
                initiative_id=str(current.id),
                initiative_version=current.version,
                scope_status=final.status,
                expected_scope_revision=final.version,
            )
            schema = json.loads((DIRECTORY / "scope-editor-precondition-v2.schema.json").read_bytes())
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(data)
            return data
    except Exception:
        raise ScopeEditorUnavailable from None
