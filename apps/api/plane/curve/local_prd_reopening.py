# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Immutable evidence for reopening an approved local PRD.

Reopening retains the approved submission and decision. A consuming native
command must authorize the Initiative owner and atomically invalidate current
approval eligibility. These pure records never authorize a transition themselves.
"""

from copy import deepcopy
import uuid

from .local_document_record import validate_local_document_record
from .local_document_store import LocalDocumentUnavailable
from .local_prd_review import (
    _id,
    _digest,
    _instant,
    _version,
    _pin,
    _require,
    validate_submission,
    validate_decision,
)

REOPENING_SCHEMA = "curve.local-prd-reopening/v1-candidate"
_FIELDS = {
    "schema_version",
    "id",
    "workspace_id",
    "initiative_id",
    "initiative_version",
    "source_id",
    "source_digest",
    "submission_id",
    "submission_digest",
    "decision_id",
    "decision_digest",
    "reopened_by",
    "reopened_at",
    "digest",
}


def validate_reopening(value, submission, decision):
    """Validate an exact approved subject, chronology and closed canonical record."""
    try:
        submission = validate_submission(submission)
        decision = validate_decision(decision, submission)
        _require(type(value) is dict and set(value) == _FIELDS)
        _require(value["schema_version"] == REOPENING_SCHEMA)
        for field in (
            "id",
            "workspace_id",
            "initiative_id",
            "source_id",
            "submission_id",
            "decision_id",
            "reopened_by",
        ):
            _id(value[field])
        for field in ("source_digest", "submission_digest", "decision_digest", "digest"):
            _digest(value[field])
        _version(value["initiative_version"])
        _require(decision["state"] == "APPROVED")
        _require(value["initiative_version"] > decision["initiative_version"])
        _require(_instant(value["reopened_at"]) >= _instant(decision["decided_at"]))
        expected = dict(
            workspace_id=submission["workspace_id"],
            initiative_id=submission["initiative_id"],
            source_id=submission["source_id"],
            source_digest=submission["source_digest"],
            submission_id=submission["id"],
            submission_digest=submission["digest"],
            decision_id=decision["id"],
            decision_digest=decision["digest"],
        )
        _require(all(value[key] == item for key, item in expected.items()))
        _require(_pin(value) == value["digest"])
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise LocalDocumentUnavailable from None
    return deepcopy(value)


def create_reopening(*, submission, decision, initiative_version, reopened_by, reopened_at):
    submission = validate_submission(submission)
    decision = validate_decision(decision, submission)
    value = dict(
        schema_version=REOPENING_SCHEMA,
        id=str(uuid.uuid4()),
        workspace_id=submission["workspace_id"],
        initiative_id=submission["initiative_id"],
        initiative_version=initiative_version,
        source_id=submission["source_id"],
        source_digest=submission["source_digest"],
        submission_id=submission["id"],
        submission_digest=submission["digest"],
        decision_id=decision["id"],
        decision_digest=decision["digest"],
        reopened_by=reopened_by,
        reopened_at=reopened_at,
    )
    value["digest"] = _pin(value)
    return validate_reopening(value, submission, decision)


def require_replacement_source(reopening, submission, decision, source):
    """A reopened approval requires a new upload identity, even for equal bytes."""
    reopening = validate_reopening(reopening, submission, decision)
    source = validate_local_document_record(source)
    _require(source["workspace_id"] == reopening["workspace_id"])
    _require(source["initiative_id"] == reopening["initiative_id"])
    _require(source["id"] != reopening["source_id"])
    _require(source["version"] > submission["source_version"])
    _require(_instant(source["uploaded_at"]) >= _instant(reopening["reopened_at"]))
    return source
