# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
from types import SimpleNamespace

import pytest

from plane.curve.item_scope_preparation import SCOPE_SCHEMA, normalize_scope_document
from plane.curve.item_scope_results import prepared_scope_result, validate_scope_result, validate_retained_scope
from plane.curve.services import ReplayResourceUnavailable, operation_response_digest


BODY = {"body": "Synthetic outcome"}
OBJECT = "98000000-0000-4000-8000-000000000001"


def reference():
    raw = normalize_scope_document(BODY)
    return dict(
        object_id=OBJECT,
        digest="sha256:" + hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        media_type="application/json",
        editor_schema_version=SCOPE_SCHEMA,
    )


def record():
    result = prepared_scope_result(reference())
    return SimpleNamespace(
        state="COMPLETED",
        response_status=201,
        response_resource_ref=result,
        response_digest=operation_response_digest(response_status=201, resource_ref=result),
    )


def test_retained_scope_binds_original_body_and_detaches_reference():
    retained = record()
    parsed = validate_retained_scope(retained, payload=BODY)
    assert parsed == reference()
    parsed["object_id"] = "changed"
    assert retained.response_resource_ref["scope_body"]["object_id"] == OBJECT


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "IN_PROGRESS"),
        ("response_status", 200),
        ("response_status", True),
        ("response_digest", "sha256:" + "0" * 64),
    ],
)
def test_incomplete_or_corrupt_receipt_is_unavailable(field, value):
    retained = record()
    setattr(retained, field, value)
    with pytest.raises(ReplayResourceUnavailable):
        validate_retained_scope(retained, payload=BODY)


def test_valid_receipt_for_other_body_is_unavailable():
    with pytest.raises(ReplayResourceUnavailable):
        validate_retained_scope(record(), payload={"body": "Different outcome"})


@pytest.mark.parametrize(
    "field,value",
    [
        ("resource_type", "ROADMAP_ITEM"),
        ("resource_version", True),
        ("resource_version", 2),
        ("resource_id", "98000000-0000-4000-8000-000000000002"),
        ("approval", "APPROVED"),
    ],
)
def test_result_is_closed_and_identity_bound(field, value):
    result = record().response_resource_ref
    result[field] = value
    with pytest.raises(ReplayResourceUnavailable):
        validate_scope_result(result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("size_bytes", 0),
        ("size_bytes", 131073),
        ("size_bytes", True),
        ("media_type", "text/html"),
        ("editor_schema_version", "unknown"),
        ("object_id", OBJECT.replace("-", "")),
        ("grants", {}),
    ],
)
def test_scope_reference_rejects_unsupported_or_injected_fields(field, value):
    result = record().response_resource_ref
    result["scope_body"][field] = value
    with pytest.raises(ReplayResourceUnavailable):
        validate_scope_result(result)


def test_rehashed_receipt_with_wrong_size_cannot_match_original_body():
    retained = record()
    retained.response_resource_ref["scope_body"]["size_bytes"] += 1
    retained.response_digest = operation_response_digest(
        response_status=201, resource_ref=retained.response_resource_ref
    )
    with pytest.raises(ReplayResourceUnavailable):
        validate_retained_scope(retained, payload=BODY)
