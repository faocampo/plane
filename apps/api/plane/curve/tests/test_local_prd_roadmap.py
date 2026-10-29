# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
from copy import deepcopy

import pytest

from plane.curve.local_document_store import (
    LocalDocumentStore,
    LocalDocumentUnavailable,
)
from plane.curve.local_prd_review import _pin
from plane.curve.tests.test_local_document_record import (
    uploaded,
    ACTOR,
    WORKSPACE,
    INITIATIVE,
)
from plane.curve.tests.test_local_prd_review import REVIEWERS

from plane.curve.local_prd_roadmap import (
    create_roadmap_submission,
    require_current_roadmap_submission,
    validate_roadmap_submission,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def subject(tmp_path):
    root = tmp_path / "documents"
    root.mkdir(mode=0o700)
    with LocalDocumentStore(root) as store:
        inputs = dict(
            source=uploaded(store),
            product_id=WORKSPACE,
            product_version=1,
            business_intent="STRATEGIC",
            reviewers=deepcopy(REVIEWERS),
            risk_tier="STANDARD",
            roadmap_item_id=INITIATIVE,
            roadmap_item_scope=dict(
                object_id=ACTOR,
                digest="sha256:" + "a" * 64,
                size_bytes=24,
                media_type="text/markdown",
                editor_schema_version="markdown-v1",
            ),
        )
        record = create_roadmap_submission(
            **inputs,
            initiative_version=2,
            submitted_by=ACTOR,
            submitted_at="2026-10-21T12:00:00Z",
        )
        yield inputs, record


def test_exact_document_and_item_scope_are_required(subject):
    inputs, record = subject
    assert require_current_roadmap_submission(record, **inputs) == record
    assert record["source_digest"] == inputs["source"]["digest"]
    assert record["roadmap_item_scope"] == inputs["roadmap_item_scope"]
    copy = validate_roadmap_submission(record)
    copy["roadmap_item_scope"]["size_bytes"] += 1
    assert record["roadmap_item_scope"]["size_bytes"] == 24


@pytest.mark.parametrize(
    "field,value",
    [
        ("object_id", WORKSPACE),
        ("digest", "sha256:" + "b" * 64),
        ("size_bytes", 25),
        ("media_type", "text/plain"),
        ("editor_schema_version", "markdown-v2"),
    ],
)
def test_scope_replacement_invalidates_current_subject_even_with_identical_bytes(subject, field, value):
    inputs, record = subject
    changed = deepcopy(inputs)
    changed["roadmap_item_scope"][field] = value
    with pytest.raises(LocalDocumentUnavailable):
        require_current_roadmap_submission(record, **changed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("roadmap_item_id", WORKSPACE),
        ("product_id", ACTOR),
        ("product_version", 2),
        ("business_intent", "MANDATORY"),
        ("risk_tier", "HIGH"),
    ],
)
def test_foreign_or_changed_native_context_is_not_current(subject, field, value):
    inputs, record = subject
    with pytest.raises(LocalDocumentUnavailable):
        require_current_roadmap_submission(record, **(inputs | {field: value}))


@pytest.mark.parametrize(
    "change",
    ["extra", "missing", "boolean_size", "foreign_edition", "bad_id", "digest"],
)
def test_closed_record_rejects_malformed_or_tampered_subjects(subject, change):
    _, record = subject
    value = deepcopy(record)
    if change == "extra":
        value["code_approver"] = ACTOR
    elif change == "missing":
        value.pop("roadmap_item_scope")
    elif change == "boolean_size":
        value["roadmap_item_scope"]["size_bytes"] = True
    elif change == "foreign_edition":
        value["schema_version"] = "curve.local-prd-submission/v2-candidate"
    elif change == "bad_id":
        value["roadmap_item_id"] = "not-a-uuid"
    else:
        value["roadmap_item_scope"]["size_bytes"] = 40
    if change != "digest":
        value["digest"] = _pin(value)
    with pytest.raises(LocalDocumentUnavailable):
        validate_roadmap_submission(value)


def test_changed_reviewer_and_reuploaded_document_require_fresh_submission(subject):
    inputs, record = subject
    changed = deepcopy(inputs)
    changed["reviewers"][0]["gate_assignment_id"] = ACTOR
    with pytest.raises(LocalDocumentUnavailable):
        require_current_roadmap_submission(record, **changed)
    changed = deepcopy(inputs)
    changed["source"]["id"] = ACTOR
    changed["source"]["digest"] = _pin(changed["source"])
    with pytest.raises(LocalDocumentUnavailable):
        require_current_roadmap_submission(record, **changed)
