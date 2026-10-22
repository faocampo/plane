# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Local plan revision identity, pinned to an actual approved local PRD.

The record validates evidence only. Commands must resolve current native access,
verify protected bytes and persist their effects atomically.
"""

from copy import deepcopy
import uuid
from .local_document_store import LocalDocumentUnavailable
from .local_prd_review import validate_submission, validate_decision, _id, _version, _digest, _instant, _pin, _require

SCHEMA = "curve.local-plan-revision/v1-candidate"
_FIELDS = {
    "schema_version",
    "id",
    "workspace_id",
    "initiative_id",
    "initiative_version",
    "version",
    "predecessor_id",
    "prd_submission_id",
    "prd_submission_digest",
    "prd_decision_id",
    "prd_decision_digest",
    "original",
    "snapshot",
    "normalization_schema_version",
    "uploaded_by",
    "uploaded_at",
    "digest",
}


def _reference(value, snapshot=False):
    _require(type(value) is dict and set(value) == {"object_id", "digest", "size_bytes", "media_type"})
    _id(value["object_id"])
    _digest(value["digest"])
    _version(value["size_bytes"])
    _require(value["size_bytes"] <= (6 * 10 * 1024 * 1024 + 4096 if snapshot else 10 * 1024 * 1024))
    _require(
        value["media_type"]
        in ({"application/json"} if snapshot else {"application/pdf", "text/plain", "text/markdown"})
    )


def validate_plan_revision(value, *, submission, approval):
    try:
        subject = validate_submission(submission)
        accepted = validate_decision(approval, subject)
        _require(accepted["state"] == "APPROVED")
        _require(type(value) is dict and set(value) == _FIELDS and value["schema_version"] == SCHEMA)
        for key in ("id", "uploaded_by"):
            _id(value[key])
        for key in ("initiative_version", "version"):
            _version(value[key])
        _require(value["initiative_version"] > accepted["initiative_version"])
        for key in ("workspace_id", "initiative_id"):
            _require(value[key] == subject[key])
        _require(value["prd_submission_id"] == subject["id"] and value["prd_submission_digest"] == subject["digest"])
        _require(value["prd_decision_id"] == accepted["id"] and value["prd_decision_digest"] == accepted["digest"])
        if value["version"] == 1:
            _require(value["predecessor_id"] is None)
        else:
            _id(value["predecessor_id"])
            _require(value["predecessor_id"] != value["id"])
        _require(_instant(value["uploaded_at"]) >= _instant(accepted["decided_at"]))
        _reference(value["original"])
        _reference(value["snapshot"], True)
        _require(value["original"]["object_id"] != value["snapshot"]["object_id"])
        _require(value["normalization_schema_version"] == "curve.local-upload.normalized/v1-candidate")
        _digest(value["digest"])
        _require(_pin(value) == value["digest"])
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise LocalDocumentUnavailable from None
    return deepcopy(value)


def create_plan_revision(
    *, submission, approval, initiative_version, version, predecessor_id, original, snapshot, uploaded_by, uploaded_at
):
    subject = validate_submission(submission)
    accepted = validate_decision(approval, subject)
    value = dict(
        schema_version=SCHEMA,
        id=str(uuid.uuid4()),
        workspace_id=subject["workspace_id"],
        initiative_id=subject["initiative_id"],
        initiative_version=initiative_version,
        version=version,
        predecessor_id=predecessor_id,
        prd_submission_id=subject["id"],
        prd_submission_digest=subject["digest"],
        prd_decision_id=accepted["id"],
        prd_decision_digest=accepted["digest"],
        original=deepcopy(original),
        snapshot=deepcopy(snapshot),
        normalization_schema_version="curve.local-upload.normalized/v1-candidate",
        uploaded_by=uploaded_by,
        uploaded_at=uploaded_at,
    )
    value["digest"] = _pin(value)
    return validate_plan_revision(value, submission=subject, approval=accepted)


SUBMISSION_SCHEMA = "curve.local-plan-submission/v1-candidate"
DECISION_SCHEMA = "curve.local-plan-decision/v1-candidate"
_SUBMISSION_FIELDS = {
    "schema_version",
    "id",
    "workspace_id",
    "initiative_id",
    "initiative_version",
    "plan_revision_id",
    "plan_revision_digest",
    "plan_version",
    "content_digest",
    "prd_submission_id",
    "prd_submission_digest",
    "prd_decision_id",
    "prd_decision_digest",
    "technical_gate_assignment_id",
    "technical_approver_id",
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
    "plan_submission_id",
    "plan_submission_digest",
    "plan_revision_id",
    "plan_revision_digest",
    "technical_gate_assignment_id",
    "state",
    "decided_by",
    "decided_at",
    "feedback",
    "digest",
}


def validate_plan_submission(value, *, plan, prd_submission, prd_approval):
    try:
        revision = validate_plan_revision(plan, submission=prd_submission, approval=prd_approval)
        _require(type(value) is dict and set(value) == _SUBMISSION_FIELDS)
        _require(value["schema_version"] == SUBMISSION_SCHEMA)
        _id(value["id"])
        _version(value["initiative_version"])
        _require(value["initiative_version"] >= revision["initiative_version"])
        for key in (
            "workspace_id",
            "initiative_id",
            "prd_submission_id",
            "prd_submission_digest",
            "prd_decision_id",
            "prd_decision_digest",
        ):
            _require(value[key] == revision[key])
        _require(value["plan_revision_id"] == revision["id"] and value["plan_revision_digest"] == revision["digest"])
        _require(type(value["plan_version"]) is int and value["plan_version"] == revision["version"])
        _require(value["content_digest"] == revision["snapshot"]["digest"])
        reviewer = prd_submission["reviewers"][0]
        _require(value["technical_gate_assignment_id"] == reviewer["gate_assignment_id"])
        _require(value["technical_approver_id"] == reviewer["approver_user_id"])
        _require(value["submitted_by"] == revision["uploaded_by"])
        _require(_instant(value["submitted_at"]) >= _instant(revision["uploaded_at"]))
        _digest(value["digest"])
        _require(_pin(value) == value["digest"])
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise LocalDocumentUnavailable from None
    return deepcopy(value)


def create_plan_submission(*, plan, prd_submission, prd_approval, initiative_version, submitted_by, submitted_at):
    revision = validate_plan_revision(plan, submission=prd_submission, approval=prd_approval)
    value = {
        key: revision[key]
        for key in (
            "workspace_id",
            "initiative_id",
            "prd_submission_id",
            "prd_submission_digest",
            "prd_decision_id",
            "prd_decision_digest",
        )
    }
    reviewer = prd_submission["reviewers"][0]
    value.update(
        schema_version=SUBMISSION_SCHEMA,
        id=str(uuid.uuid4()),
        initiative_version=initiative_version,
        plan_revision_id=revision["id"],
        plan_revision_digest=revision["digest"],
        plan_version=revision["version"],
        content_digest=revision["snapshot"]["digest"],
        technical_gate_assignment_id=reviewer["gate_assignment_id"],
        technical_approver_id=reviewer["approver_user_id"],
        submitted_by=submitted_by,
        submitted_at=submitted_at,
    )
    value["digest"] = _pin(value)
    return validate_plan_submission(value, plan=revision, prd_submission=prd_submission, prd_approval=prd_approval)


def validate_plan_decision(value, *, submission, plan, prd_submission, prd_approval):
    try:
        subject = validate_plan_submission(
            submission, plan=plan, prd_submission=prd_submission, prd_approval=prd_approval
        )
        _require(type(value) is dict and set(value) == _DECISION_FIELDS and value["schema_version"] == DECISION_SCHEMA)
        _id(value["id"])
        _version(value["initiative_version"])
        _require(value["initiative_version"] >= subject["initiative_version"])
        for key in (
            "workspace_id",
            "initiative_id",
            "plan_revision_id",
            "plan_revision_digest",
            "technical_gate_assignment_id",
        ):
            _require(value[key] == subject[key])
        _require(value["plan_submission_id"] == subject["id"] and value["plan_submission_digest"] == subject["digest"])
        _require(value["decided_by"] == subject["technical_approver_id"])
        _require(_instant(value["decided_at"]) >= _instant(subject["submitted_at"]))
        _require(value["state"] in {"APPROVED", "CHANGES_REQUESTED"})
        if value["state"] == "APPROVED":
            _require(value["feedback"] is None)
        else:
            _reference(value["feedback"])
            _require(value["feedback"]["media_type"] == "text/plain" and value["feedback"]["size_bytes"] <= 16384)
        _digest(value["digest"])
        _require(_pin(value) == value["digest"])
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise LocalDocumentUnavailable from None
    return deepcopy(value)


def create_plan_decision(
    *, submission, plan, prd_submission, prd_approval, initiative_version, state, decided_by, decided_at, feedback=None
):
    subject = validate_plan_submission(submission, plan=plan, prd_submission=prd_submission, prd_approval=prd_approval)
    value = {
        key: subject[key]
        for key in (
            "workspace_id",
            "initiative_id",
            "plan_revision_id",
            "plan_revision_digest",
            "technical_gate_assignment_id",
        )
    }
    value.update(
        schema_version=DECISION_SCHEMA,
        id=str(uuid.uuid4()),
        initiative_version=initiative_version,
        plan_submission_id=subject["id"],
        plan_submission_digest=subject["digest"],
        state=state,
        decided_by=decided_by,
        decided_at=decided_at,
        feedback=deepcopy(feedback),
    )
    value["digest"] = _pin(value)
    return validate_plan_decision(
        value, submission=subject, plan=plan, prd_submission=prd_submission, prd_approval=prd_approval
    )
