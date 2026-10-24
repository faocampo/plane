# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
from copy import deepcopy

import pytest

from plane.curve.local_document_store import LocalDocumentStore, LocalDocumentUnavailable
from plane.curve.local_prd_review import (
    create_submission,
    create_decision,
    validate_submission,
    validate_decision,
    require_current_submission,
    validate_feedback,
    _pin,
)
from plane.curve.tests.test_local_document_record import uploaded, ACTOR, WORKSPACE, INITIATIVE

pytestmark = pytest.mark.unit
REVIEWER = "00000000-0000-4000-8000-000000000004"
REVIEWERS = [
    dict(gate_type="PLAN_APPROVAL", gate_assignment_id=WORKSPACE, approver_user_id=ACTOR),
    dict(gate_type="PRD_APPROVAL", gate_assignment_id=INITIATIVE, approver_user_id=REVIEWER),
]


@pytest.fixture
def example(tmp_path):
    root = tmp_path / "documents"
    root.mkdir(mode=0o700)
    with LocalDocumentStore(root) as store:
        source = uploaded(store)
        inputs = dict(
            source=source,
            scope_revision_id=WORKSPACE,
            scope_revision=1,
            membership_digest="sha256:" + "a" * 64,
            reviewers=deepcopy(REVIEWERS),
            risk_tier="STANDARD",
        )
        subject = create_submission(
            **inputs, initiative_version=2, submitted_by=ACTOR, submitted_at="2026-10-21T12:00:00Z"
        )
        yield store, inputs, subject


def approve(subject, **overrides):
    values = dict(
        submission=subject,
        initiative_version=3,
        state="APPROVED",
        decided_by=REVIEWER,
        decided_at="2026-10-21T12:01:00Z",
    )
    return create_decision(**(values | overrides))


def test_exact_uploaded_version_has_two_reviewers_and_a_product_decision(example):
    _, inputs, subject = example
    assert require_current_submission(subject, **inputs) == subject
    decision = approve(subject)
    assert decision["source_digest"] == inputs["source"]["digest"]
    assert decision["gate_assignment_id"] == REVIEWERS[1]["gate_assignment_id"]
    assert decision["feedback"] is None
    assert set(decision).isdisjoint({"provider_version", "canonical_url", "feedback_text"})
    copy = validate_submission(subject)
    copy["reviewers"][0]["approver_user_id"] = REVIEWER
    assert subject["reviewers"][0]["approver_user_id"] == ACTOR


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", ACTOR),
        ("source_digest", "sha256:" + "b" * 64),
        ("scope_revision", 2),
        ("membership_digest", "sha256:" + "b" * 64),
        ("risk_tier", "HIGH"),
    ],
)
def test_changed_native_subject_is_not_current_even_after_valid_repin(example, field, value):
    _, inputs, subject = example
    changed = deepcopy(subject)
    changed[field] = value
    changed["digest"] = _pin(changed)
    with pytest.raises(LocalDocumentUnavailable):
        require_current_submission(changed, **inputs)


def test_identical_bytes_reuploaded_require_a_fresh_submission(example):
    store, inputs, subject = example
    replacement = uploaded(store, predecessor=inputs["source"])
    assert replacement["original"]["digest"] == inputs["source"]["original"]["digest"]
    with pytest.raises(LocalDocumentUnavailable):
        require_current_submission(subject, **(inputs | {"source": replacement}))


@pytest.mark.parametrize(
    "overrides",
    [
        {"decided_by": ACTOR},
        {"initiative_version": 2},
        {"initiative_version": True},
        {"decided_at": "2026-10-20T12:00:00Z"},
        {"state": "CODE_APPROVED"},
        {"state": "CHANGES_REQUESTED"},
        {"feedback": {"text": "unexpected"}},
    ],
)
def test_invalid_or_wrong_reviewer_decision_is_rejected(example, overrides):
    with pytest.raises(LocalDocumentUnavailable):
        approve(example[2], **overrides)


def test_return_requires_private_feedback_reference_and_preserves_unicode():
    assert validate_feedback("  Add acceptance checks.\n確認  ") == "  Add acceptance checks.\n確認  ".encode()


@pytest.mark.parametrize("text", ["", " \n\t", "a\x00b", "\ud800", "a" * 16385, None])
def test_empty_invalid_or_oversized_feedback_is_rejected(text):
    with pytest.raises(LocalDocumentUnavailable):
        validate_feedback(text)


def test_changes_requested_record_has_reference_only(example):
    feedback = dict(object_id=ACTOR, digest="sha256:" + "b" * 64, size_bytes=40, media_type="text/plain")
    decision = approve(example[2], state="CHANGES_REQUESTED", feedback=feedback)
    assert validate_decision(decision, example[2]) == decision
    changed = deepcopy(decision)
    changed["source_digest"] = "sha256:" + "f" * 64
    changed["digest"] = _pin(changed)
    with pytest.raises(LocalDocumentUnavailable):
        validate_decision(changed, example[2])


def test_only_low_risk_allows_same_human_for_both_stages(example):
    _, inputs, subject = example
    subject["reviewers"][0]["approver_user_id"] = REVIEWER
    subject["digest"] = _pin(subject)
    with pytest.raises(LocalDocumentUnavailable):
        validate_submission(subject)
    subject["risk_tier"] = "LOW"
    subject["digest"] = _pin(subject)
    assert validate_submission(subject)["risk_tier"] == "LOW"


@pytest.mark.parametrize(
    "field,value",
    [
        ("reviewers", [REVIEWERS[0]]),
        ("reviewers", [None, None]),
        ("initiative_version", True),
        ("source_version", 0),
        ("submitted_at", "2026-02-31T00:00:00Z"),
        ("source_digest", None),
    ],
)
def test_submission_rejects_malformed_fields_with_recomputed_digest(example, field, value):
    subject = deepcopy(example[2])
    subject[field] = value
    subject["digest"] = _pin(subject)
    with pytest.raises(LocalDocumentUnavailable):
        validate_submission(subject)
