# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Independent candidate contract pin; existing Initiative/PRD pins are unchanged."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from .policy_services import CurvePolicyResourceNotFound
from .services import sha256_digest

MANIFEST_DIGEST = "sha256:e30c1bc28c49650ea12c809dbbc579ed7d4248271a75a357827c06e7fa1f211f"


def validate_scope_contract(name, value):
    directory = Path(__file__).parent / "scope_proposal_candidate"
    try:
        raw = (directory / "manifest-v1.json").read_bytes()
        if sha256_digest(raw) != MANIFEST_DIGEST:
            raise ValueError
        manifest = json.loads(raw)
        raw = (directory / (name + ".schema.json")).read_bytes()
        if sha256_digest(raw) != manifest[name + ".schema.json"]:
            raise ValueError
        Draft202012Validator(json.loads(raw), format_checker=FormatChecker()).validate(value)
    except Exception:
        raise CurvePolicyResourceNotFound from None
