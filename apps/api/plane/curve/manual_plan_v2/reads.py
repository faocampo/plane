# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Protected current/history reads and separately authorized minimal status."""

from dataclasses import dataclass
from django.db import transaction

from .contracts import ManualPlanError, POLICY_EDITION, require, validate
from .policy import (
    authority_fence,
    bind_inputs,
    capture_authorized,
    load_native,
    require_edition,
    require_enabled,
    _principals,
)
from .repository import load_head, load_revision
from .synthetic import SyntheticManualPlanResolverV2
from .validation import canonical_json


@dataclass(frozen=True)
class ReadResult:
    data: dict
    initiative_version: int


def _status(context, subject, head, revision, resolver):
    catalog, _, grants, file_fence = resolver.authorize(
        workspace_id=context.workspace.id,
        initiative_id=context.initiative.id,
        principals=_principals(context),
        action="READ_STATUS",
    )
    status = "ABSENT"
    if head is not None:
        status = "STALE"
        plan = catalog["plans"].get(revision.payload["definition_ref"]["object_id"])
        if plan is not None and plan["identity"] == revision.original_input_identity:
            # A metadata-only check: status does not read or grant old body access.
            from types import SimpleNamespace

            try:
                bind_inputs(context, subject, SimpleNamespace(identity=plan["identity"], facts=plan["facts"]))
                status = "CURRENT"
            except ManualPlanError:
                pass
    data = dict(
        schema_version="curve.manual-plan-draft.status/v2-candidate",
        policy_edition=POLICY_EDITION,
        workspace_id=str(context.workspace.id),
        initiative_id=str(context.initiative.id),
        initiative_version=context.initiative.version,
        draft_status=status,
        current_revision_id=str(revision.id) if revision is not None else None,
        expected_draft_revision=head.version if head is not None else 0,
    )
    validate("manual-plan-draft-status-v2", data)
    return data, (catalog["generation"], canonical_json(list(grants)), file_fence)


def read_manual_plan(*, request, workspace_slug, initiative_id, action, revision_id=None):
    try:
        require(action in {"READ_CURRENT", "READ_REVISION", "READ_STATUS"})
        require((revision_id is not None) == (action == "READ_REVISION"))
        require(not request.query_params)
        require_enabled(request, workspace_slug)
        with SyntheticManualPlanResolverV2.from_settings() as resolver, transaction.atomic():
            require_edition()
            context, subject = load_native(request=request, workspace_slug=workspace_slug, initiative_id=initiative_id)
            initial_version = context.initiative.version
            head, current = load_head(context.initiative)
            if action == "READ_STATUS":
                data, fence = _status(context, subject, head, current, resolver)
            else:
                require(head is not None)
                revision = load_revision(context.initiative, head, revision_id) if revision_id is not None else current
                captured = capture_authorized(
                    context=context,
                    subject=subject,
                    resolver=resolver,
                    definition_ref=revision.payload["definition_ref"],
                    action=action,
                )
                require(captured.identity == revision.original_input_identity)
                data, fence = revision.as_record(), authority_fence(context, subject, captured)
            head_fence = None if head is None else (head.id, head.version, head.current_revision_id)
            fresh, fresh_subject = load_native(
                request=request, workspace_slug=workspace_slug, initiative_id=initiative_id
            )
            final_head, final_current = load_head(fresh.initiative)
            require(fresh.initiative.version == initial_version and fresh.fence == context.fence)
            require(
                (None if final_head is None else (final_head.id, final_head.version, final_head.current_revision_id))
                == head_fence
            )
            if action == "READ_STATUS":
                final_data, final_fence = _status(fresh, fresh_subject, final_head, final_current, resolver)
                require(final_data == data and final_fence == fence)
                resolver.recheck((final_fence[2],))
            else:
                final = capture_authorized(
                    context=fresh,
                    subject=fresh_subject,
                    resolver=resolver,
                    definition_ref=revision.payload["definition_ref"],
                    action=action,
                )
                require(
                    final.identity == revision.original_input_identity
                    and authority_fence(fresh, fresh_subject, final) == fence
                )
                resolver.recheck(final.file_fence)
            return ReadResult(data, initial_version)
    except ManualPlanError:
        raise
    except Exception:
        raise ManualPlanError("UNAVAILABLE") from None
