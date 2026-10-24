# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
from copy import deepcopy
import pytest
from plane.curve.local_plan_review import (
    create_plan_revision,
    create_plan_submission,
    create_plan_decision,
    validate_plan_submission,
    validate_plan_decision,
)
from plane.curve.local_prd_review import _pin
from plane.curve.local_document_store import LocalDocumentUnavailable
from plane.curve.tests.test_local_prd_review import example as product_example, approve, ACTOR, REVIEWER  # noqa: F401

pytestmark = pytest.mark.unit


@pytest.fixture
def review(product_example):  # noqa: F811
    _, inputs, prd = product_example
    approval = approve(prd)
    source = inputs["source"]
    plan = create_plan_revision(
        submission=prd,
        approval=approval,
        initiative_version=4,
        version=1,
        predecessor_id=None,
        original=source["original"],
        snapshot=source["snapshot"],
        uploaded_by=ACTOR,
        uploaded_at="2026-10-21T12:02:00Z",
    )
    submission = create_plan_submission(
        plan=plan,
        prd_submission=prd,
        prd_approval=approval,
        initiative_version=4,
        submitted_by=ACTOR,
        submitted_at="2026-10-21T12:03:00Z",
    )
    return dict(submission=submission, plan=plan, prd_submission=prd, prd_approval=approval)


def decide(review, **overrides):
    args = dict(initiative_version=4, state="APPROVED", decided_by=ACTOR, decided_at="2026-10-21T12:04:00Z")
    return create_plan_decision(**review, **(args | overrides))


def test_technical_approval_pins_exact_plan_and_product_approval(review):
    result = decide(review)
    assert result["decided_by"] == review["submission"]["technical_approver_id"]
    assert result["plan_revision_id"] == review["plan"]["id"]
    assert result["feedback"] is None
    assert validate_plan_decision(result, **review) == result


@pytest.mark.parametrize(
    "field,value",
    [
        ("plan_revision_digest", "sha256:" + "0" * 64),
        ("content_digest", "sha256:" + "0" * 64),
        ("technical_approver_id", REVIEWER),
        ("submitted_by", REVIEWER),
        ("plan_version", True),
        ("submitted_at", "2026-10-21T12:01:00Z"),
    ],
)
def test_repinning_cannot_change_the_submitted_plan(review, field, value):
    data = deepcopy(review["submission"])
    data[field] = value
    data["digest"] = _pin(data)
    with pytest.raises(LocalDocumentUnavailable):
        validate_plan_submission(data, **{key: value for key, value in review.items() if key != "submission"})


@pytest.mark.parametrize(
    "overrides",
    [
        {"decided_by": REVIEWER},
        {"state": "CODE_APPROVED"},
        {"state": "CHANGES_REQUESTED"},
        {"initiative_version": 3},
        {"decided_at": "2026-10-21T12:02:00Z"},
        {"feedback": {"text": "inline feedback"}},
    ],
)
def test_invalid_decision_is_rejected(review, overrides):
    with pytest.raises(LocalDocumentUnavailable):
        decide(review, **overrides)


def test_changes_requested_retains_only_protected_feedback_reference(review):
    note = dict(object_id=ACTOR, digest="sha256:" + "b" * 64, size_bytes=40, media_type="text/plain")
    result = decide(review, state="CHANGES_REQUESTED", feedback=note)
    assert validate_plan_decision(result, **review)["feedback"] == note
    note["size_bytes"] = 16385
    with pytest.raises(LocalDocumentUnavailable):
        decide(review, state="CHANGES_REQUESTED", feedback=note)
