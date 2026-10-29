# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Immutable local-file Product review records, independent of provider bindings.

These pure records are evidence, not permission grants. The native command must
resolve current authority, protect feedback bytes, lock versions and atomically
persist the record and Initiative transition before exposing any action result.
"""

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re
import uuid

from .local_document_record import validate_local_document_record
from .local_document_store import LocalDocumentUnavailable

SUBMISSION_SCHEMA = "curve.local-prd-submission/v1-candidate"
DECISION_SCHEMA = "curve.local-prd-decision/v1-candidate"
_MAX_VERSION = 9007199254740991
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_INSTANT = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z\Z")
_SUBMISSION_FIELDS = {
    "schema_version",
    "id",
    "workspace_id",
    "initiative_id",
    "initiative_version",
    "source_id",
    "source_version",
    "source_digest",
    "content_digest",
    "scope_revision_id",
    "scope_revision",
    "membership_digest",
    "reviewers",
    "risk_tier",
    "submitted_by",
    "submitted_at",
    "digest",
}
_DECISION_FIELDS = {
    "schema_version",
    "id",
    "workspace_id",
    "initiative_id",
    "initiative_version",
    "submission_id",
    "submission_digest",
    "source_id",
    "source_digest",
    "gate_assignment_id",
    "state",
    "decided_by",
    "decided_at",
    "feedback",
    "digest",
}


def _require(value):
    if not value:
        raise LocalDocumentUnavailable


def _id(value):
    _require(type(value) is str and str(uuid.UUID(value)) == value)


def _version(value):
    _require(type(value) is int and 1 <= value <= _MAX_VERSION)


def _digest(value):
    _require(type(value) is str and _DIGEST.fullmatch(value) is not None)


def _instant(value):
    _require(type(value) is str and _INSTANT.fullmatch(value) is not None)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _pin(value):
    value = deepcopy(value)
    value.pop("digest", None)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _reviewers(value, risk):
    _require(type(value) is list and len(value) == 2)
    _require([item.get("gate_type") for item in value] == ["PLAN_APPROVAL", "PRD_APPROVAL"])
    for item in value:
        _require(type(item) is dict and set(item) == {"gate_type", "gate_assignment_id", "approver_user_id"})
        _id(item["gate_assignment_id"])
        _id(item["approver_user_id"])
    _require(value[0]["gate_assignment_id"] != value[1]["gate_assignment_id"])
    _require(risk in {"LOW", "STANDARD", "HIGH"})
    if risk != "LOW":
        _require(value[0]["approver_user_id"] != value[1]["approver_user_id"])


def validate_submission(value):
    if type(value) is dict and value.get("schema_version") == "curve.local-prd-submission/v3-roadmap-candidate":
        from .local_prd_roadmap import validate_roadmap_submission

        return validate_roadmap_submission(value)
    if type(value) is dict and value.get("schema_version") == "curve.local-prd-submission/v2-candidate":
        from .local_prd_new_work import validate_new_work_submission

        return validate_new_work_submission(value)
    try:
        _require(type(value) is dict and set(value) == _SUBMISSION_FIELDS)
        _require(value["schema_version"] == SUBMISSION_SCHEMA)
        for field in ("id", "workspace_id", "initiative_id", "source_id", "scope_revision_id", "submitted_by"):
            _id(value[field])
        for field in ("initiative_version", "source_version", "scope_revision"):
            _version(value[field])
        for field in ("source_digest", "content_digest", "membership_digest", "digest"):
            _digest(value[field])
        _instant(value["submitted_at"])
        _reviewers(value["reviewers"], value["risk_tier"])
        _require(_pin(value) == value["digest"])
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise LocalDocumentUnavailable from None
    return deepcopy(value)


def create_submission(
    *,
    source,
    initiative_version,
    scope_revision_id,
    scope_revision,
    membership_digest,
    reviewers,
    risk_tier,
    submitted_by,
    submitted_at,
):
    source = validate_local_document_record(source)
    value = dict(
        schema_version=SUBMISSION_SCHEMA,
        id=str(uuid.uuid4()),
        workspace_id=source["workspace_id"],
        initiative_id=source["initiative_id"],
        initiative_version=initiative_version,
        source_id=source["id"],
        source_version=source["version"],
        source_digest=source["digest"],
        content_digest=source["snapshot"]["digest"],
        scope_revision_id=scope_revision_id,
        scope_revision=scope_revision,
        membership_digest=membership_digest,
        reviewers=deepcopy(reviewers),
        risk_tier=risk_tier,
        submitted_by=submitted_by,
        submitted_at=submitted_at,
    )
    value["digest"] = _pin(value)
    return validate_submission(value)


def validate_decision(value, submission):
    try:
        subject = validate_submission(submission)
        _require(type(value) is dict and set(value) == _DECISION_FIELDS)
        _require(value["schema_version"] == DECISION_SCHEMA)
        for field in ("id", "decided_by", "gate_assignment_id"):
            _id(value[field])
        _version(value["initiative_version"])
        _require(value["initiative_version"] > subject["initiative_version"])
        for field in ("workspace_id", "initiative_id", "source_id", "source_digest"):
            _require(value[field] == subject[field])
        _require(value["submission_id"] == subject["id"] and value["submission_digest"] == subject["digest"])
        reviewer = subject["reviewers"][1]
        _require(value["gate_assignment_id"] == reviewer["gate_assignment_id"])
        _require(value["decided_by"] == reviewer["approver_user_id"])
        _require(_instant(value["decided_at"]) >= _instant(subject["submitted_at"]))
        _require(value["state"] in {"APPROVED", "CHANGES_REQUESTED"})
        if value["state"] == "APPROVED":
            _require(value["feedback"] is None)
        else:
            feedback = value["feedback"]
            _require(type(feedback) is dict and set(feedback) == {"object_id", "digest", "size_bytes", "media_type"})
            _id(feedback["object_id"])
            _digest(feedback["digest"])
            _require(type(feedback["size_bytes"]) is int and 1 <= feedback["size_bytes"] <= 16384)
            _require(feedback["media_type"] == "text/plain")
        _digest(value["digest"])
        _require(_pin(value) == value["digest"])
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise LocalDocumentUnavailable from None
    return deepcopy(value)


def validate_feedback(text):
    """Validate before private storage; feedback is never embedded in metadata."""
    try:
        _require(type(text) is str and text.strip() and "\x00" not in text)
        body = text.encode("utf-8", errors="strict")
        _require(1 <= len(body) <= 16384)
    except (ValueError, TypeError, UnicodeError):
        raise LocalDocumentUnavailable from None
    return body


def create_decision(*, submission, initiative_version, state, decided_by, decided_at, feedback=None):
    subject = validate_submission(submission)
    value = dict(
        schema_version=DECISION_SCHEMA,
        id=str(uuid.uuid4()),
        workspace_id=subject["workspace_id"],
        initiative_id=subject["initiative_id"],
        initiative_version=initiative_version,
        submission_id=subject["id"],
        submission_digest=subject["digest"],
        source_id=subject["source_id"],
        source_digest=subject["source_digest"],
        gate_assignment_id=subject["reviewers"][1]["gate_assignment_id"],
        state=state,
        decided_by=decided_by,
        decided_at=decided_at,
        feedback=deepcopy(feedback),
    )
    value["digest"] = _pin(value)
    return validate_decision(value, subject)


def require_current_submission(
    submission, *, source, scope_revision_id, scope_revision, membership_digest, reviewers, risk_tier
):
    """Compare exact native inputs; caller still owns authorization and locking."""
    subject = validate_submission(submission)
    current = validate_local_document_record(source)
    expected = dict(
        workspace_id=current["workspace_id"],
        initiative_id=current["initiative_id"],
        source_id=current["id"],
        source_version=current["version"],
        source_digest=current["digest"],
        content_digest=current["snapshot"]["digest"],
        scope_revision_id=scope_revision_id,
        scope_revision=scope_revision,
        membership_digest=membership_digest,
        reviewers=reviewers,
        risk_tier=risk_tier,
    )
    _require(all(subject[key] == value for key, value in expected.items()))
    return subject
