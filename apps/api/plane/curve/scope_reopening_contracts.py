# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Closed additive reopening contracts; frozen C1 and C2a contracts are untouched."""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from .prd_commands import PrdCommandError
from .scoped_prd_contracts import canonical, digest, metadata_digest

SCHEMA_VERSION = "curve.scope-reopening/v1-candidate"
POLICY_EDITION = "EXPLICIT_EXISTING_WORK_SCOPE_REOPENING_V1"
REVISION_EDITION = "REOPENED_EXISTING_WORK_SCOPE_PROPOSAL_V1"
ACTION = "CURVE.SCOPE.REOPEN_AND_REPLACE_SCOPE"
POLICY_DIGEST = "sha256:598e492b7dc23369eaf3029d7e208b4fd338d03d3e3388fcb10305e9c02b0094"
MANIFEST_DIGEST = "sha256:a16cca4313a159fb8297c9f7f90afbab5ab99c3574305f8be8ccd44eba2780df"
DIRECTORY = Path(__file__).parent / "scope_reopening_candidate"
MAX_COMMAND_BYTES = 65536
MAX_RECORD_BYTES = 262144


def require_reopening_contract_integrity():
    try:
        raw = (DIRECTORY / "manifest-v1.json").read_bytes()
        if "sha256:" + hashlib.sha256(raw).hexdigest() != MANIFEST_DIGEST:
            raise ValueError
        manifest = json.loads(raw)
        for name, expected in manifest.items():
            if "sha256:" + hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest() != expected:
                raise ValueError
    except Exception:
        raise PrdCommandError("SCOPE_REOPENING_CONTRACT_UNAVAILABLE", 503) from None


def validate_reopening_contract(name, value):
    require_reopening_contract_integrity()
    try:
        if len(canonical(value)) > MAX_RECORD_BYTES:
            raise ValueError
        schema = json.loads((DIRECTORY / (name + ".schema.json")).read_bytes())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    except Exception:
        raise PrdCommandError("SCOPE_REOPENING_INVALID", 422) from None
    return value


__all__ = ["SCHEMA_VERSION", "POLICY_EDITION", "REVISION_EDITION", "ACTION", "canonical", "digest", "metadata_digest"]
