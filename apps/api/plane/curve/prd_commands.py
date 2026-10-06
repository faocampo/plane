# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Closed PRD command input and exact-subject preconditions.

Call after authentication and before durable acceptance. These pure checks grant
no authority and perform no provider or storage access. Recheck preconditions
under the final Initiative lock; replay must first reauthorize its original scope.
Rationale bytes remain transient until an independently authorized storage write.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError

from .prd_metadata_validation import MAX_SAFE_INTEGER, validate_external_record
from .prd_review_rationale import encode_review_rationale


MAX_COMMAND_BYTES = 65536
_SCHEMAS = {"submit": "Submit", "approve": "Approve", "return-for-revision": "ReturnForRevision"}


class PrdCommandError(ValueError):
    """Fixed public code and HTTP status, without request or schema diagnostics."""

    def __init__(self, code, status=422):
        self.code = code
        self.status = status
        super().__init__(code)


@dataclass(frozen=True)
class PrdCommand:
    action: str
    expected_version: int
    request_digest: str
    # All schema-approved subject values are scalar, so a tuple is deeply immutable.
    subject: tuple[tuple[str, str], ...] = field(repr=False)
    rationale_bytes: bytes | None = field(repr=False)
    idempotency_key: str = field(repr=False)

    def subject_metadata(self):
        return dict(self.subject)

    def operation_request_identity(self):
        """Canonical digest envelope for the existing Operation idempotency kernel.

        Includes the digest of the complete original command, including rationale,
        while keeping body bytes out of the durable command/Operation envelope.
        This envelope alone is insufficient to execute the command after restart.
        """
        return _canonical(
            {"action": self.action, "expected_version": self.expected_version, "request_digest": self.request_digest}
        )


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PrdCommandError("PRD_COMMAND_INVALID")
        result[key] = value
    return result


def parse_prd_command(*, route, body, if_match, idempotency_key):
    """Parse raw UTF-8 JSON so duplicate keys cannot disappear before validation.

    The candidate API uses a strong quoted numeric Initiative ETag. Legacy
    Initiative routes keep their separately versioned ETag representation.
    """
    if type(route) is not str or route not in _SCHEMAS:
        raise PrdCommandError("PRD_COMMAND_UNKNOWN", 404)
    if if_match is None:
        raise PrdCommandError("PRECONDITION_REQUIRED", 428)
    if type(if_match) is not str or len(if_match) > 18 or re.fullmatch(r'"[1-9][0-9]*"', if_match) is None:
        raise PrdCommandError("VERSION_CONFLICT", 412)
    expected_version = int(if_match[1:-1])
    if expected_version > MAX_SAFE_INTEGER:
        raise PrdCommandError("VERSION_CONFLICT", 412)
    if (
        type(idempotency_key) is not str
        or not 1 <= len(idempotency_key) <= 255
        or not idempotency_key.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in idempotency_key)
    ):
        raise PrdCommandError("IDEMPOTENCY_KEY_INVALID")
    try:
        idempotency_key.encode("utf-8", errors="strict")
    except UnicodeError:
        raise PrdCommandError("IDEMPOTENCY_KEY_INVALID") from None
    if type(body) is not bytes:
        raise PrdCommandError("PRD_COMMAND_INVALID")
    if len(body) > MAX_COMMAND_BYTES:
        raise PrdCommandError("PRD_COMMAND_TOO_LARGE", 413)
    try:
        payload = json.loads(body.decode("utf-8", errors="strict"), object_pairs_hook=_object)
        validate_external_record(_SCHEMAS[route], payload)
        rationale = encode_review_rationale(payload["rationale"]) if "rationale" in payload else None
        action = {
            "submit": "SUBMIT",
            "approve": "APPROVE",
            "return-for-revision": {"CHANGES_REQUESTED": "REQUEST_CHANGES", "REJECTED": "REJECT"}.get(
                payload.get("decision")
            ),
        }[route]
        action = f"CURVE.PRD.{action}"
        request_digest = (
            "sha256:"
            + hashlib.sha256(
                _canonical({"action": action, "expected_version": expected_version, "payload": payload})
            ).hexdigest()
        )
    except ValidationError as error:
        if error.code == "PRD_SCHEMA_INTEGRITY_FAILED":
            raise PrdCommandError("PRD_CONTRACT_UNAVAILABLE", 503) from None
        raise PrdCommandError("PRD_COMMAND_INVALID") from None
    except OSError:
        raise PrdCommandError("PRD_CONTRACT_UNAVAILABLE", 503) from None
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise PrdCommandError("PRD_COMMAND_INVALID") from None
    return PrdCommand(
        action=action,
        expected_version=expected_version,
        request_digest=request_digest,
        subject=tuple(sorted((key, value) for key, value in payload.items() if key != "rationale")),
        rationale_bytes=rationale,
        idempotency_key=idempotency_key,
    )


def check_prd_command_subject(*, command, initiative, binding=None, checkpoint=None, gate_assignment=None):
    """Use current same-workspace ORM records, after scoped authorization.

    Caller locks/reloads these records at the final commit fence. Submitted IDs
    for completeness/evidence still require current independently authorized
    record resolution; this check never treats their presence as readiness.
    """
    if type(command) is not PrdCommand:
        raise PrdCommandError("PRD_COMMAND_INVALID")
    if initiative.version != command.expected_version:
        raise PrdCommandError("VERSION_CONFLICT", 412)
    subject = command.subject_metadata()
    if command.action == "CURVE.PRD.SUBMIT":
        if initiative.state not in {"ALIGNING", "PRD_REVIEW"}:
            raise PrdCommandError("PRD_STATE_CONFLICT", 409)
        if (
            binding is None
            or binding.workspace_id != initiative.workspace_id
            or binding.initiative_id != initiative.id
            or str(binding.id) != subject["external_document_binding_id"]
        ):
            raise PrdCommandError("PRD_SUBJECT_CONFLICT", 409)
        return
    if command.action not in {"CURVE.PRD.APPROVE", "CURVE.PRD.REQUEST_CHANGES", "CURVE.PRD.REJECT"}:
        raise PrdCommandError("PRD_COMMAND_UNKNOWN", 404)
    if initiative.state != "PRD_REVIEW":
        raise PrdCommandError("PRD_STATE_CONFLICT", 409)
    if (
        checkpoint is None
        or gate_assignment is None
        or gate_assignment.workspace_id != initiative.workspace_id
        or gate_assignment.initiative_id != initiative.id
        or gate_assignment.gate_type != "PRD_APPROVAL"
        or str(gate_assignment.id) != subject["gate_assignment_id"]
        or checkpoint.workspace_id != initiative.workspace_id
        or checkpoint.initiative_id != initiative.id
        or checkpoint.id != initiative.current_prd_checkpoint_id
        or any(
            str(getattr(checkpoint, attribute)) != subject[key]
            for key, attribute in (
                ("checkpoint_id", "id"),
                ("artifact_version_id", "artifact_version_id"),
                ("content_digest", "content_digest"),
                ("provider_version", "provider_version"),
                ("evidence_snapshot_id", "evidence_snapshot_id"),
            )
        )
        or initiative.risk_tier != subject["confirmed_risk_tier"]
    ):
        raise PrdCommandError("PRD_SUBJECT_CONFLICT", 409)
