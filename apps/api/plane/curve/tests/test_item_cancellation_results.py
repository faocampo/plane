# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest

from plane.curve.item_cancellation_results import cancellation_identity, cancellation_reference, validate_cancellation
from plane.curve.services import ReplayResourceUnavailable, operation_response_digest


def uid(n):
    return UUID(f"99000000-0000-4000-8000-{n:012d}")


def identity(**changes):
    data = dict(workspace_id=uid(1), product_id=uid(2), roadmap_id=uid(3), actor_id=uid(4), command_key=str(uid(5)))
    data.update(changes)
    return cancellation_identity(**data)


def record():
    ref = cancellation_reference(uid(6))
    return SimpleNamespace(
        id=uid(6),
        workspace_id=uid(1),
        **identity(),
        state="FAILED_TERMINAL",
        response_status=409,
        response_resource_ref=ref,
        response_digest=operation_response_digest(response_status=409, resource_ref=ref),
        completed_at="synthetic-present",
        external_effect_refs=[],
    )


def test_exact_terminal_marker_proves_cancellation_without_draft_data():
    assert validate_cancellation(record(), workspace_id=uid(1), identity=identity()) == {"state": "CANCELLED"}
    assert identity()["principal_scope"] == f"HUMAN:{uid(4)}"
    assert identity()["command_scope"] == f"CURVE.ITEM.CREATE_ROADMAP_ITEM_INITIATIVE:{uid(2)}:{uid(3)}"


@pytest.mark.parametrize("field", ["workspace_id", "product_id", "roadmap_id", "actor_id", "command_key"])
def test_identity_binds_every_scope_and_original_key(field):
    changed = identity(**{field: str(uid(9))})
    assert changed["request_digest"] != identity()["request_digest"]
    with pytest.raises(ReplayResourceUnavailable):
        validate_cancellation(record(), workspace_id=uid(1), identity=changed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "COMPLETED"),
        ("state", "IN_PROGRESS"),
        ("response_status", 200),
        ("response_status", True),
        ("response_digest", "sha256:" + "0" * 64),
        ("completed_at", None),
        ("external_effect_refs", [{"unexpected": True}]),
        ("workspace_id", uid(9)),
        ("request_digest", "sha256:" + "0" * 64),
    ],
)
def test_invalid_terminal_evidence_is_rejected(field, value):
    value_record = record()
    setattr(value_record, field, value)
    with pytest.raises(ReplayResourceUnavailable):
        validate_cancellation(value_record, workspace_id=uid(1), identity=identity())


@pytest.mark.parametrize("change", ["extra", "other_id", "boolean_version", "other_type"])
def test_reference_is_closed_and_bound_to_its_receipt_even_with_recomputed_digest(change):
    value = record()
    ref = deepcopy(value.response_resource_ref)
    if change == "extra":
        ref["body"] = "synthetic draft"
    elif change == "other_id":
        ref["resource_id"] = str(uid(9))
    elif change == "boolean_version":
        ref["resource_version"] = True
    else:
        ref["resource_type"] = "ROADMAP_ITEM"
    value.response_resource_ref = ref
    value.response_digest = operation_response_digest(response_status=409, resource_ref=ref)
    with pytest.raises(ReplayResourceUnavailable):
        validate_cancellation(value, workspace_id=uid(1), identity=identity())


def test_missing_expected_identity_cannot_skip_scope_checks():
    with pytest.raises(ReplayResourceUnavailable):
        validate_cancellation(record(), workspace_id=uid(1), identity={})


@pytest.mark.parametrize("key", ["", None, "synthetic", str(uid(5)).upper().replace("99000000", "AA000000")])
def test_only_canonical_uuid_locators_are_accepted(key):
    with pytest.raises(ReplayResourceUnavailable):
        identity(command_key=key)


def test_cancellation_event_contains_only_bound_scope_and_marker():
    from plane.curve.item_cancellation_events import build_item_cancellation_event

    event = build_item_cancellation_event(workspace_id=uid(1), product_id=uid(2), roadmap_id=uid(3), record_id=uid(6))
    assert event == {
        "schema_version": "1.0",
        "workspace_id": str(uid(1)),
        "product_id": str(uid(2)),
        "roadmap_id": str(uid(3)),
        "result": cancellation_reference(uid(6)),
    }


@pytest.mark.parametrize("field", ["workspace_id", "product_id", "roadmap_id", "record_id"])
def test_cancellation_event_rejects_invalid_identifiers(field):
    from jsonschema import ValidationError
    from plane.curve.item_cancellation_events import build_item_cancellation_event

    args = dict(workspace_id=uid(1), product_id=uid(2), roadmap_id=uid(3), record_id=uid(6))
    args[field] = "invalid"
    with pytest.raises((ValueError, ValidationError)):
        build_item_cancellation_event(**args)
