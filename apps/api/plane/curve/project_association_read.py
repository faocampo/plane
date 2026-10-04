# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Closed advisory native association discovery; no policy or source writes."""

import hashlib
import json
from pathlib import Path

from django.db import transaction
from django.utils import timezone
from jsonschema import Draft202012Validator, FormatChecker

from .models import ProductState, ProjectAssociation
from .project_association_policy import READ, _installation, _load_context, _policy_integrity
from .project_association_services import _uuid
from .scope_reopening_qualification import require_reopening_qualification

SCHEMA_VERSION = "curve.project-association-precondition/v1-candidate"
POLICY_EDITION = "LOCAL_NATIVE_PROJECT_ASSOCIATION_PRECONDITION_READ_V1"
DIRECTORY = Path(__file__).parent / "project_association_read_candidate"
MANIFEST_DIGEST = "sha256:0e2ff6eac36ae52e32e87ae75163b0ba08aa9d27e6c0da87a1c085e171201f68"


class AssociationReadUnavailable(Exception):
    pass


def require_read_contract_integrity():
    raw = (DIRECTORY / "manifest-v1.json").read_bytes()
    if "sha256:" + hashlib.sha256(raw).hexdigest() != MANIFEST_DIGEST:
        raise AssociationReadUnavailable
    manifest = json.loads(raw)
    if set(manifest) != {"policy-v1.json", "project-association-precondition-v1.schema.json"}:
        raise AssociationReadUnavailable
    for name, expected in manifest.items():
        if "sha256:" + hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest() != expected:
            raise AssociationReadUnavailable


def _snapshot(context):
    # The common Workspace lock also serializes supported CREATE/END commands,
    # including the absent-row case that cannot itself be row-locked.
    associations = list(
        ProjectAssociation.objects.select_for_update().filter(
            workspace_id=context.workspace.id,
            provider_installation_id=context.installation_id,
            source_project_id=context.project.id,
            state="ACTIVE",
        )[:2]
    )
    if len(associations) > 1:
        raise AssociationReadUnavailable
    association = associations[0] if associations else None
    availability = "AVAILABLE"
    association_id = None
    if association is not None:
        if association.product_id == context.product.id:
            availability = "ASSOCIATED_WITH_SELECTED_PRODUCT"
            association_id = str(association.id)
        else:
            availability = "ASSOCIATED_ELSEWHERE"
    # The private fence is never serialized; conflicts expose neither target ID.
    fence = (
        None
        if association is None
        else (association.id, association.product_id, association.version, association.state)
    )
    return availability, association_id, fence


def read_project_association_preconditions(*, request, workspace_slug, product_id, source_project_id):
    try:
        require_read_contract_integrity()
        _policy_integrity()
        product_id = _uuid(product_id, "product_id")
        source_project_id = _uuid(source_project_id, "source_project_id")

        def authorize():
            _, context, reasons = _load_context(
                request=request,
                workspace_slug=workspace_slug,
                product_id=product_id,
                source_project_id=source_project_id,
                provider_installation_id=_installation(),
                action=READ,
            )
            if (
                reasons != ("ALLOW",)
                or context is None
                or context.product.state != ProductState.ACTIVE
                or context.project.archived_at is not None
            ):
                raise AssociationReadUnavailable
            return context

        with transaction.atomic():
            context = authorize()
            authority_fence = context.fence()
            initial = _snapshot(context)
            require_reopening_qualification()
            # Rebuild current server-owned human/membership/Product/source state
            # after the snapshot. A stale request.user or prior GET is no grant.
            current = authorize()
            result = _snapshot(current)
            if current.fence() != authority_fence or result != initial:
                raise AssociationReadUnavailable
            data = dict(
                schema_version=SCHEMA_VERSION,
                policy_edition=POLICY_EDITION,
                workspace_id=str(current.workspace.id),
                product_id=str(current.product.id),
                product_version=current.product.version,
                provider_installation_id=str(current.installation_id),
                source_project_id=str(current.project.id),
                availability=result[0],
                association_id=result[1],
                observed_at=timezone.now().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            )
            schema = json.loads((DIRECTORY / "project-association-precondition-v1.schema.json").read_bytes())
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(data)
            return data
    except Exception:
        # A fixed read denial never reveals existence, authority, drift or input.
        raise AssociationReadUnavailable from None
