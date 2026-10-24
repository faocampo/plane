# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Closed manual Gate 2 wire identities and immutable metadata projections."""

from dataclasses import dataclass
import json
from pathlib import Path
import re
import uuid

from jsonschema import Draft202012Validator, FormatChecker
from plane.curve.manual_plan_v3.validation import (
    canonical_json,
    digest,
    metadata_digest,
    parse_strict_json,
)

EDITION = "LOCAL_MANUAL_GATE2_RECONSTRUCTION_V3"
POLICY_KEY = "CURVE.LOCAL_MANUAL_GATE2_RECONSTRUCTION_V3"
DIRECTORY = Path(__file__).parent / "contract_snapshot"
MANIFEST_DIGEST = "sha256:3272d28ee28366a4f8364e44c252c46f9481eb886624afc4abafbd716204f682"
ACTIONS = frozenset({"PREPARE", "APPROVE", "REQUEST_CHANGES", "RECONCILE", "RELEASE"})
RESOURCE = "MANUAL_GATE2_RECORD_V3"
DESTINATION = "curve-local-manual-gate2-v3"


class Gate2Error(Exception):
    def __init__(self, code="UNAVAILABLE", status=404):
        self.code, self.status = code, status
        super().__init__(code)


def require(value, code="UNAVAILABLE", status=404):
    if not value:
        raise Gate2Error(code, status)


def uuid_text(value):
    try:
        result = str(uuid.UUID(str(value)))
        require(result == str(value))
        return result
    except (ValueError, TypeError):
        raise Gate2Error() from None


CONTRACT_FILES = frozenset(
    {
        "policy.json",
        "event.schema.json",
        "record.schema.json",
        "rationale.schema.json",
        "status.schema.json",
        "command.schema.json",
        "preparation.schema.json",
        "material.schema.json",
    }
)


def validate_manifest():
    try:
        require(not DIRECTORY.is_symlink(), "EDITION_UNAVAILABLE", 503)
        manifest_path = DIRECTORY / "manifest.json"
        require(not manifest_path.is_symlink(), "EDITION_UNAVAILABLE", 503)
        raw = manifest_path.read_bytes()
        require(digest(raw) == MANIFEST_DIGEST, "EDITION_UNAVAILABLE", 503)
        manifest = parse_strict_json(raw)
        require(type(manifest) is dict and set(manifest) == CONTRACT_FILES, "EDITION_UNAVAILABLE", 503)
        require({p.name for p in DIRECTORY.iterdir()} == CONTRACT_FILES | {"manifest.json"}, "EDITION_UNAVAILABLE", 503)
        for filename, expected in manifest.items():
            path = DIRECTORY / filename
            require(path.is_file() and not path.is_symlink(), "EDITION_UNAVAILABLE", 503)
            require(digest(path.read_bytes()) == expected, "EDITION_UNAVAILABLE", 503)
    except Gate2Error:
        raise
    except (OSError, ValueError):
        raise Gate2Error("EDITION_UNAVAILABLE", 503) from None


def validate(name, value):
    validate_manifest()
    require(name + ".schema.json" in CONTRACT_FILES, "EDITION_UNAVAILABLE", 503)
    schema = json.loads((DIRECTORY / (name + ".schema.json")).read_bytes())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)


def policy_digest():
    validate_manifest()
    return digest((DIRECTORY / "policy.json").read_bytes())


@dataclass(frozen=True)
class Command:
    initiative_id: uuid.UUID
    payload: dict
    expected_version: int
    key: str
    request_digest: str

    @property
    def action(self):
        return self.payload["action"]


def parse_command(*, initiative_id, raw, if_match, key):
    try:
        identifier = uuid_text(initiative_id)
        require(if_match is not None and key is not None, "PRECONDITION_REQUIRED", 428)
        matched = re.fullmatch(r'"curve-initiative:([0-9a-f-]{36}):v([1-9][0-9]{0,15})"', if_match)
        require(matched is not None and matched[1] == identifier, "INVALID_COMMAND", 422)
        version = int(matched[2])
        require(version <= 9007199254740991, "INVALID_COMMAND", 422)
        require(
            type(key) is str and 1 <= len(key) <= 500 and all(32 <= ord(c) <= 126 for c in key),
            "INVALID_COMMAND",
            422,
        )
        require(type(raw) is bytes and len(raw) <= 65536, "INPUT_TOO_LARGE", 413)
        payload = parse_strict_json(raw, max_bytes=65536)
        validate("command", payload)
        action = payload["action"]
        require(
            (payload["subject_ref"] is None) == (action == "PREPARE"),
            "INVALID_COMMAND",
            422,
        )
        require(
            (payload["rationale_ref"] is None) == (action == "PREPARE"),
            "INVALID_COMMAND",
            422,
        )
        require(
            (payload["reconciliation_ref"] is not None) == (action == "RELEASE"),
            "INVALID_COMMAND",
            422,
        )
        require(
            bool(payload["claims"]) == (action in {"RECONCILE", "RELEASE"}),
            "INVALID_COMMAND",
            422,
        )
        pairs = [(v["claim_id"], v["generation"]) for v in payload["claims"]]
        require(pairs == sorted(set(pairs)), "INVALID_COMMAND", 422)
        return Command(
            uuid.UUID(identifier),
            payload,
            version,
            key,
            digest(
                canonical_json(
                    dict(
                        initiative_id=identifier,
                        expected_version=version,
                        payload=payload,
                    )
                )
            ),
        )
    except Gate2Error:
        raise
    except Exception:
        raise Gate2Error("INVALID_COMMAND", 422) from None


def record_ref(record):
    return dict(
        resource_type=RESOURCE,
        resource_id=str(record.id),
        resource_version=record.version,
    )


def verify_record(record):
    payload = record.payload
    validate("record", payload)
    require(payload["digest"] == metadata_digest(payload) == record.digest)
    for key in (
        "id",
        "workspace_id",
        "product_id",
        "initiative_id",
        "subject_id",
        "draft_revision_id",
        "created_by",
        "policy_decision_id",
        "command_receipt_id",
    ):
        field = "actor_id" if key == "created_by" else key
        require(str(getattr(record, key)) == payload[field])
    require(record.version == payload["sequence"] and record.initiative_version == payload["initiative_version"])
    require(record.action == payload["action"] and record.subject_digest == payload["subject_digest"])
    require((None if record.predecessor_id is None else str(record.predecessor_id)) == payload["predecessor_id"])
    require(record.request_digest == payload["request_digest"])
    require(record.recorded_at.isoformat(timespec="microseconds").replace("+00:00", "Z") == payload["recorded_at"])
    return payload


def project_record(record):
    data = verify_record(record)
    # Original input identities, private authority receipts and material bodies are not metadata projections.
    return {
        key: data[key]
        for key in (
            "schema_version",
            "policy_edition",
            "id",
            "workspace_id",
            "product_id",
            "initiative_id",
            "sequence",
            "initiative_version",
            "action",
            "actor_id",
            "subject_id",
            "subject_digest",
            "draft_revision_id",
            "rationale_ref",
            "reconciliation_id",
            "claims",
            "recorded_at",
            "digest",
            "request_digest",
        )
    }


def verify_claim_subject(record):
    """Verify a competing reservation using its retained exact record edition."""
    edition = record.payload.get("schema_version")
    if edition == "curve.manual-gate2.record/v3-candidate":
        return verify_record(record)
    if edition == "curve.manual-gate2.record/v2-candidate":
        from plane.curve.manual_gate2_v2.contracts import verify_record as verify_historical

        return verify_historical(record)
    raise Gate2Error()
