# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Protected metadata projection; no ORM, provider, protected bytes or mutations.

All collaborators are trusted in-process server adapters, never request JSON.
A read permission cannot authorize a command or protected rationale/body access.
"""

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Protocol

from jsonschema import Draft202012Validator, FormatChecker

from .prd_readiness import SUBJECT_FIELDS, require_current_prd_readiness, validate_prd_readiness_report


READ_ACTION = "CURVE.PRD.METADATA_READ"
READ_POLICY_KEY = "CURVE_PRD_METADATA_READ_POLICY"
READ_POLICY_DIGEST = "sha256:af25780728016bf6229baf6ea3172d3360b01289ec8881894601a3ad39713435"
_SCHEMA_PINS = {
    "prd-review-context-v1.schema.json": "d027e434643c4c63b395ee1c77cdd6a7e42a7eac8ee2d0f325a0efa1ec8bd332",
    "prd-review-context-input-v1.schema.json": "90aa24cac66851550e3044845b4bfea58d0f48fc8adb328bfe9cb0e3a438d62d",
}
_AUTHORITY_FIELDS = {
    "action",
    "policy_key",
    "policy_digest",
    "actor_id",
    "workspace_id",
    "initiative_id",
    "initiative_version",
    "snapshot_revision",
    "evaluated_at",
    "classification",
    "membership",
    "classification_access",
    "object_metadata",
    "source_metadata",
    "evidence_metadata",
    "explicit_deny",
}
_SCOPE_FIELDS = {"workspace_id", "initiative_id", "actor_id", "initiative_version"}
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9._~-]{1,512}\Z")
_GATES = {"PRD_APPROVAL", "PLAN_APPROVAL", "CODE_READINESS"}


class PrdReadUnavailable(PermissionError):
    def __init__(self):
        super().__init__("PRD_CONTEXT_UNAVAILABLE")


class PrdReadRuntime(Protocol):
    """Installed trusted adapter with no write/capture/command interface.

    observe must perform fresh current authorization, including source/evidence
    metadata and the entire allowlisted identity projection. snapshot_revision
    fences all mutable subject/assignment/access inputs, not just a DB version.
    read_metadata returns ONLY the closed DTO after successful authorization.
    is_current rechecks coherent current scope/revision with a strict bool result.
    A production adapter must qualify its revocation/consistency guarantees before
    activation. This interface is not that qualification or a permission grant.
    """

    def observe(self, *, scope: dict, evaluated_at: str) -> dict: ...

    def read_metadata(self, *, scope: dict, snapshot_revision: str) -> dict: ...

    def is_current(self, *, scope: dict, snapshot_revision: str) -> bool: ...


def _require(condition):
    if not condition:
        raise PrdReadUnavailable


def _closed(value, keys):
    return type(value) is dict and set(value) == set(keys)


def _time(value):
    _require(type(value) is str and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,3})?Z", value))
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _json(value, depth=0, budget=None):
    """Reject ORM objects/non-JSON authority and bound recursive input work."""
    budget = [0] if budget is None else budget
    budget[0] += 1
    _require(depth <= 20 and budget[0] <= 10000)
    if value is None or type(value) is bool:
        return
    if type(value) is str:
        _require(len(value) <= 2048)
        value.encode("utf-8", errors="strict")
    elif type(value) is int:
        _require(abs(value) <= 9007199254740991)
    elif type(value) is list:
        _require(len(value) <= 1000)
        for item in value:
            _json(item, depth + 1, budget)
    elif type(value) is dict:
        _require(all(type(key) is str for key in value))
        for key, item in value.items():
            _json(key, depth + 1, budget)
            _json(item, depth + 1, budget)
    else:
        raise PrdReadUnavailable


def _pinned_json(path, digest):
    _require(not path.is_symlink())
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == digest)
    return json.loads(raw)


def _validate_schema(value, name):
    _json(value)
    path = Path(__file__).parent / "prd_read_schemas" / name
    schema = _pinned_json(path, _SCHEMA_PINS[name])
    _require(Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(value))


def _same_scope(value, scope):
    return all(value[key] == scope[key] for key in ("workspace_id", "initiative_id"))


def _scope(value):
    _require(_closed(value, _SCOPE_FIELDS))
    _require(
        all(type(value[key]) is str and _UUID.fullmatch(value[key]) for key in _SCOPE_FIELDS - {"initiative_version"})
    )
    _require(type(value["initiative_version"]) is int and 0 < value["initiative_version"] <= 9007199254740991)


def _authorize(observation, scope, now):
    _json(observation)
    policy = _pinned_json(
        Path(__file__).parent / "prd_candidate_policy/prd-metadata-read-policy-v1.json",
        READ_POLICY_DIGEST.removeprefix("sha256:"),
    )
    _require(_closed(observation, _AUTHORITY_FIELDS))
    _require(
        observation["action"] == READ_ACTION
        and observation["policy_key"] == READ_POLICY_KEY
        and observation["policy_digest"] == READ_POLICY_DIGEST
        and all(type(observation[key]) is type(scope[key]) and observation[key] == scope[key] for key in _SCOPE_FIELDS)
        and observation["evaluated_at"] == now
        and observation["classification"] in policy["allowed_classifications"]
        and observation["explicit_deny"] is False
        and all(observation[key] == "ALLOW" for key in policy["required_current_checks"])
        and type(observation["snapshot_revision"]) is str
        and _TOKEN.fullmatch(observation["snapshot_revision"])
    )
    _time(now)


def _select(record, fields):
    return {key: deepcopy(record[key]) for key in fields}


def _envelope(envelope, fields):
    return {
        "availability": envelope["availability"],
        "metadata": _select(envelope["metadata"], fields) if envelope["metadata"] is not None else None,
    }


def _check_pointers(snapshot, scope, now):
    if snapshot["state"] == "PRD_REVIEW":
        _require(snapshot["current_checkpoint_id"] is not None and snapshot["controlling_decision_id"] is None)
    for name in ("binding", "checkpoint", "readiness", "decision"):
        record = snapshot[name]["metadata"]
        if record is not None:
            _require(_same_scope(record, scope))
    for name, pointer in (
        ("checkpoint", "current_checkpoint_id"),
        ("decision", "controlling_decision_id"),
        ("readiness", "current_readiness_report_id"),
    ):
        envelope = snapshot[name]
        if envelope["availability"] == "ABSENT":
            _require(snapshot[pointer] is None)
        elif envelope["availability"] == "PRESENT":
            _require(envelope["metadata"]["id"] == snapshot[pointer])
    binding, checkpoint, decision = (snapshot[name]["metadata"] for name in ("binding", "checkpoint", "decision"))
    if checkpoint is not None:
        _require(
            binding is not None
            and checkpoint["external_document_binding_id"] == binding["id"]
            and checkpoint["provider_file_id"] == binding["provider_file_id"]
            and _time(checkpoint["recorded_at"]) <= _time(now)
        )
    if decision is not None:
        _require(checkpoint is not None and decision["checkpoint_id"] == checkpoint["id"])
        _require(
            all(
                decision[key] == checkpoint[key]
                for key in (
                    "artifact_version_id",
                    "evidence_snapshot_id",
                    "provider_version",
                    "content_digest",
                )
            )
        )
        original = snapshot["decision_assignment"]
        _require(
            original is not None
            and _same_scope(original, scope)
            and original["id"] == decision["gate_assignment_id"]
            and original["gate_type"] == "PRD_APPROVAL"
            and original["approver"] == decision["decided_by"]
        )
        _require(
            _time(checkpoint["recorded_at"])
            <= _time(decision["provider_validation_cutoff"])
            <= _time(decision["decided_at"])
            <= _time(now)
            and _time(original["valid_from"]) <= _time(decision["provider_validation_cutoff"])
            and (original["valid_until"] is None or _time(decision["decided_at"]) < _time(original["valid_until"]))
        )


def _readiness(snapshot, now):
    envelope = snapshot["readiness"]
    if envelope["availability"] != "PRESENT":
        return {"availability": envelope["availability"], "metadata": None}
    report = envelope["metadata"]
    validate_prd_readiness_report(report)  # Reuse the pinned closed structural report validator.
    _require(_time(report["checked_at"]) <= _time(now))
    current = snapshot["current_readiness_subject"]
    applicability, reason = "UNVERIFIED", "CURRENT_OBSERVATION_UNAVAILABLE"
    if current is not None and snapshot["current_profile_digest"] is not None:
        _require(
            _same_scope(current, snapshot)
            and current["initiative_version"] == snapshot["initiative_version"]
            and current["id"] == snapshot["current_readiness_report_id"]
        )
        binding = snapshot["binding"]["metadata"]
        if binding is not None:
            _require(
                current["prd_binding_id"] == binding["id"]
                and current["provider_file_id"] == binding["provider_file_id"]
                and current["provider_version"] == binding["current_provider_version"]
            )
            if snapshot["current_profile_digest"] != report["profile_digest"]:
                applicability, reason = "STALE", "PROFILE_CHANGED"
            elif any(
                type(report[key]) is not type(current[key]) or report[key] != current[key] for key in SUBJECT_FIELDS
            ):
                applicability, reason = "STALE", "EXACT_SUBJECT_CHANGED"
            elif binding["synchronization_status"] != "CURRENT":
                applicability, reason = "UNVERIFIED", "BINDING_NOT_CURRENT"
            else:
                applicability, reason = "CURRENT", "EXACT_SUBJECT_MATCH"
                if report["status"] == "READY":
                    require_current_prd_readiness(report, current)
    return {
        "availability": "PRESENT",
        "metadata": {
            **_select(report, ("id", "schema_version", "status", "reasons", "checked_at", "profile_digest")),
            "applicability_scope": "NEW_SUBMISSION",
            "applicability": applicability,
            "applicability_reasons": [reason],
            "ready_for_submission": applicability == "CURRENT" and report["status"] == "READY",
        },
    }


def _reviewer(snapshot, scope, now):
    assignments = snapshot["assignments"]
    _require(all(_same_scope(item, scope) for item in assignments))
    product = [item for item in assignments if item["gate_type"] == "PRD_APPROVAL"]
    product = product[0] if len(product) == 1 else None
    valid = (
        len(assignments) == 3
        and len({item["id"] for item in assignments}) == 3
        and {item["gate_type"] for item in assignments} == _GATES
        and all(
            item["member_active"] is True
            and item["approver"]["actor_type"] == "HUMAN"
            and _time(item["valid_from"]) <= _time(now)
            and (item["valid_until"] is None or _time(now) < _time(item["valid_until"]))
            for item in assignments
        )
        and (snapshot["risk_tier"] == "LOW" or len({item["approver"]["actor_id"] for item in assignments}) == 3)
    )
    return {
        "assignment_id": product["id"] if product else None,
        "identity": deepcopy(product["approver"]) if product else None,
        "display_name": product["display_name"] if product else None,
        "validity": ("VALID" if valid else "INVALID") if product else "UNAVAILABLE",
        "reason_codes": [
            "CURRENT_ASSIGNMENT" if valid else "ASSIGNMENTS_INVALID" if product else "CURRENT_ASSIGNMENT_UNAVAILABLE"
        ],
        "requesting_human_is_reviewer": bool(
            valid and product and product["approver"]["actor_id"] == scope["actor_id"]
        ),
    }


def _project(snapshot, scope, now):
    _check_pointers(snapshot, scope, now)
    readiness, reviewer = _readiness(snapshot, now), _reviewer(snapshot, scope, now)
    capabilities = {}
    for action in ("submit", "approve", "request_changes", "reject"):
        reasons = ["COMMAND_RUNTIME_NOT_EVALUATED"]
        if reviewer["validity"] != "VALID":
            reasons.append("ASSIGNMENTS_INVALID")
        if action == "submit":
            if snapshot["state"] not in {"ALIGNING", "PRD_REVIEW"}:
                reasons.append("STATE_NOT_ALLOWED")
            if readiness["metadata"] is None or readiness["metadata"]["applicability"] != "CURRENT":
                reasons.append("READINESS_NOT_CURRENT")
            if readiness["metadata"] is not None and readiness["metadata"]["status"] == "BLOCKED":
                reasons.append("READINESS_BLOCKED")
        else:
            if snapshot["state"] != "PRD_REVIEW":
                reasons.append("STATE_NOT_ALLOWED")
            if snapshot["checkpoint"]["availability"] != "PRESENT":
                reasons.append("CHECKPOINT_UNAVAILABLE")
            if not reviewer["requesting_human_is_reviewer"]:
                reasons.append("CURRENT_REVIEWER_REQUIRED")
            if snapshot["controlling_decision_id"] is not None:
                reasons.append("ALREADY_DECIDED")
        capabilities[action] = {"available": False, "reason_codes": reasons, "evaluated_at": now}
    return {
        "schema_version": "curve.prd-review-context/v1-candidate",
        **_select(scope, ("workspace_id", "initiative_id", "initiative_version")),
        "state": snapshot["state"],
        "observed_at": now,
        "binding": _envelope(
            snapshot["binding"],
            (
                "id",
                "metadata_schema_version",
                "version",
                "synchronization_status",
                "last_reconciled_at",
            ),
        ),
        "checkpoint": _envelope(
            snapshot["checkpoint"],
            (
                "id",
                "metadata_schema_version",
                "checkpoint_number",
                "artifact_version_id",
                "evidence_snapshot_id",
                "provider_version",
                "content_digest",
                "recorded_at",
            ),
        ),
        "readiness": readiness,
        "reviewer": reviewer,
        "decision": _envelope(
            snapshot["decision"],
            (
                "id",
                "metadata_schema_version",
                "state",
                "gate_assignment_id",
                "checkpoint_id",
                "artifact_version_id",
                "evidence_snapshot_id",
                "provider_version",
                "content_digest",
                "confirmed_risk_tier",
                "decided_by",
                "decided_at",
            ),
        ),
        "capabilities": capabilities,
        "command_preconditions": {
            "initiative_version": snapshot["initiative_version"],
            "commandETag": f'"{snapshot["initiative_version"]}"',
        },
    }


def validate_review_context(value):
    """Closed response validation plus cross-field semantics, fixed failures only."""
    try:
        _validate_schema(value, "prd-review-context-v1.schema.json")
        version = value["initiative_version"]
        _require(value["command_preconditions"] == {"initiative_version": version, "commandETag": f'"{version}"'})
        _require(all(item["evaluated_at"] == value["observed_at"] for item in value["capabilities"].values()))
        if value["state"] == "PRD_REVIEW":
            _require(value["checkpoint"]["availability"] != "ABSENT" and value["decision"]["availability"] != "PRESENT")
        decision = value["decision"]["metadata"]
        checkpoint = value["checkpoint"]["metadata"]
        if decision is not None:
            _require(checkpoint is not None and decision["checkpoint_id"] == checkpoint["id"])
            _require(
                all(
                    decision[key] == checkpoint[key]
                    for key in (
                        "artifact_version_id",
                        "evidence_snapshot_id",
                        "provider_version",
                        "content_digest",
                    )
                )
            )
        report = value["readiness"]["metadata"]
        if report is not None:
            _require(
                report["ready_for_submission"] is (report["status"] == "READY" and report["applicability"] == "CURRENT")
            )
            reasons = {
                "CURRENT": {"EXACT_SUBJECT_MATCH"},
                "STALE": {"EXACT_SUBJECT_CHANGED", "PROFILE_CHANGED"},
                "UNVERIFIED": {"CURRENT_OBSERVATION_UNAVAILABLE", "BINDING_NOT_CURRENT"},
            }
            _require(report["applicability_reasons"][0] in reasons[report["applicability"]])
        return True
    except Exception:
        raise PrdReadUnavailable from None


def read_prd_review_context(*, resolve_scope, runtime: PrdReadRuntime, clock):
    """Authorize before selected metadata reads and freshly recheck before return.

    resolve_scope is server-owned: active authenticated human, active membership,
    workspace, exact Initiative and current aggregate version. Called twice.
    No client-supplied role, profile, grants, expected subject or version is used.
    """
    try:
        _require(
            callable(resolve_scope)
            and callable(clock)
            and all(callable(getattr(runtime, name, None)) for name in ("observe", "read_metadata", "is_current"))
        )
        scope = deepcopy(resolve_scope())
        _scope(scope)
        before_time = clock()
        before = deepcopy(runtime.observe(scope=deepcopy(scope), evaluated_at=before_time))
        _authorize(before, scope, before_time)
        revision = before["snapshot_revision"]
        snapshot = deepcopy(runtime.read_metadata(scope=deepcopy(scope), snapshot_revision=revision))
        _validate_schema(snapshot, "prd-review-context-input-v1.schema.json")
        _require(
            _same_scope(snapshot, scope)
            and snapshot["initiative_version"] == scope["initiative_version"]
            and snapshot["snapshot_revision"] == revision
        )
        final_time = clock()
        _require(_time(final_time) >= _time(before_time))
        fresh_scope = deepcopy(resolve_scope())
        _scope(fresh_scope)
        _require(fresh_scope == scope)
        after = deepcopy(runtime.observe(scope=deepcopy(scope), evaluated_at=final_time))
        _authorize(after, scope, final_time)
        _require(after["snapshot_revision"] == revision)
        _require(runtime.is_current(scope=deepcopy(scope), snapshot_revision=revision) is True)
        result = _project(snapshot, scope, final_time)
        validate_review_context(result)
        return result
    except Exception:
        # Schema, provider, resolver and protected-record diagnostics never escape.
        raise PrdReadUnavailable from None
