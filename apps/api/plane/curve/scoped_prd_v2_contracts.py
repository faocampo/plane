# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Pinned two-reviewer successor; original scoped records keep their edition."""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from .prd_commands import PrdCommandError
from .scoped_prd_contracts import MAX_RECORD_BYTES, canonical

SCHEMA_VERSION = "curve.scoped-prd/v2-candidate"
POLICY_EDITION = "EXACT_EXISTING_WORK_SCOPED_PRD_V2"
DIRECTORY = Path(__file__).parent / "scoped_prd_v2_candidate"
MANIFEST_DIGEST = "sha256:abf906b6cec6dd39ea128e56b87a75083cafb868923ea8fd549aaefeace22832"
CONTRACT_NAMES = frozenset(
    f"scoped-prd-{kind}-v2.schema.json"
    for kind in (
        "observation",
        "readiness",
        "subject",
        "decision",
        "observe",
        "submit",
        "approve",
        "return-for-revision",
        "observed-event",
    )
)


def require_contract_integrity():
    try:
        raw = (DIRECTORY / "manifest-v2.json").read_bytes()
        if "sha256:" + hashlib.sha256(raw).hexdigest() != MANIFEST_DIGEST:
            raise ValueError
        manifest = json.loads(raw)
        if set(manifest) != CONTRACT_NAMES | {"policy-v2.json"}:
            raise ValueError
        for name, expected in manifest.items():
            if "sha256:" + hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest() != expected:
                raise ValueError
        return manifest
    except Exception:
        raise PrdCommandError("SCOPED_PRD_CONTRACT_UNAVAILABLE", 503) from None


def validate_scoped_v2_contract(name, value):
    require_contract_integrity()
    name = {key: f"scoped-prd-{key.lower()}-v2" for key in ("Observation", "Readiness", "Subject", "Decision")}.get(
        name, name
    )
    if not name.endswith(".schema.json"):
        name += ".schema.json"
    try:
        if name not in CONTRACT_NAMES or len(canonical(value)) > MAX_RECORD_BYTES:
            raise ValueError
        schema = json.loads((DIRECTORY / name).read_bytes())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
        if name == "scoped-prd-observation-v2.schema.json":
            reviewers = value["reviewers"]
            if [item["gate_type"] for item in reviewers] != ["PLAN_APPROVAL", "PRD_APPROVAL"] or len(
                {item["gate_assignment_id"] for item in reviewers}
            ) != 2:
                raise ValueError
    except (ValidationError, ValueError, TypeError, UnicodeError, RecursionError):
        raise PrdCommandError("SCOPED_PRD_INVALID", 422) from None
    return value
