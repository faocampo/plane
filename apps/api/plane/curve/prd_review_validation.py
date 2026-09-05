# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Exact-subject checks for trusted server records before a PRD command commits.

These pure checks perform no authorization, provider reads, storage access or
lifecycle mutation. The command must load current scoped records under its
transaction/fence and independently validate current source/evidence access,
completeness and storage authority. Historical projections grant no permission.
Decision rationale stays in caller memory; failures expose fixed codes only.
"""

from datetime import datetime

from .prd_metadata_validation import (
    MAX_SAFE_INTEGER,
    metadata_digest,
    require_metadata,
    validate_external_record,
    validate_gate_record,
    validate_record,
)


def _time(value):
    # Called only after format validation. Fail closed for valid RFC3339 values
    # that the platform cannot represent (for example a leap second).
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require_metadata(result.utcoffset() is not None, "PRD_REVIEW_TIMESTAMP_INVALID")
        return result
    except (ValueError, OverflowError):
        require_metadata(False, "PRD_REVIEW_TIMESTAMP_INVALID")


def _scope(left, right):
    return left["workspace_id"] == right["workspace_id"] and left["initiative_id"] == right["initiative_id"]


def validate_checkpoint_subject(*, binding, checkpoint, artifact_version, evidence_snapshot, predecessor=None):
    """Verify one checkpoint against persisted native version/snapshot metadata.

    The version/snapshot repository remains responsible for exact evidence members
    and immutable artifact lineage. A predecessor here is the preceding checkpoint.
    Later allowed source-container moves preserve captured historical provenance.
    """
    validate_external_record("Binding", binding)
    validate_external_record("Checkpoint", checkpoint)
    validate_record("ArtifactVersion", artifact_version)
    validate_record("EvidenceSnapshot", evidence_snapshot)
    require_metadata(
        all(_scope(checkpoint, item) for item in (binding, artifact_version, evidence_snapshot)),
        "CHECKPOINT_SCOPE_MISMATCH",
    )
    require_metadata(
        checkpoint["external_document_binding_id"] == binding["id"]
        and checkpoint["provider_connection_id"] == binding["provider_connection_id"]
        and checkpoint["provider_file_id"] == binding["provider_file_id"],
        "CHECKPOINT_BINDING_MISMATCH",
    )
    require_metadata(
        checkpoint["artifact_version_id"] == artifact_version["id"] == evidence_snapshot["artifact_version_id"]
        and checkpoint["evidence_snapshot_id"] == artifact_version["evidence_snapshot_id"] == evidence_snapshot["id"],
        "CHECKPOINT_ARTIFACT_MISMATCH",
    )
    body = checkpoint["normalized_content_ref"]
    require_metadata(
        body == artifact_version["body"]
        and body["digest"] == checkpoint["content_digest"] == artifact_version["body_digest"]
        and body["media_type"] == "application/json"
        and 0 < body["size_bytes"] <= MAX_SAFE_INTEGER,
        "CHECKPOINT_OBJECT_MISMATCH",
    )
    require_metadata(
        checkpoint["submitted_or_approved_by"] == artifact_version["created_by"],
        "CHECKPOINT_AUTHOR_MISMATCH",
    )
    require_metadata(
        checkpoint["access_envelope_id"] == artifact_version["access_envelope_id"]
        and checkpoint["retention_policy_version_id"] == artifact_version["retention_policy_version_id"]
        and checkpoint["normalization_schema_version"] == artifact_version["body_schema_id"],
        "CHECKPOINT_POLICY_MISMATCH",
    )
    require_metadata(
        evidence_snapshot["digest"]
        == metadata_digest({key: value for key, value in evidence_snapshot.items() if key != "digest"}),
        "CHECKPOINT_EVIDENCE_DIGEST_MISMATCH",
    )
    require_metadata(
        _time(binding["created_at"]) <= _time(checkpoint["recorded_at"])
        and _time(evidence_snapshot["created_at"])
        <= _time(artifact_version["created_at"])
        <= _time(checkpoint["recorded_at"]),
        "CHECKPOINT_CHRONOLOGY_INVALID",
    )
    if predecessor is None:
        require_metadata(
            checkpoint["predecessor_id"] is None
            and checkpoint["checkpoint_number"] == 1
            and artifact_version["parent_version_id"] is None
            and artifact_version["version_number"] == 1,
            "CHECKPOINT_PREDECESSOR_REQUIRED",
        )
    else:
        validate_external_record("Checkpoint", predecessor)
        require_metadata(
            _scope(checkpoint, predecessor)
            and checkpoint["external_document_binding_id"] == predecessor["external_document_binding_id"]
            and checkpoint["provider_connection_id"] == predecessor["provider_connection_id"]
            and checkpoint["provider_file_id"] == predecessor["provider_file_id"],
            "CHECKPOINT_SCOPE_MISMATCH",
        )
        require_metadata(
            checkpoint["id"] != predecessor["id"]
            and checkpoint["predecessor_id"] == predecessor["id"]
            and checkpoint["checkpoint_number"] == predecessor["checkpoint_number"] + 1
            and artifact_version["id"] != predecessor["artifact_version_id"]
            and artifact_version["parent_version_id"] == predecessor["artifact_version_id"],
            "CHECKPOINT_SEQUENCE_MISMATCH",
        )
        require_metadata(
            _time(predecessor["recorded_at"]) <= _time(checkpoint["recorded_at"]),
            "CHECKPOINT_CHRONOLOGY_INVALID",
        )


def validate_review_subject(
    *,
    checkpoint,
    decision,
    assignments,
    active_human_ids,
    authenticated_actor,
    current_checkpoint_id,
    current_risk_tier,
    current_policy_version_ids,
):
    """Check exact decision subject against current server-derived observations.

    All inputs must be server-loaded or server-built. In particular active humans,
    the current pointer, policy versions and authenticated actor are never request
    body authority. The caller must revalidate them at the final transaction fence.
    Both negative outcomes review the immutable submission even after source edits;
    approval additionally requires stable live source/body validation by its caller.
    """
    validate_external_record("Checkpoint", checkpoint)
    validate_external_record("Decision", decision)
    require_metadata(_scope(checkpoint, decision), "PRD_REVIEW_SCOPE_MISMATCH")
    require_metadata(
        checkpoint["id"] == current_checkpoint_id == decision["checkpoint_id"]
        and all(
            checkpoint[key] == decision[key]
            for key in ("artifact_version_id", "content_digest", "provider_version", "evidence_snapshot_id")
        ),
        "PRD_REVIEW_SUBJECT_MISMATCH",
    )
    require_metadata(decision["decided_by"] == authenticated_actor, "PRD_REVIEW_ACTOR_MISMATCH")
    require_metadata(decision["confirmed_risk_tier"] == current_risk_tier, "PRD_REVIEW_RISK_CHANGED")
    require_metadata(
        type(current_policy_version_ids) is list
        and bool(current_policy_version_ids)
        and all(type(value) is str for value in current_policy_version_ids)
        and len(set(current_policy_version_ids)) == len(current_policy_version_ids)
        and set(decision["policy_version_ids"]) == set(current_policy_version_ids),
        "PRD_REVIEW_POLICY_CHANGED",
    )
    require_metadata(type(assignments) is list and len(assignments) == 3, "PRD_REVIEW_THREE_GATES_REQUIRED")
    for assignment in assignments:
        validate_gate_record(assignment)
    require_metadata(
        {assignment["gate_type"] for assignment in assignments} == {"PRD_APPROVAL", "PLAN_APPROVAL", "CODE_READINESS"}
        and len({assignment["id"] for assignment in assignments}) == 3,
        "PRD_REVIEW_EXACT_GATES_REQUIRED",
    )
    require_metadata(
        type(active_human_ids) is list
        and all(type(value) is str and value for value in active_human_ids)
        and all(
            _scope(assignment, checkpoint) and assignment["approver"]["actor_id"] in active_human_ids
            for assignment in assignments
        ),
        "PRD_REVIEW_MEMBERSHIP_INVALID",
    )
    if current_risk_tier in ("STANDARD", "HIGH"):
        require_metadata(
            len({assignment["approver"]["actor_id"] for assignment in assignments}) == 3,
            "PRD_REVIEW_DISTINCT_HUMANS_REQUIRED",
        )
    cutoff, decided = _time(decision["provider_validation_cutoff"]), _time(decision["decided_at"])
    require_metadata(_time(checkpoint["recorded_at"]) <= cutoff <= decided, "PRD_REVIEW_CHRONOLOGY_INVALID")
    require_metadata(
        all(
            _time(assignment["valid_from"]) <= cutoff
            and (assignment["valid_until"] is None or _time(assignment["valid_until"]) > decided)
            for assignment in assignments
        ),
        "PRD_REVIEW_ASSIGNMENT_EXPIRED",
    )
    product_gate = next(assignment for assignment in assignments if assignment["gate_type"] == "PRD_APPROVAL")
    require_metadata(
        product_gate["id"] == decision["gate_assignment_id"] and product_gate["approver"] == decision["decided_by"],
        "PRD_REVIEW_PRODUCT_APPROVER_REQUIRED",
    )
