# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import traceback
import uuid
from copy import deepcopy

import pytest
from django.core.exceptions import ValidationError

from plane.curve.prd_metadata_validation import validate_review_decision_record
from plane.curve.prd_review_rationale import (
    encode_review_rationale,
    review_decision_metadata,
    review_decision_wire_record,
)
from plane.curve.tests import test_prd_review_validation as review_fixtures

graph = review_fixtures.graph
review = review_fixtures.review


pytestmark = pytest.mark.unit


def object_ref(value):
    return dict(
        object_id=str(uuid.uuid4()),
        digest="sha256:" + hashlib.sha256(value).hexdigest(),
        size_bytes=len(value),
        media_type="text/plain; charset=utf-8",
    )


def metadata_from(decision):
    return review_decision_metadata(
        decision=decision,
        rationale_ref=object_ref(decision["rationale"].encode("utf-8")),
        rationale_access_envelope_id=str(uuid.uuid4()),
        rationale_retention_policy_version_id=str(uuid.uuid4()),
    )


@pytest.mark.parametrize(
    "rationale",
    ["Synthetic rationale.", "  Original\r\ntext\t ", "e\u0301", "é", "😀" * 2000],
    ids=["plain", "whitespace-preserved", "decomposed", "composed", "max-utf8"],
)
def test_original_rationale_round_trips_without_normalization(review, rationale):
    decision = deepcopy(review["decision"])
    decision["rationale"] = rationale
    before = deepcopy(decision)
    metadata = metadata_from(decision)
    assert decision == before
    assert "rationale" not in metadata
    validate_review_decision_record(metadata)
    original_metadata = deepcopy(metadata)
    assert review_decision_wire_record(metadata=metadata, rationale_bytes=rationale.encode("utf-8")) == decision
    assert metadata == original_metadata


@pytest.mark.parametrize(
    "rationale", ["", " \n\t", "a" * 2001, None, 7], ids=["empty", "blank", "long", "null", "number"]
)
def test_invalid_rationale_is_rejected_before_protected_storage(rationale):
    with pytest.raises(ValidationError) as error:
        encode_review_rationale(rationale)
    assert error.value.code == "PRD_RATIONALE_INVALID"


def test_unpaired_surrogates_fail_without_encoding_exception_disclosure():
    with pytest.raises(ValidationError) as error:
        encode_review_rationale("Synthetic protected sentinel " + "\ud800")
    rendered = "".join(traceback.format_exception(error.type, error.value, error.tb))
    assert error.value.code == "PRD_RATIONALE_ENCODING_INVALID"
    assert error.value.__suppress_context__
    assert "UnicodeEncodeError" not in rendered


@pytest.mark.parametrize("field,value", [("digest", "sha256:" + "f" * 64), ("size_bytes", 1)])
def test_wrong_protected_object_reference_rejects_capture(review, field, value):
    decision = review["decision"]
    reference = object_ref(decision["rationale"].encode())
    reference[field] = value
    with pytest.raises(ValidationError) as error:
        review_decision_metadata(
            decision=decision,
            rationale_ref=reference,
            rationale_access_envelope_id=str(uuid.uuid4()),
            rationale_retention_policy_version_id=str(uuid.uuid4()),
        )
    assert error.value.code == "PRD_RATIONALE_OBJECT_MISMATCH"


@pytest.mark.parametrize("body", [b"altered", b"", None, "Synthetic rationale."])
def test_missing_or_changed_bytes_do_not_reconstruct_rationale(review, body):
    metadata = metadata_from(review["decision"])
    with pytest.raises(ValidationError) as error:
        review_decision_wire_record(metadata=metadata, rationale_bytes=body)
    assert error.value.code == "PRD_RATIONALE_OBJECT_MISMATCH"


def test_invalid_utf8_cannot_be_returned_even_when_reference_matches(review):
    metadata = metadata_from(review["decision"])
    metadata["rationale_ref"] = object_ref(b"\xff")
    with pytest.raises(ValidationError) as error:
        review_decision_wire_record(metadata=metadata, rationale_bytes=b"\xff")
    assert error.value.code == "PRD_RATIONALE_ENCODING_INVALID" and error.value.__suppress_context__


@pytest.mark.parametrize("body", [b" \n", b"a" * 2001])
def test_invalid_decoded_text_cannot_be_returned_even_when_reference_matches(review, body):
    metadata = metadata_from(review["decision"])
    metadata["rationale_ref"] = object_ref(body)
    with pytest.raises(ValidationError) as error:
        review_decision_wire_record(metadata=metadata, rationale_bytes=body)
    assert error.value.code == "PRD_RATIONALE_INVALID"


@pytest.mark.parametrize("field", ["rationale", "body", "preview", "url"])
def test_metadata_rejects_inline_rationale_and_alternative_content_channels(review, field):
    metadata = metadata_from(review["decision"])
    metadata[field] = "Synthetic protected sentinel"
    with pytest.raises(ValidationError) as error:
        validate_review_decision_record(metadata)
    assert error.value.code == "PRD_METADATA_SCHEMA_INVALID"
    assert "Synthetic protected sentinel" not in str(error.value)


def test_rationale_references_are_copied_not_aliased(review):
    metadata = metadata_from(review["decision"])
    wire = review_decision_wire_record(metadata=metadata, rationale_bytes=review["decision"]["rationale"].encode())
    wire["decided_by"]["actor_id"] = "replacement"
    assert metadata["decided_by"] == review["decision"]["decided_by"]
