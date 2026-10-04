# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Explicit new-edition dispatcher; legacy parsers and digest history are untouched."""

from dataclasses import dataclass
import json

from .prd_commands import PrdCommand, PrdCommandError, _object, parse_prd_command
from .scoped_prd_contracts import SCHEMA_VERSION, MAX_COMMAND_BYTES, canonical, digest, validate_scoped_contract

EXTRA_FIELDS = frozenset(
    {
        "schema_version",
        "policy_edition",
        "proposal_id",
        "scope_revision_id",
        "scope_revision",
        "membership_digest",
        "observation_set_id",
        "observation_digest",
        "scoped_subject_id",
        "scoped_subject_digest",
    }
)


@dataclass(frozen=True)
class ScopedPrdCommand(PrdCommand):
    def legacy_command(self):
        return PrdCommand(
            self.action,
            self.expected_version,
            self.request_digest,
            tuple((key, value) for key, value in self.subject if key not in EXTRA_FIELDS),
            self.rationale_bytes,
            self.idempotency_key,
        )

    def operation_request_identity(self):
        return canonical(
            {
                "edition": SCHEMA_VERSION,
                "action": self.action,
                "expected_version": self.expected_version,
                "request_digest": self.request_digest,
            }
        )


def parse_scoped_prd_command(*, route, body, if_match, idempotency_key):
    if route not in {"observe", "submit", "approve", "return-for-revision"}:
        raise PrdCommandError("SCOPED_PRD_COMMAND_UNKNOWN", 404)
    if type(body) is not bytes:
        raise PrdCommandError("SCOPED_PRD_INVALID")
    if len(body) > MAX_COMMAND_BYTES:
        raise PrdCommandError("SCOPED_PRD_TOO_LARGE", 413)
    try:
        payload = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
        validate_scoped_contract(f"scoped-prd-{route}-v1", payload)
        legacy_payload = {key: value for key, value in payload.items() if key not in EXTRA_FIELDS}
        # Reuse exactly the legacy header/rationale validation without modifying its digest.
        if route == "observe":
            legacy_payload = {
                key: "00000000-0000-0000-0000-000000000001"
                for key in ("external_document_binding_id", "evidence_snapshot_id", "completeness_check_id")
            }
        base = parse_prd_command(
            route="submit" if route == "observe" else route,
            body=canonical(legacy_payload),
            if_match=if_match,
            idempotency_key=idempotency_key,
        )
        action = "CURVE.SCOPED_PRD.OBSERVE" if route == "observe" else base.action
        request_digest = digest(
            {"edition": SCHEMA_VERSION, "action": action, "expected_version": base.expected_version, "payload": payload}
        )
    except PrdCommandError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise PrdCommandError("SCOPED_PRD_INVALID") from None
    return ScopedPrdCommand(
        action,
        base.expected_version,
        request_digest,
        tuple(sorted((key, value) for key, value in payload.items() if key != "rationale")),
        base.rationale_bytes,
        idempotency_key,
    )


def validate_scoped_command(command, *, metadata_only=False):
    """Internal service callers must satisfy the same closed parser as HTTP."""
    if type(command) is not ScopedPrdCommand:
        raise PrdCommandError("SCOPED_PRD_INVALID")
    payload = command.subject_metadata()
    if command.action in {"CURVE.SCOPED_PRD.OBSERVE", "CURVE.PRD.SUBMIT"} and command.rationale_bytes is not None:
        raise PrdCommandError("SCOPED_PRD_INVALID")
    if command.action == "CURVE.SCOPED_PRD.OBSERVE":
        route = "observe"
    elif command.action == "CURVE.PRD.SUBMIT":
        route = "submit"
    elif command.action in {"CURVE.PRD.APPROVE", "CURVE.PRD.REQUEST_CHANGES", "CURVE.PRD.REJECT"}:
        route = "approve" if command.action == "CURVE.PRD.APPROVE" else "return-for-revision"
        if metadata_only and command.rationale_bytes is None:
            payload["rationale"] = "Validation placeholder"
        elif type(command.rationale_bytes) is bytes:
            try:
                payload["rationale"] = command.rationale_bytes.decode("utf-8", errors="strict")
            except UnicodeError:
                raise PrdCommandError("SCOPED_PRD_INVALID") from None
        else:
            raise PrdCommandError("SCOPED_PRD_INVALID")
    else:
        raise PrdCommandError("SCOPED_PRD_INVALID")
    parsed = parse_scoped_prd_command(
        route=route,
        body=canonical(payload),
        if_match=f'"{command.expected_version}"',
        idempotency_key=command.idempotency_key,
    )
    if (
        parsed.action != command.action
        or parsed.subject != command.subject
        or (not metadata_only and parsed.request_digest != command.request_digest)
    ):
        raise PrdCommandError("SCOPED_PRD_INVALID")
    return command
