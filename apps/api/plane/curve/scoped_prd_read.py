# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Current, protected C2a metadata reads; no capture or command side effects.

The ordinary trusted read adapter authorizes the current artifact/evidence before
native locks are held. Its final ``is_current`` hook must be a local check, never
provider/network work. Exact subject reads are deliberately current-only: current
artifact access cannot authorize an older checkpoint's protected evidence.
"""

from copy import deepcopy

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .config import is_curve_enabled_for_workspace
from .prd_read_context import PrdReadUnavailable, read_prd_review_context
from .prd_read_views import resolve_prd_read_scope
from .scoped_prd_contracts import canonical, metadata_digest, validate_scoped_contract


def scoped_prd_enabled(workspace_slug):
    return (
        is_curve_enabled_for_workspace(workspace_slug)
        and getattr(settings, "CURVE_ENVIRONMENT", "") == "LOCAL"
        and getattr(settings, "CURVE_PRD_COMMANDS_ENABLED", False) is True
        and getattr(settings, "CURVE_SCOPED_PRD_COMMANDS_ENABLED", False) is True
    )


def _require(condition):
    if not condition:
        raise PrdReadUnavailable


def _projection(record, kind):
    """Never sanitize a damaged/open record into an apparently valid closed DTO."""
    value = deepcopy(record)
    validate_scoped_contract(f"scoped-prd-{kind}-v1", value)
    _require(value["digest"] == metadata_digest(value))
    members = value["members"]
    ids = [member["source_issue_id"] for member in members]
    _require(ids == sorted(set(ids)))
    if kind == "observation":
        reviewers = value["reviewers"]
        gates = [reviewer["gate_type"] for reviewer in reviewers]
        _require(gates == sorted({"PRD_APPROVAL", "PLAN_APPROVAL", "CODE_READINESS"}))
        _require(len({reviewer["gate_assignment_id"] for reviewer in reviewers}) == 3)
    return value


class _AuthorizedReadRuntime:
    """Retain only a successful existing read seam's exact local fence inputs."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.scope = None
        self.revision = None

    def observe(self, **kwargs):
        return self.runtime.observe(**kwargs)

    def read_metadata(self, **kwargs):
        return self.runtime.read_metadata(**kwargs)

    def is_current(self, *, scope, snapshot_revision):
        result = self.runtime.is_current(scope=deepcopy(scope), snapshot_revision=snapshot_revision)
        if result is True:
            self.scope = deepcopy(scope)
            self.revision = snapshot_revision
        return result


def _require_scope(context, scope, resolve_scope):
    initiative = context.initiative
    _require(
        str(initiative.workspace_id) == scope["workspace_id"]
        and str(initiative.id) == scope["initiative_id"]
        and type(initiative.version) is int
        and initiative.version == scope["initiative_version"]
        and canonical(resolve_scope()) == canonical(scope)
    )


def _native_read(*, kind, record_id, current, authorization, review_context, resolve_scope):
    # Imported only after ordinary read authorization succeeds. These reads never
    # call the mutation service or infer edition from a row's shape.
    from .scoped_prd_models import ScopedPrdObservation, ScopedPrdSubject
    from .scoped_prd_policy import require_scoped_current

    scope = authorization.scope
    guard_args = {key: scope[key] for key in ("workspace_id", "initiative_id", "actor_id")}
    with transaction.atomic():
        context = require_scoped_current(**guard_args)
        _require_scope(context, scope, resolve_scope)
        fence = deepcopy(context.fence)
        checkpoint_pointer = context.initiative.current_prd_checkpoint_id
        if kind == "observation":
            record = ScopedPrdObservation.objects.find_by_id(
                workspace_id=scope["workspace_id"], record_id=record_id, for_update=True
            )
        elif current:
            checkpoint_id = context.initiative.current_prd_checkpoint_id
            _require(checkpoint_id is not None)
            record = (
                ScopedPrdSubject.objects.for_workspace(scope["workspace_id"])
                .select_for_update()
                .filter(initiative_id=scope["initiative_id"], checkpoint_id=checkpoint_id)
                .first()
            )
        else:
            record = ScopedPrdSubject.objects.find_by_id(
                workspace_id=scope["workspace_id"], record_id=record_id, for_update=True
            )
        _require(record is not None)
        value = _projection(record.as_record(), kind)
        _require(
            value["workspace_id"] == scope["workspace_id"]
            and value["initiative_id"] == scope["initiative_id"]
            and (current or value["id"] == str(record_id))
        )
        if kind == "subject":
            checkpoint = review_context["checkpoint"]
            _require(checkpoint["availability"] == "PRESENT" and checkpoint["metadata"] is not None)
            checkpoint = checkpoint["metadata"]
            _require(
                value["checkpoint_id"] == str(context.initiative.current_prd_checkpoint_id) == checkpoint["id"]
                and all(
                    value[key] == checkpoint[key]
                    for key in ("artifact_version_id", "content_digest", "provider_version", "evidence_snapshot_id")
                )
            )
        guard_args[kind] = record
        context = require_scoped_current(**guard_args)
        _require(context.fence == fence and context.initiative.current_prd_checkpoint_id == checkpoint_pointer)
        _require_scope(context, scope, resolve_scope)
        # The existing read contract makes snapshot_revision cover every mutable
        # subject, assignment and access/classification input. This final local
        # hook must recheck that complete revision without provider/network work.
        # A truthy value is insufficient, and callback changes are rechecked below.
        _require(
            authorization.runtime.is_current(scope=deepcopy(scope), snapshot_revision=authorization.revision) is True
        )
        context = require_scoped_current(**guard_args)
        _require(context.fence == fence and context.initiative.current_prd_checkpoint_id == checkpoint_pointer)
        _require_scope(context, scope, resolve_scope)
        return value


def _read(*, request, workspace_slug, initiative_id, kind, record_id=None, current=False):
    try:
        _require(scoped_prd_enabled(workspace_slug) and getattr(settings, "CURVE_PRD_READ_ENABLED", False) is True)
        runtime = getattr(settings, "CURVE_PRD_READ_RUNTIME", None)
        _require(all(callable(getattr(runtime, name, None)) for name in ("observe", "read_metadata", "is_current")))
        authorization = _AuthorizedReadRuntime(runtime)

        def resolve_scope():
            return resolve_prd_read_scope(request=request, workspace_slug=workspace_slug, initiative_id=initiative_id)

        review_context = read_prd_review_context(
            resolve_scope=resolve_scope,
            runtime=authorization,
            clock=lambda: timezone.now().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        )
        _require(authorization.scope is not None and authorization.revision is not None)
        return _native_read(
            kind=kind,
            record_id=record_id,
            current=current,
            authorization=authorization,
            review_context=review_context,
            resolve_scope=resolve_scope,
        )
    except Exception:
        # No provider/schema/ORM diagnostics or distinction between missing,
        # historical, hidden and temporarily unavailable records escapes.
        raise PrdReadUnavailable from None


def read_scoped_prd_observation(*, request, workspace_slug, initiative_id, observation_id):
    return _read(
        request=request,
        workspace_slug=workspace_slug,
        initiative_id=initiative_id,
        kind="observation",
        record_id=observation_id,
    )


def read_scoped_prd_subject(*, request, workspace_slug, initiative_id, scoped_subject_id=None):
    return _read(
        request=request,
        workspace_slug=workspace_slug,
        initiative_id=initiative_id,
        kind="subject",
        record_id=scoped_subject_id,
        current=scoped_subject_id is None,
    )
