# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Fresh native access for local PRD sources, evaluated inside caller-owned locks.

This is the local upload command's preflight/revalidation boundary. Its result
must be recorded by the consuming command's policy/audit transaction; it is not
an HTTP capability or a reusable permission grant. Protected file I/O is separate.
"""

from dataclasses import dataclass

from django.conf import settings
from django.db import transaction

from plane.db.models import Workspace
from .config import is_curve_enabled_for_workspace
from .local_document_models import LocalPrdSource
from .local_document_record import validate_local_document_record
from .prd_commands import PrdCommandError
from .local_initiative_context import require_local_initiative_context
from .scope_reopening_qualification import require_reopening_qualification


@dataclass(frozen=True, repr=False)
class LocalDocumentAuthority:
    context: object
    current_source: object
    action: str
    fence: tuple


def _require(condition, code="LOCAL_PRD_UNAVAILABLE", status=404):
    if not condition:
        raise PrdCommandError(code, status)


def require_local_document_authority(*, request, workspace_slug, initiative_id, action, expected_version=None):
    _require(transaction.get_connection().in_atomic_block, "LOCAL_PRD_TRANSACTION_REQUIRED", 503)
    _require(action in {"UPLOAD", "READ"})
    _require(
        getattr(settings, "CURVE_LOCAL_PRD_ENABLED", False) is True
        and getattr(settings, "CURVE_ENVIRONMENT", None) == "LOCAL"
        and is_curve_enabled_for_workspace(workspace_slug)
    )
    user = getattr(request, "user", None)
    _require(user is not None and user.is_authenticated and user.is_active and not getattr(user, "is_bot", True))
    require_reopening_qualification()
    workspace = Workspace.objects.select_for_update().filter(slug=workspace_slug).first()
    _require(workspace is not None)
    context = require_local_initiative_context(workspace_id=workspace.id, initiative_id=initiative_id, actor_id=user.id)
    initiative = context.initiative
    _require(initiative.schema_version == "1.2" and initiative.pending_scope_reopening_id is None)
    creator = initiative.creator_user_id == context.actor_id
    approver = str(context.actor_id) in {value["approver_user_id"] for value in context.reviewers}
    if action == "UPLOAD":
        _require(creator)
        _require(initiative.state in {"DRAFT", "ALIGNING"}, "LOCAL_PRD_REVIEW_IN_PROGRESS", 409)
        _require(type(expected_version) is int and expected_version > 0, "LOCAL_PRD_VERSION_REQUIRED", 428)
    else:
        _require(creator or approver)
    if expected_version is not None:
        _require(
            type(expected_version) is int and expected_version == initiative.version, "LOCAL_PRD_VERSION_CHANGED", 412
        )
    current = (
        LocalPrdSource.objects.select_for_update()
        .filter(workspace_id=workspace.id, initiative_id=initiative.id)
        .order_by("-version")
        .first()
    )
    if current is not None:
        current.validate_metadata()
        validate_local_document_record(current.payload)
    fence = (
        str(workspace.id),
        str(initiative.id),
        initiative.version,
        initiative.state,
        str(context.actor_id),
        str(initiative.creator_user_id),
        (str(context.head.id), str(context.revision.id), context.revision.version, context.revision.membership_digest)
        if context.head is not None
        else None,
        context.fence,
        (str(current.id), current.version, current.digest) if current else None,
    )
    return LocalDocumentAuthority(context, current, action, fence)
