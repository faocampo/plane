# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Explicit new-Initiative submission edition; historical scope pins stay unchanged."""

from copy import deepcopy
import uuid
from .local_document_record import validate_local_document_record
from .local_document_store import LocalDocumentUnavailable
from .local_prd_review import _SUBMISSION_FIELDS, _require, _id, _version, _digest, _instant, _reviewers, _pin

SCHEMA_VERSION = "curve.local-prd-submission/v2-candidate"
INTENTS = {"STRATEGIC", "CUSTOMER_COMMITMENT", "BUSINESS_IMPROVEMENT", "MANDATORY"}
FIELDS = (_SUBMISSION_FIELDS - {"scope_revision_id", "scope_revision", "membership_digest"}) | {
    "product_id",
    "product_version",
    "business_intent",
}


def validate_new_work_submission(value):
    try:
        _require(type(value) is dict and set(value) == FIELDS and value["schema_version"] == SCHEMA_VERSION)
        for field in ("id", "workspace_id", "initiative_id", "source_id", "product_id", "submitted_by"):
            _id(value[field])
        for field in ("initiative_version", "source_version", "product_version"):
            _version(value[field])
        for field in ("source_digest", "content_digest", "digest"):
            _digest(value[field])
        _require(type(value["business_intent"]) is str and value["business_intent"] in INTENTS)
        _instant(value["submitted_at"])
        _reviewers(value["reviewers"], value["risk_tier"])
        _require(_pin(value) == value["digest"])
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise LocalDocumentUnavailable from None
    return deepcopy(value)


def create_new_work_submission(
    *,
    source,
    initiative_version,
    product_id,
    product_version,
    business_intent,
    reviewers,
    risk_tier,
    submitted_by,
    submitted_at,
):
    source = validate_local_document_record(source)
    value = dict(
        schema_version=SCHEMA_VERSION,
        id=str(uuid.uuid4()),
        workspace_id=source["workspace_id"],
        initiative_id=source["initiative_id"],
        initiative_version=initiative_version,
        source_id=source["id"],
        source_version=source["version"],
        source_digest=source["digest"],
        content_digest=source["snapshot"]["digest"],
        product_id=product_id,
        product_version=product_version,
        business_intent=business_intent,
        reviewers=deepcopy(reviewers),
        risk_tier=risk_tier,
        submitted_by=submitted_by,
        submitted_at=submitted_at,
    )
    value["digest"] = _pin(value)
    return validate_new_work_submission(value)


def require_current_new_work_submission(
    submission, *, source, product_id, product_version, business_intent, reviewers, risk_tier
):
    subject = validate_new_work_submission(submission)
    source = validate_local_document_record(source)
    expected = dict(
        workspace_id=source["workspace_id"],
        initiative_id=source["initiative_id"],
        source_id=source["id"],
        source_version=source["version"],
        source_digest=source["digest"],
        content_digest=source["snapshot"]["digest"],
        product_id=product_id,
        product_version=product_version,
        business_intent=business_intent,
        reviewers=reviewers,
        risk_tier=risk_tier,
    )
    _require(all(subject[key] == value for key, value in expected.items()))
    return subject
