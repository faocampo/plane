# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Closed scope-preparation receipt validation; current access is checked separately."""

from plane.curve.item_creation_input import ItemCreationInputError
from plane.curve.item_creation_material import normalize_scope_reference
from plane.curve.item_scope_preparation import SCOPE_SCHEMA, normalize_scope_document
from plane.curve.services import ReplayResourceUnavailable, operation_response_digest
import hashlib


def prepared_scope_result(reference):
    result = {
        "resource_type": "PREPARED_ITEM_SCOPE",
        "resource_id": reference["object_id"],
        "resource_version": 1,
        "scope_body": dict(reference),
    }
    validate_scope_result(result)
    return result


def validate_scope_result(result):
    if type(result) is not dict or set(result) != {"resource_type", "resource_id", "resource_version", "scope_body"}:
        raise ReplayResourceUnavailable
    try:
        ref = normalize_scope_reference(result["scope_body"])
    except ItemCreationInputError as error:
        raise ReplayResourceUnavailable from error
    if (
        result["resource_type"] != "PREPARED_ITEM_SCOPE"
        or type(result["resource_version"]) is not int
        or result["resource_version"] != 1
        or result["scope_body"] != ref
        or result["resource_id"] != ref["object_id"]
        or ref["media_type"] != "application/json"
        or ref["editor_schema_version"] != SCOPE_SCHEMA
        or not 1 <= ref["size_bytes"] <= 128 * 1024
    ):
        raise ReplayResourceUnavailable
    return ref


def validate_retained_scope(record, *, payload):
    """Bind a completed receipt to original normalized bytes, without granting access.

    The service must first match the actor/scoped idempotency key and request
    digest, then resolve current owner/membership facts and capture this exact
    reference under a protected-material lease through transaction commit.
    """
    ref = validate_scope_result(record.response_resource_ref)
    raw = normalize_scope_document(payload)
    if (
        record.state != "COMPLETED"
        or type(record.response_status) is not int
        or record.response_status != 201
        or record.response_digest
        != operation_response_digest(response_status=201, resource_ref=record.response_resource_ref)
        or ref["digest"] != "sha256:" + hashlib.sha256(raw).hexdigest()
        or ref["size_bytes"] != len(raw)
    ):
        raise ReplayResourceUnavailable
    return ref
