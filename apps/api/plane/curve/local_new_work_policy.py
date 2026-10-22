# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Pinned successor policy identities for unscoped new-Initiative documents."""

import hashlib
from pathlib import Path
from .prd_commands import PrdCommandError

POLICIES = {
    "CURVE_LOCAL_PRD_POLICY": (
        "local-prd-policy-v2.json",
        "sha256:ca91f9a19b2203245c6a70d99305b2a6db3697af13f98c7aeaf6f648a3a97be9",
    ),
    "CURVE_LOCAL_PRD_REVIEW_POLICY": (
        "local-prd-review-policy-v2.json",
        "sha256:f5a26189960ebb3a5657cb5a7857f4060f44eff3e217e598bb500273718f0c4a",
    ),
    "CURVE_LOCAL_PLAN_UPLOAD_POLICY": (
        "local-plan-upload-policy-v2.json",
        "sha256:5d661c02789d1ecc761adc3864ef670e868aa6cef77f0c7dc9202d64a9df9ae3",
    ),
    "CURVE_LOCAL_PLAN_REVIEW_POLICY": (
        "local-plan-review-policy-v2.json",
        "sha256:e98a45e07f35cb297a6f7766b05ecea5bd67c2ad91facab2a8f4a37197194b3b",
    ),
    "CURVE_LOCAL_PRD_REOPENING_POLICY": (
        "local-prd-reopening-policy-v2.json",
        "sha256:f2021762aef38835aa7e9807cef415293f3ee2cb79705f6a7dc9033d02eee354",
    ),
}


def policy_identity(context, key, historical_digest):
    if context.head is not None:
        return 1, historical_digest
    name, digest = POLICIES[key]
    path = Path(__file__).parent / "two_stage_review" / name
    if path.is_symlink() or "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise PrdCommandError("LOCAL_NEW_WORK_POLICY_UNAVAILABLE", 503)
    return 2, digest
