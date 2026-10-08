# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Independent pinned C2a contracts; no old schema or digest changes."""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from .prd_commands import PrdCommandError

SCHEMA_VERSION = "curve.scoped-prd/v1-candidate"
POLICY_EDITION = "EXACT_EXISTING_WORK_SCOPED_PRD_V1"
MANIFEST_DIGEST = "sha256:7543deddb9a56e29c3613b03823afb9cd5e9474dc8bb64016665657cee17b997"
MAX_COMMAND_BYTES = 65536
MAX_RECORD_BYTES = 262144
DIRECTORY = Path(__file__).parent / "scoped_prd_candidate"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def metadata_digest(value):
    return digest({key: item for key, item in value.items() if key != "digest"})


def require_contract_integrity():
    try:
        raw = (DIRECTORY / "manifest-v1.json").read_bytes()
        if "sha256:" + hashlib.sha256(raw).hexdigest() != MANIFEST_DIGEST:
            raise ValueError
        manifest = json.loads(raw)
        for name, expected in manifest.items():
            if "sha256:" + hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest() != expected:
                raise ValueError
        return manifest
    except Exception:
        raise PrdCommandError("SCOPED_PRD_CONTRACT_UNAVAILABLE", 503) from None


def validate_scoped_contract(name, value):
    require_contract_integrity()
    name = {
        key: "scoped-prd-" + key.lower() + "-v1" for key in ("Observation", "Readiness", "Subject", "Decision")
    }.get(name, name)
    try:
        if name.endswith(".schema.json"):
            name = name[:-12]
        if len(canonical(value)) > MAX_RECORD_BYTES:
            raise ValueError
        schema = json.loads((DIRECTORY / (name + ".schema.json")).read_bytes())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    except (ValidationError, ValueError, TypeError, UnicodeError, RecursionError):
        raise PrdCommandError("SCOPED_PRD_INVALID", 422) from None
    return value
