# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID
import pytest

from plane.curve.item_creation_results import pair_reference, validate_pair_reference, validate_retained_creation
from plane.curve.item_creation_events import build_item_creation_event
from plane.curve.services import ReplayResourceUnavailable, operation_response_digest

ITEM = "94000000-0000-4000-8000-000000000001"
INITIATIVE = "94000000-0000-4000-8000-000000000002"
ACTOR = "94000000-0000-4000-8000-000000000003"


def result():
    return pair_reference(item_id=ITEM, initiative_id=INITIATIVE)


def record():
    ref = result()
    return SimpleNamespace(
        state="COMPLETED",
        response_status=201,
        response_resource_ref=ref,
        response_digest=operation_response_digest(response_status=201, resource_ref=ref),
    )


def test_retained_result_binds_both_server_identities_and_original_versions():
    assert validate_retained_creation(record()) == (UUID(ITEM), UUID(INITIATIVE))


@pytest.mark.parametrize(
    "field,value",
    [
        ("resource_type", "FEATURE"),
        ("resource_version", True),
        ("resource_version", 2),
        ("resource_id", "invalid"),
        ("resource_id", ITEM.replace("-", "")),
    ],
)
@pytest.mark.parametrize("nested", [True, False])
def test_invalid_identity_or_version_is_rejected(field, value, nested):
    ref = result()
    (ref["initiative_ref"] if nested else ref)[field] = value
    with pytest.raises(ReplayResourceUnavailable):
        validate_pair_reference(ref)


def test_closed_result_rejects_extra_fields_missing_pair_and_same_identity():
    original = result()
    cases = [
        None,
        {},
        {**original, "approval": "approved"},
        {k: v for k, v in original.items() if k != "initiative_ref"},
    ]
    changed = deepcopy(original)
    changed["initiative_ref"]["resource_id"] = ITEM
    cases.append(changed)
    for ref in cases:
        with pytest.raises(ReplayResourceUnavailable):
            validate_pair_reference(ref)


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "IN_PROGRESS"),
        ("response_status", 200),
        ("response_status", True),
        ("response_digest", "sha256:" + "0" * 64),
    ],
)
def test_uncompleted_or_corrupted_receipt_is_unavailable(field, value):
    retained = record()
    setattr(retained, field, value)
    with pytest.raises(ReplayResourceUnavailable):
        validate_retained_creation(retained)


def event_args():
    return dict(
        workspace_id=ITEM,
        product_id=INITIATIVE,
        roadmap_id=ITEM,
        milestone_id=INITIATIVE,
        feature_id=ITEM,
        owner_id=ACTOR,
        result=result(),
        actor={"actor_type": "HUMAN", "actor_id": ACTOR},
        occurred_at="2026-10-28T12:00:00+00:00",
    )


def test_event_keeps_two_stages_and_is_detached():
    args = event_args()
    event = build_item_creation_event(**args)
    args["result"]["initiative_ref"]["resource_id"] = ITEM
    assert event["result"] == result()
    assert event["approval_stages"] == ["PRD_APPROVAL", "PLAN_APPROVAL"]
    assert event["initial_item_status"] == "PROPOSED"
    assert event["initial_initiative_state"] == "DRAFT"


def test_event_requires_actor_to_be_the_item_owner():
    with pytest.raises(ValueError, match="OWNER"):
        build_item_creation_event(**{**event_args(), "owner_id": INITIATIVE})
