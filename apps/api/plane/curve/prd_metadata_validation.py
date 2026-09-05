# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Closed, pinned metadata validation; no authorization or protected-body access."""

import hashlib
import json
from datetime import timezone
from functools import lru_cache
from pathlib import Path

from django.core.exceptions import ValidationError
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


SCHEMA_PINS = {
    "prd-review-decision-record-v1.schema.json": "2943f9f9eb3ed142533378deec224493be90d80da4fb26747d9b25508115e4bb",
    "external-prd-v1.schema.json": "f1bdd4ce2d037327b83d352c09e5373882f2b71475605e7fbb93f891ea012eb5",
    "access-envelope.schema.json": "eb6c978390675fc3042803ab4633052f7da49fc7a49305f9bf7ff8c284081dd1",
    "prd-artifact-records-v1.schema.json": "0e6047491c12d5833518e3a32be435ece5765836eb99ace8e82c933ad2411bcf",
}
SCHEMA_BASE = "https://curve.example.invalid/contracts/schemas/"
MAX_SAFE_INTEGER = 9007199254740991
EXISTING_SCHEMA_PINS = {
    "common.schema.json": "54b32643ee06d5458934c033a890b639d6c8f8a75346743ba8ef054320bfc3de",
    "gate-assignment.schema.json": "5b614728e2666698e188eaf325f47f000befa056cc514bd743e12e4807070e97",
    "product.schema.json": "ec4c08fe6c3ac71201ec80f7a5554f9c2161436a32687c5547c50735b1626a47",
}


def require_metadata(condition, code):
    if not condition:
        # Codes only: jsonschema diagnostics can contain protected source data.
        raise ValidationError(code, code=code)


def instant(value):
    require_metadata(value.tzinfo is not None and value.utcoffset() is not None, "PRD_TIMESTAMP_INVALID")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def metadata_digest(value):
    # Schema-constrained metadata uses bounded integers and fixed ASCII keys.
    # UTF-8 strings and array order match the candidate's canonical JSON digest.
    try:
        nodes = 0

        def check(node, depth=0):
            nonlocal nodes
            nodes += 1
            require_metadata(depth <= 100 and nodes <= 100000, "PRD_METADATA_LIMIT_EXCEEDED")
            if node is None or isinstance(node, (str, bool)):
                return
            if type(node) is int:
                require_metadata(abs(node) <= MAX_SAFE_INTEGER, "PRD_METADATA_INTEGER_INVALID")
                return
            if type(node) is list:
                for item in node:
                    check(item, depth + 1)
                return
            if type(node) is dict and all(type(key) is str for key in node):
                for item in node.values():
                    check(item, depth + 1)
                return
            require_metadata(False, "PRD_METADATA_TYPE_INVALID")

        check(value)
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ValidationError("PRD_METADATA_ENCODING_INVALID", code="PRD_METADATA_ENCODING_INVALID") from None


@lru_cache(maxsize=1)
def _registry():
    root = Path(__file__).parent
    resources = []
    for name, digest in EXISTING_SCHEMA_PINS.items():
        path = root / "contracts/schemas" / name
        require_metadata(not path.is_symlink(), "PRD_SCHEMA_INTEGRITY_FAILED")
        data = path.read_bytes()
        require_metadata(hashlib.sha256(data).hexdigest() == digest, "PRD_SCHEMA_INTEGRITY_FAILED")
        resources.append(json.loads(data))
    candidate_root = root / "prd_candidate_schemas"
    require_metadata(
        {path.name for path in candidate_root.iterdir()} == set(SCHEMA_PINS), "PRD_SCHEMA_INTEGRITY_FAILED"
    )
    for name, digest in SCHEMA_PINS.items():
        path = candidate_root / name
        require_metadata(not path.is_symlink(), "PRD_SCHEMA_INTEGRITY_FAILED")
        data = path.read_bytes()
        require_metadata(hashlib.sha256(data).hexdigest() == digest, "PRD_SCHEMA_INTEGRITY_FAILED")
        resources.append(json.loads(data))
    return Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in resources)


def validate_record(kind, value):
    _validate_reference("prd-artifact-records-v1.schema.json#/$defs/" + kind, value)


def validate_external_record(kind, value):
    _validate_reference("external-prd-v1.schema.json#/$defs/" + kind, value)


def validate_gate_record(value):
    _validate_reference("gate-assignment.schema.json", value)


def validate_review_decision_record(value):
    _validate_reference("prd-review-decision-record-v1.schema.json", value)


def _validate_reference(reference, value):
    # Bound input complexity and require JSON-safe integer values before walking
    # the schema. The digest is discarded; this is a validation-only boundary.
    metadata_digest(value)
    validator = Draft202012Validator(
        {"$ref": SCHEMA_BASE + reference},
        registry=_registry(),
        format_checker=FormatChecker(),
    )
    require_metadata(validator.is_valid(value), "PRD_METADATA_SCHEMA_INVALID")
