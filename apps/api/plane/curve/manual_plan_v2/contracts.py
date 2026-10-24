# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Closed manual-draft commands and projections; no authority resolution."""

import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime

from .validation import (
    InvalidPlan,
    MAX_INTEGER,
    candidate_schemas,
    canonical_json,
    digest,
    metadata_digest,
    parse_strict_json,
    parse_typed_initiative_etag,
    validate_schema,
)

POLICY_EDITION = "LOCAL_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2"
POLICY_KEY = "CURVE_MANUAL_PLAN_DRAFT_POLICY_V2"
ACTION = "CURVE.MANUAL_PLAN_DRAFT.SAVE_V2"
EVENT_TYPE = "CURVE.MANUAL_PLAN_DRAFT_SAVED_V2"
OUTBOX_DESTINATION = "CURVE_MANUAL_PLAN_DRAFT_LOCAL_V2"
RESOURCE_TYPE = "MANUAL_PLAN_DRAFT_REVISION_V2"
EVENT_SCHEMA = "https://curve.example.invalid/candidates/manual-planning-v2/manual-plan-draft-event-v2.schema.json"
ERROR_STATUS = {
    "REQUEST_INVALID": 422,
    "PRECONDITION_REQUIRED": 428,
    "PRECONDITION_FAILED": 412,
    "REQUEST_TOO_LARGE": 413,
    "COMMAND_CONFLICT": 409,
    "UNAVAILABLE": 404,
    "EDITION_UNAVAILABLE": 503,
    "VALIDATION_UNAVAILABLE": 503,
    "VALIDATION_FAILED": 422,
}


class ManualPlanError(Exception):
    def __init__(self, suffix="UNAVAILABLE"):
        if suffix not in ERROR_STATUS:
            raise ValueError("Unsupported manual-plan error")
        self.code = "MANUAL_PLAN_DRAFT_" + suffix
        self.status_code = ERROR_STATUS[suffix]
        super().__init__(self.code)


def require(condition, suffix="UNAVAILABLE"):
    if not condition:
        raise ManualPlanError(suffix)


def validate(name, payload):
    try:
        schemas = candidate_schemas()
    except Exception:
        raise ManualPlanError("EDITION_UNAVAILABLE") from None
    try:
        validate_schema(name + ".schema.json", payload, schemas)
    except InvalidPlan:
        raise ManualPlanError("REQUEST_INVALID") from None


def policy_digest():
    from .validation import ROOT

    candidate_schemas()
    return digest((ROOT / "policy-v2.json").read_bytes())


@dataclass(frozen=True)
class SaveCommand:
    initiative_id: uuid.UUID
    expected_version: int
    key: str
    canonical_payload: bytes
    request_digest: str

    @property
    def payload(self):
        # Return a new tree so callers cannot mutate the captured identity.
        return parse_strict_json(self.canonical_payload)


def parse_save(*, initiative_id, raw, if_match, idempotency_key):
    require(type(raw) is bytes, "REQUEST_INVALID")
    require(len(raw) <= 65536, "REQUEST_TOO_LARGE")
    require(if_match is not None and idempotency_key is not None, "PRECONDITION_REQUIRED")
    require(type(idempotency_key) is str and 1 <= len(idempotency_key) <= 500, "REQUEST_INVALID")
    require(all(32 <= ord(char) <= 126 for char in idempotency_key), "REQUEST_INVALID")
    try:
        target = uuid.UUID(str(initiative_id))
        require(str(target) == str(initiative_id), "REQUEST_INVALID")
        version = parse_typed_initiative_etag(if_match, str(target))
        payload = parse_strict_json(raw)
    except (ValueError, TypeError, InvalidPlan):
        raise ManualPlanError("REQUEST_INVALID") from None
    validate("manual-plan-draft-save-v2", payload)
    identity = dict(payload=payload, initiative_id=str(target), expected_initiative_version=version)
    return SaveCommand(target, version, idempotency_key, canonical_json(payload), digest(canonical_json(identity)))


def resource_ref(revision):
    return dict(resource_type=RESOURCE_TYPE, resource_id=str(revision.id), resource_version=revision.version)


def build_revision(*, initiative, actor_id, draft_id, revision_id, previous, command, identity, receipt, recorded_at):
    """Construct closed persisted metadata only; this grants no write authority."""
    payload = command.payload
    require(initiative.id == command.initiative_id, "COMMAND_CONFLICT")
    require(type(initiative.version) is int and 1 <= initiative.version < MAX_INTEGER, "COMMAND_CONFLICT")
    require(initiative.version == command.expected_version, "PRECONDITION_FAILED")
    expected = previous.version if previous is not None else 0
    require(payload["expected_draft_revision"] == expected, "PRECONDITION_FAILED")
    validate("manual-plan-input-identity-v2", identity)
    validate("manual-plan-validation-receipt-v2", receipt)
    require(identity["digest"] == metadata_digest(identity), "VALIDATION_FAILED")
    require(receipt["digest"] == metadata_digest(receipt), "VALIDATION_FAILED")
    require(
        identity["workspace_id"] == str(initiative.workspace_id)
        and identity["initiative_id"] == str(initiative.id)
        and receipt["input_identity_digest"] == identity["digest"]
        and receipt["definition_digest"] == identity["definition_ref"]["digest"],
        "VALIDATION_FAILED",
    )
    for key in ("approved_subject_ref", "definition_ref", "manual_profile_ref"):
        require(payload[key] == identity[key], "VALIDATION_FAILED")
    if previous is not None:
        require(
            previous.workspace_id == initiative.workspace_id
            and previous.initiative_id == initiative.id
            and previous.product_id == initiative.product_id
            and previous.draft_id == draft_id
            and previous.initiative_version <= initiative.version
            and previous.recorded_at <= recorded_at,
            "COMMAND_CONFLICT",
        )
    require(isinstance(recorded_at, datetime) and recorded_at.utcoffset() is not None, "REQUEST_INVALID")
    data = dict(
        schema_version="curve.manual-plan-draft.revision/v2-candidate",
        policy_edition=POLICY_EDITION,
        id=str(revision_id),
        workspace_id=str(initiative.workspace_id),
        product_id=str(initiative.product_id),
        initiative_id=str(initiative.id),
        draft_id=str(draft_id),
        revision=expected + 1,
        initiative_version=initiative.version + 1,
        predecessor_id=str(previous.id) if previous is not None else None,
        approved_subject_ref=deepcopy(payload["approved_subject_ref"]),
        definition_ref=deepcopy(payload["definition_ref"]),
        manual_profile_ref=deepcopy(payload["manual_profile_ref"]),
        created_by=str(actor_id),
        recorded_at=recorded_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        controlling=False,
    )
    data["digest"] = metadata_digest(data)
    validate("manual-plan-draft-revision-v2", data)
    return data


def verify_revision(record):
    """Reject row/projection/private-receipt substitutions before any read."""
    data = deepcopy(record.payload)
    validate("manual-plan-draft-revision-v2", data)
    validate("manual-plan-input-identity-v2", record.original_input_identity)
    validate("manual-plan-validation-receipt-v2", record.validation_receipt)
    for key in ("id", "workspace_id", "initiative_id", "product_id", "draft_id", "created_by"):
        require(data[key] == str(getattr(record, key)))
    require(
        data["revision"] == record.version
        and data["initiative_version"] == record.initiative_version
        and data["predecessor_id"] == (str(record.predecessor_id) if record.predecessor_id else None)
        and datetime.fromisoformat(data["recorded_at"].replace("Z", "+00:00")) == record.recorded_at
        and metadata_digest(data) == data["digest"] == record.digest,
    )
    original, receipt = record.original_input_identity, record.validation_receipt
    require(
        original["digest"] == metadata_digest(original) == record.input_identity_digest
        and original["workspace_id"] == data["workspace_id"]
        and original["initiative_id"] == data["initiative_id"]
        and receipt["digest"] == metadata_digest(receipt) == record.validation_receipt_digest
        and receipt["input_identity_digest"] == record.input_identity_digest
        and receipt["definition_digest"] == data["definition_ref"]["digest"],
    )
    for key in ("approved_subject_ref", "definition_ref", "manual_profile_ref"):
        require(data[key] == original[key])
    return data


def event_payload(revision):
    data = dict(
        schema_version="curve.manual-plan-draft.event/v2-candidate",
        policy_edition=POLICY_EDITION,
        event_type=EVENT_TYPE,
        workspace_id=str(revision.workspace_id),
        initiative_id=str(revision.initiative_id),
        draft_id=str(revision.draft_id),
        revision_id=str(revision.id),
        revision_digest=revision.digest,
        definition_digest=revision.payload["definition_ref"]["digest"],
        input_identity_digest=revision.input_identity_digest,
        policy_decision_id=str(revision.policy_decision_id),
        controlling=False,
    )
    validate("manual-plan-draft-event-v2", data)
    return data
