# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811
from copy import deepcopy
import pytest

from plane.curve.local_document_store import LocalDocumentUnavailable
from plane.curve.local_prd_review import _pin, create_decision
from plane.curve.local_prd_reopening import create_reopening, validate_reopening, require_replacement_source
from plane.curve.tests.test_local_prd_review import example, approve, REVIEWER  # noqa: F401
from plane.curve.tests.test_local_document_record import uploaded, ACTOR, WORKSPACE

pytestmark = pytest.mark.unit


def reopened(subject, decision, **overrides):
    return create_reopening(
        **(
            dict(
                submission=subject,
                decision=decision,
                initiative_version=4,
                reopened_by=ACTOR,
                reopened_at="2026-10-21T12:02:00Z",
            )
            | overrides
        )
    )


def test_reopening_retains_exact_approved_evidence(example):
    _, _, subject = example
    decision = approve(subject)
    before = deepcopy((subject, decision))
    record = reopened(subject, decision)
    assert record["submission_digest"] == subject["digest"]
    assert record["decision_digest"] == decision["digest"]
    assert (subject, decision) == before
    result = validate_reopening(record, subject, decision)
    result["source_id"] = WORKSPACE
    assert record["source_id"] == subject["source_id"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("workspace_id", ACTOR),
        ("initiative_id", ACTOR),
        ("source_id", ACTOR),
        ("source_digest", "sha256:" + "b" * 64),
        ("submission_id", ACTOR),
        ("submission_digest", "sha256:" + "b" * 64),
        ("decision_id", ACTOR),
        ("decision_digest", "sha256:" + "b" * 64),
        ("initiative_version", 3),
        ("initiative_version", True),
        ("reopened_at", "2026-10-21T12:00:00Z"),
        ("reopened_at", "2026-02-31T12:02:00Z"),
        ("reopened_by", "not-a-user-id"),
        ("schema_version", "other"),
        ("unexpected", "value"),
    ],
)
def test_rehashed_wrong_subject_or_chronology_is_rejected(example, field, value):
    _, _, subject = example
    decision = approve(subject)
    record = reopened(subject, decision)
    record[field] = value
    record["digest"] = _pin(record)
    with pytest.raises(LocalDocumentUnavailable):
        validate_reopening(record, subject, decision)


def test_change_request_cannot_be_reopened_as_an_approval(example):
    _, _, subject = example
    decision = create_decision(
        submission=subject,
        initiative_version=3,
        state="CHANGES_REQUESTED",
        decided_by=REVIEWER,
        decided_at="2026-10-21T12:01:00Z",
        feedback=dict(object_id=ACTOR, digest="sha256:" + "a" * 64, size_bytes=20, media_type="text/plain"),
    )
    with pytest.raises(LocalDocumentUnavailable):
        reopened(subject, decision)


def test_reopened_subject_requires_a_new_upload_even_for_identical_bytes(example):
    store, inputs, subject = example
    decision = approve(subject)
    record = reopened(subject, decision)
    with pytest.raises(LocalDocumentUnavailable):
        require_replacement_source(record, subject, decision, inputs["source"])
    replacement = uploaded(store, predecessor=inputs["source"], uploaded_at="2026-10-21T12:03:00Z")
    assert replacement["original"]["digest"] == inputs["source"]["original"]["digest"]
    assert require_replacement_source(record, subject, decision, replacement) == replacement


def test_replacement_captured_before_reopening_is_rejected(example):
    store, inputs, subject = example
    decision = approve(subject)
    record = reopened(subject, decision)
    replacement = uploaded(store, predecessor=inputs["source"], uploaded_at="2026-10-21T12:01:00Z")
    with pytest.raises(LocalDocumentUnavailable):
        require_replacement_source(record, subject, decision, replacement)


def test_record_digest_cannot_be_changed(example):
    _, _, subject = example
    decision = approve(subject)
    record = reopened(subject, decision)
    record["digest"] = "sha256:" + "f" * 64
    with pytest.raises(LocalDocumentUnavailable):
        validate_reopening(record, subject, decision)
