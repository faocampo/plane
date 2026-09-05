# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Exact rationale byte/reference conversion, after independent authorization.

No storage access or permission grant occurs here. Callers must validate current
source/evidence/rationale access, retention and object identity before returning
a reconstructed decision. Never log the input, decoded text or returned body.
"""

import hashlib
from copy import deepcopy

from django.core.exceptions import ValidationError

from .prd_metadata_validation import require_metadata, validate_external_record, validate_review_decision_record


RATIONALE_MEDIA_TYPE = "text/plain; charset=utf-8"
RATIONALE_METADATA_FIELDS = ("rationale_ref", "rationale_access_envelope_id", "rationale_retention_policy_version_id")


def encode_review_rationale(rationale):
    require_metadata(
        type(rationale) is str and 1 <= len(rationale) <= 2000 and bool(rationale.strip()), "PRD_RATIONALE_INVALID"
    )
    try:
        return rationale.encode("utf-8", errors="strict")
    except UnicodeError:
        raise ValidationError("PRD_RATIONALE_ENCODING_INVALID", code="PRD_RATIONALE_ENCODING_INVALID") from None


def _verify_bytes(reference, value):
    require_metadata(
        type(value) is bytes
        and len(value) == reference["size_bytes"]
        and "sha256:" + hashlib.sha256(value).hexdigest() == reference["digest"],
        "PRD_RATIONALE_OBJECT_MISMATCH",
    )


def review_decision_metadata(
    *, decision, rationale_ref, rationale_access_envelope_id, rationale_retention_policy_version_id
):
    validate_external_record("Decision", decision)
    metadata = {key: deepcopy(value) for key, value in decision.items() if key != "rationale"}
    metadata.update(
        schema_version="1.0-candidate",
        rationale_ref=deepcopy(rationale_ref),
        rationale_access_envelope_id=str(rationale_access_envelope_id),
        rationale_retention_policy_version_id=str(rationale_retention_policy_version_id),
    )
    validate_review_decision_record(metadata)
    _verify_bytes(metadata["rationale_ref"], encode_review_rationale(decision["rationale"]))
    return metadata


def review_decision_wire_record(*, metadata, rationale_bytes):
    validate_review_decision_record(metadata)
    _verify_bytes(metadata["rationale_ref"], rationale_bytes)
    try:
        rationale = rationale_bytes.decode("utf-8", errors="strict")
    except UnicodeError:
        raise ValidationError("PRD_RATIONALE_ENCODING_INVALID", code="PRD_RATIONALE_ENCODING_INVALID") from None
    require_metadata(encode_review_rationale(rationale) == rationale_bytes, "PRD_RATIONALE_OBJECT_MISMATCH")
    decision = {key: deepcopy(value) for key, value in metadata.items() if key not in RATIONALE_METADATA_FIELDS}
    decision.update(schema_version="1.0", rationale=rationale)
    validate_external_record("Decision", decision)
    return decision
