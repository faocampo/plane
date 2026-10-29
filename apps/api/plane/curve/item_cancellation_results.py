# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Closed terminal reservation for an original, not-yet-accepted creation identity."""

from uuid import UUID

from plane.curve.services import (
    canonical_json_bytes,
    idempotency_key_digest,
    operation_response_digest,
    sha256_digest,
    ReplayResourceUnavailable,
)


def cancellation_identity(*, workspace_id, product_id, roadmap_id, actor_id, command_key):
    try:
        values = [UUID(str(value)) for value in (workspace_id, product_id, roadmap_id, actor_id)]
        if str(UUID(command_key)) != command_key:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ReplayResourceUnavailable from None
    workspace_id, product_id, roadmap_id, actor_id = map(str, values)
    key_digest = idempotency_key_digest(command_key)
    return {
        "principal_scope": f"HUMAN:{actor_id}",
        "command_scope": f"CURVE.ITEM.CREATE_ROADMAP_ITEM_INITIATIVE:{product_id}:{roadmap_id}",
        "key_digest": key_digest,
        "request_digest": sha256_digest(
            canonical_json_bytes(
                {
                    "action": "CANCEL_ITEM_CREATION_ATTEMPT",
                    "workspace_id": workspace_id,
                    "product_id": product_id,
                    "roadmap_id": roadmap_id,
                    "actor_id": actor_id,
                    "key_digest": key_digest,
                }
            )
        ),
    }


def cancellation_reference(record_id):
    return {
        "resource_type": "ROADMAP_ITEM_CREATION_CANCELLATION",
        "resource_id": str(UUID(str(record_id))),
        "resource_version": 1,
    }


def validate_cancellation(record, *, workspace_id, identity):
    if type(identity) is not dict or set(identity) != {
        "principal_scope",
        "command_scope",
        "key_digest",
        "request_digest",
    }:
        raise ReplayResourceUnavailable
    ref = record.response_resource_ref
    if (
        str(record.workspace_id) != str(workspace_id)
        or any(getattr(record, key) != value for key, value in identity.items())
        or record.state != "FAILED_TERMINAL"
        or type(record.response_status) is not int
        or record.response_status != 409
        or type(ref) is not dict
        or set(ref) != {"resource_type", "resource_id", "resource_version"}
        or type(ref.get("resource_version")) is not int
        or ref != cancellation_reference(record.id)
        or record.completed_at is None
        or record.external_effect_refs != []
        or record.response_digest != operation_response_digest(response_status=409, resource_ref=ref)
    ):
        raise ReplayResourceUnavailable
    return {"state": "CANCELLED"}
