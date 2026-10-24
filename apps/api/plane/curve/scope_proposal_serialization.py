# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from .services import canonical_json_bytes, sha256_digest


def serialize_scope_item(item):
    return {
        "association_id": str(item.association_id),
        "association_version": item.association_version,
        "provider_installation_id": str(item.provider_installation_id),
        "source_project_id": str(item.source_project_id),
        "source_issue_id": str(item.source_issue_id),
        "purpose": item.purpose,
        "source_observed_at": item.source_observed_at.isoformat(),
        "source_version": item.source_version,
        "source_fingerprint": item.source_fingerprint,
    }


def scope_membership_digest(items):
    return sha256_digest(
        canonical_json_bytes(sorted(items, key=lambda item: (item["source_issue_id"], item["purpose"])))
    )


def serialize_scope_revision(revision, items):
    from .scope_proposal_models import POLICY_EDITION
    from .scope_reopening_contracts import REVISION_EDITION

    if revision.policy_edition == POLICY_EDITION:
        schema_version = "1.0"
    elif revision.policy_edition == REVISION_EDITION:
        schema_version = "2.0"
    else:
        raise ValueError("Unknown scope revision edition")
    return {
        "schema_version": schema_version,
        "id": str(revision.id),
        "workspace_id": str(revision.workspace_id),
        "proposal_id": str(revision.proposal_id),
        "initiative_id": str(revision.initiative_id),
        "product_id": str(revision.product_id),
        "version": revision.version,
        "initiative_version": revision.initiative_version,
        "predecessor_id": str(revision.predecessor_id) if revision.predecessor_id else None,
        "item_count": revision.item_count,
        "delivery_count": revision.delivery_count,
        "membership_digest": revision.membership_digest,
        "created_by": str(revision.created_by),
        "recorded_at": revision.recorded_at.isoformat(),
        "policy_edition": revision.policy_edition,
        "command_receipt_id": str(revision.command_receipt_id),
        "controlling": False,
        "items": sorted([serialize_scope_item(item) for item in items], key=lambda item: item["source_issue_id"]),
    }
