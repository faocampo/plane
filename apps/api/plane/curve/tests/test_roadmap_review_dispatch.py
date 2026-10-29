# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Edition dispatch only; native authority and persistence have separate tests."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from plane.curve.tests import test_local_prd_roadmap as records
from plane.curve import local_prd_roadmap
from plane.curve.local_document_store import LocalDocumentUnavailable
from plane.curve.prd_commands import PrdCommandError

subject = records.subject
pytestmark = pytest.mark.unit


@pytest.fixture
def dispatch():
    from plane.curve import local_prd_review_authority, local_prd_review

    return local_prd_review_authority, local_prd_review


def document(inputs, mode="ROADMAP"):
    return SimpleNamespace(
        current_source=SimpleNamespace(as_record=lambda: deepcopy(inputs["source"])),
        context=SimpleNamespace(
            initiative=SimpleNamespace(
                mode=mode,
                business_intent=inputs["business_intent"],
                risk_tier=inputs["risk_tier"],
            ),
            product=SimpleNamespace(id=inputs["product_id"], version=inputs["product_version"]),
            reviewers=inputs["reviewers"],
            roadmap_item=SimpleNamespace(id=inputs["roadmap_item_id"], scope_body=inputs["roadmap_item_scope"]),
            head=None,
        ),
    )


@pytest.mark.parametrize(
    "mode,edition",
    [("ROADMAP", "v3-roadmap-candidate"), ("STANDALONE", "v2-candidate")],
)
def test_dispatch_preserves_distinct_subject_editions(dispatch, subject, mode, edition):
    authority, validator = dispatch
    inputs, original = subject
    current = document(inputs, mode)
    result = authority.create_document_submission(
        current,
        initiative_version=original["initiative_version"],
        submitted_by=original["submitted_by"],
        submitted_at=original["submitted_at"],
    )
    assert result["schema_version"] == "curve.local-prd-submission/" + edition
    assert ("roadmap_item_scope" in result) is (mode == "ROADMAP")
    assert validator.validate_submission(result) == result
    assert authority.require_current_document_submission(result, current) == result


def test_dispatch_rejects_standalone_subject_for_roadmap(dispatch, subject):
    authority, _ = dispatch
    inputs, original = subject
    old = local_prd_roadmap._standalone_projection(original)
    with pytest.raises(LocalDocumentUnavailable):
        authority.require_current_document_submission(old, document(inputs))


def test_dispatch_rejects_roadmap_subject_for_standalone(dispatch, subject):
    authority, _ = dispatch
    inputs, original = subject
    with pytest.raises(LocalDocumentUnavailable):
        authority.require_current_document_submission(original, document(inputs, "STANDALONE"))


def test_roadmap_context_requires_defining_item(dispatch, subject):
    authority, _ = dispatch
    inputs, _ = subject
    current = document(inputs)
    current.context.roadmap_item = None
    with pytest.raises(PrdCommandError):
        authority.submission_inputs(current)
