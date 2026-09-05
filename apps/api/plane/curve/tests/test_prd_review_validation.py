# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid
from copy import deepcopy

import pytest
from django.core.exceptions import ValidationError

from plane.curve.prd_metadata_validation import metadata_digest
from plane.curve.prd_review_validation import validate_checkpoint_subject, validate_review_subject


pytestmark = pytest.mark.unit
EARLY = "2026-01-01T00:00:00Z"
CAPTURED = "2026-01-01T00:01:00Z"
CUTOFF = "2026-01-01T00:02:00Z"
DECIDED = "2026-01-01T00:03:00Z"
LATER = "2026-01-01T00:04:00Z"
DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64


def uid():
    return str(uuid.uuid4())


@pytest.fixture
def graph():
    scope = dict(workspace_id=uid(), initiative_id=uid())
    author = dict(actor_type="HUMAN", actor_id=uid())
    binding = dict(
        schema_version="1.0",
        id=uid(),
        **scope,
        artifact_kind="PRD",
        provider_connection_id=uid(),
        provider_file_id="synthetic-document",
        provider_container_id="synthetic-container",
        canonical_url="https://example.invalid/document",
        current_provider_version="source-one",
        current_revision_id=None,
        current_modified_at=EARLY,
        synchronization_status="CURRENT",
        access_status="ALLOWED",
        last_reconciled_at=CAPTURED,
        version=1,
        created_by=author,
        created_at=EARLY,
    )
    version = dict(
        schema_version="1.0-candidate",
        id=uid(),
        **scope,
        artifact_id=uid(),
        version_number=1,
        state="SUBMITTED",
        body=dict(object_id=uid(), digest=DIGEST, size_bytes=123, media_type="application/json"),
        body_schema_id="curve.normalized-prd/v1-candidate",
        body_schema_version=1,
        body_digest=DIGEST,
        evidence_snapshot_id=uid(),
        parent_version_id=None,
        created_by=author,
        created_at=CAPTURED,
        generation_provenance=None,
        access_envelope_id=uid(),
        retention_policy_version_id=uid(),
    )
    snapshot = dict(
        schema_version="1.0-candidate",
        id=version["evidence_snapshot_id"],
        **scope,
        artifact_version_id=version["id"],
        created_at=CAPTURED,
        items=[],
    )
    snapshot["digest"] = metadata_digest(snapshot)
    checkpoint = dict(
        schema_version="1.0",
        id=uid(),
        **scope,
        external_document_binding_id=binding["id"],
        artifact_version_id=version["id"],
        checkpoint_number=1,
        checkpoint_type="SUBMITTED",
        provider_connection_id=binding["provider_connection_id"],
        provider_file_id=binding["provider_file_id"],
        provider_container_id=binding["provider_container_id"],
        provider_version="source-one",
        revision_id=None,
        normalized_content_ref=deepcopy(version["body"]),
        content_digest=DIGEST,
        normalization_schema_version=version["body_schema_id"],
        evidence_snapshot_id=snapshot["id"],
        access_evaluation_id=uid(),
        completeness_check_id=uid(),
        retention_policy_version_id=version["retention_policy_version_id"],
        access_envelope_id=version["access_envelope_id"],
        predecessor_id=None,
        submitted_or_approved_by=deepcopy(author),
        recorded_at=CAPTURED,
    )
    return dict(binding=binding, checkpoint=checkpoint, artifact_version=version, evidence_snapshot=snapshot)


@pytest.fixture
def review(graph):
    checkpoint = graph["checkpoint"]
    assignments = [
        dict(
            id=uid(),
            workspace_id=checkpoint["workspace_id"],
            initiative_id=checkpoint["initiative_id"],
            gate_type=kind,
            approver=dict(actor_type="HUMAN", actor_id=uid()),
            valid_from=EARLY,
            valid_until=None,
            delegation_reason=None,
        )
        for kind in ("PRD_APPROVAL", "PLAN_APPROVAL", "CODE_READINESS")
    ]
    decision = dict(
        schema_version="1.0",
        id=uid(),
        workspace_id=checkpoint["workspace_id"],
        initiative_id=checkpoint["initiative_id"],
        gate_assignment_id=assignments[0]["id"],
        checkpoint_id=checkpoint["id"],
        artifact_version_id=checkpoint["artifact_version_id"],
        content_digest=DIGEST,
        provider_version=checkpoint["provider_version"],
        evidence_snapshot_id=checkpoint["evidence_snapshot_id"],
        access_evaluation_id=uid(),
        policy_version_ids=[uid()],
        confirmed_risk_tier="STANDARD",
        state="APPROVED",
        decided_by=deepcopy(assignments[0]["approver"]),
        decided_at=DECIDED,
        provider_validation_cutoff=CUTOFF,
        rationale="Synthetic review rationale.",
    )
    return dict(
        checkpoint=checkpoint,
        decision=decision,
        assignments=assignments,
        active_human_ids=[assignment["approver"]["actor_id"] for assignment in assignments],
        authenticated_actor=deepcopy(decision["decided_by"]),
        current_checkpoint_id=checkpoint["id"],
        current_risk_tier="STANDARD",
        current_policy_version_ids=list(decision["policy_version_ids"]),
    )


def assert_denied(check, value, code):
    before = deepcopy(value)
    with pytest.raises(ValidationError) as error:
        check(**value)
    assert error.value.code == code
    assert value == before
    assert str(error.value) == str([code])


def test_checkpoint_preserves_inputs_and_returns_no_permission_grant(graph):
    before = deepcopy(graph)
    assert validate_checkpoint_subject(**graph) is None
    assert graph == before


@pytest.mark.parametrize("state", ["APPROVED", "CHANGES_REQUESTED", "REJECTED"])
def test_exact_human_decision_preserves_inputs_and_returns_no_permission_grant(review, state):
    review["decision"]["state"] = state
    before = deepcopy(review)
    assert validate_review_subject(**review) is None
    assert review == before


@pytest.mark.parametrize("target", ["binding", "artifact_version", "evidence_snapshot"])
@pytest.mark.parametrize("field", ["workspace_id", "initiative_id"])
def test_checkpoint_rejects_cross_scope(graph, target, field):
    graph[target][field] = uid()
    assert_denied(validate_checkpoint_subject, graph, "CHECKPOINT_SCOPE_MISMATCH")


@pytest.mark.parametrize("field", ["external_document_binding_id", "provider_connection_id", "provider_file_id"])
def test_checkpoint_rejects_source_substitution(graph, field):
    graph["checkpoint"][field] = uid()
    assert_denied(validate_checkpoint_subject, graph, "CHECKPOINT_BINDING_MISMATCH")


@pytest.mark.parametrize(
    "target,field",
    [
        ("checkpoint", "artifact_version_id"),
        ("checkpoint", "evidence_snapshot_id"),
        ("artifact_version", "evidence_snapshot_id"),
        ("evidence_snapshot", "artifact_version_id"),
    ],
)
def test_checkpoint_rejects_native_metadata_substitution(graph, target, field):
    graph[target][field] = uid()
    assert_denied(validate_checkpoint_subject, graph, "CHECKPOINT_ARTIFACT_MISMATCH")


@pytest.mark.parametrize(
    "field,value",
    [
        ("object_id", "00000000-0000-4000-8000-000000000001"),
        ("digest", OTHER_DIGEST),
        ("size_bytes", 124),
        ("media_type", "text/plain"),
    ],
)
def test_checkpoint_compares_entire_protected_reference(graph, field, value):
    graph["checkpoint"]["normalized_content_ref"][field] = value
    assert_denied(validate_checkpoint_subject, graph, "CHECKPOINT_OBJECT_MISMATCH")


@pytest.mark.parametrize("target,field", [("checkpoint", "content_digest"), ("artifact_version", "body_digest")])
def test_checkpoint_rejects_digest_substitution(graph, target, field):
    graph[target][field] = OTHER_DIGEST
    assert_denied(validate_checkpoint_subject, graph, "CHECKPOINT_OBJECT_MISMATCH")


def test_checkpoint_requires_exact_author(graph):
    graph["checkpoint"]["submitted_or_approved_by"]["actor_id"] = uid()
    assert_denied(validate_checkpoint_subject, graph, "CHECKPOINT_AUTHOR_MISMATCH")


@pytest.mark.parametrize("field", ["access_envelope_id", "retention_policy_version_id", "normalization_schema_version"])
def test_checkpoint_pins_normalization_and_policy_metadata(graph, field):
    graph["checkpoint"][field] = uid()
    assert_denied(validate_checkpoint_subject, graph, "CHECKPOINT_POLICY_MISMATCH")


def test_snapshot_digest_recomputed_before_review(graph):
    graph["evidence_snapshot"]["digest"] = OTHER_DIGEST
    assert_denied(validate_checkpoint_subject, graph, "CHECKPOINT_EVIDENCE_DIGEST_MISMATCH")


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("binding", "created_at", LATER),
        ("artifact_version", "created_at", EARLY),
        ("checkpoint", "recorded_at", EARLY),
    ],
)
def test_checkpoint_rejects_impossible_chronology(graph, target, field, value):
    graph[target][field] = value
    assert_denied(validate_checkpoint_subject, graph, "CHECKPOINT_CHRONOLOGY_INVALID")


@pytest.mark.parametrize(
    "field,value", [("predecessor_id", "00000000-0000-4000-8000-000000000001"), ("checkpoint_number", 2)]
)
def test_first_checkpoint_cannot_skip_lineage(graph, field, value):
    graph["checkpoint"][field] = value
    assert_denied(validate_checkpoint_subject, graph, "CHECKPOINT_PREDECESSOR_REQUIRED")


def successor(graph):
    previous = deepcopy(graph["checkpoint"])
    graph["predecessor"] = previous
    graph["checkpoint"].update(id=uid(), predecessor_id=previous["id"], checkpoint_number=2, recorded_at=LATER)
    graph["artifact_version"].update(id=uid(), parent_version_id=previous["artifact_version_id"], version_number=2)
    graph["checkpoint"]["artifact_version_id"] = graph["artifact_version"]["id"]
    graph["evidence_snapshot"].update(id=uid(), artifact_version_id=graph["artifact_version"]["id"])
    snapshot = graph["evidence_snapshot"]
    snapshot["digest"] = metadata_digest({key: value for key, value in snapshot.items() if key != "digest"})
    graph["checkpoint"]["evidence_snapshot_id"] = graph["artifact_version"]["evidence_snapshot_id"] = snapshot["id"]


def test_successor_may_have_unchanged_body_digest(graph):
    successor(graph)
    validate_checkpoint_subject(**graph)


@pytest.mark.parametrize("field", ["predecessor_id", "checkpoint_number"])
def test_successor_requires_exact_immediate_checkpoint(graph, field):
    successor(graph)
    graph["checkpoint"][field] = 3 if field == "checkpoint_number" else uid()
    assert_denied(validate_checkpoint_subject, graph, "CHECKPOINT_SEQUENCE_MISMATCH")


def test_successor_requires_native_artifact_parent(graph):
    successor(graph)
    graph["artifact_version"]["parent_version_id"] = uid()
    assert_denied(validate_checkpoint_subject, graph, "CHECKPOINT_SEQUENCE_MISMATCH")


def test_historical_checkpoint_preserves_capture_container_after_allowed_move(graph):
    graph["binding"]["provider_container_id"] = "synthetic-new-container"
    graph["binding"]["current_provider_version"] = "source-two"
    validate_checkpoint_subject(**graph)


@pytest.mark.parametrize(
    "field", ["checkpoint_id", "artifact_version_id", "content_digest", "provider_version", "evidence_snapshot_id"]
)
def test_review_rejects_any_changed_displayed_subject(review, field):
    review["decision"][field] = OTHER_DIGEST if field == "content_digest" else uid()
    assert_denied(validate_review_subject, review, "PRD_REVIEW_SUBJECT_MISMATCH")


def test_review_rejects_old_checkpoint_after_current_pointer_advances(review):
    review["current_checkpoint_id"] = uid()
    assert_denied(validate_review_subject, review, "PRD_REVIEW_SUBJECT_MISMATCH")


@pytest.mark.parametrize("field", ["workspace_id", "initiative_id"])
def test_review_rejects_cross_scope(review, field):
    review["decision"][field] = uid()
    assert_denied(validate_review_subject, review, "PRD_REVIEW_SCOPE_MISMATCH")


def test_review_requires_authenticated_actor(review):
    review["authenticated_actor"]["actor_id"] = uid()
    assert_denied(validate_review_subject, review, "PRD_REVIEW_ACTOR_MISMATCH")


def test_risk_changed_after_display_denies_review(review):
    review["current_risk_tier"] = "HIGH"
    assert_denied(validate_review_subject, review, "PRD_REVIEW_RISK_CHANGED")


@pytest.mark.parametrize("policies", [[], None, "untrusted", ["new-policy"], ["duplicate", "duplicate"]])
def test_policy_supersession_and_malformed_observations_deny_review(review, policies):
    review["current_policy_version_ids"] = policies
    assert_denied(validate_review_subject, review, "PRD_REVIEW_POLICY_CHANGED")


def test_policy_order_is_not_semantic(review):
    review["decision"]["policy_version_ids"].append(uid())
    review["current_policy_version_ids"] = list(reversed(review["decision"]["policy_version_ids"]))
    validate_review_subject(**review)


@pytest.mark.parametrize("count", [0, 1, 2, 4])
def test_review_requires_three_gates(review, count):
    review["assignments"] = (review["assignments"] * 2)[:count]
    assert_denied(validate_review_subject, review, "PRD_REVIEW_THREE_GATES_REQUIRED")


@pytest.mark.parametrize("field", ["id", "gate_type"])
def test_review_rejects_duplicate_gate_identity_or_type(review, field):
    review["assignments"][1][field] = review["assignments"][0][field]
    assert_denied(validate_review_subject, review, "PRD_REVIEW_EXACT_GATES_REQUIRED")


@pytest.mark.parametrize("index", [0, 1, 2])
def test_revoked_membership_on_any_gate_denies_review(review, index):
    review["active_human_ids"].remove(review["assignments"][index]["approver"]["actor_id"])
    assert_denied(validate_review_subject, review, "PRD_REVIEW_MEMBERSHIP_INVALID")


@pytest.mark.parametrize("field", ["workspace_id", "initiative_id"])
def test_assignment_must_belong_to_reviewed_initiative(review, field):
    review["assignments"][1][field] = uid()
    assert_denied(validate_review_subject, review, "PRD_REVIEW_MEMBERSHIP_INVALID")


@pytest.mark.parametrize("tier", ["STANDARD", "HIGH"])
def test_risk_requires_distinct_humans(review, tier):
    review["decision"]["confirmed_risk_tier"] = review["current_risk_tier"] = tier
    review["assignments"][1]["approver"] = deepcopy(review["assignments"][0]["approver"])
    assert_denied(validate_review_subject, review, "PRD_REVIEW_DISTINCT_HUMANS_REQUIRED")


def test_low_risk_allows_one_human_assigned_to_multiple_gates(review):
    review["decision"]["confirmed_risk_tier"] = review["current_risk_tier"] = "LOW"
    for assignment in review["assignments"]:
        assignment["approver"] = deepcopy(review["authenticated_actor"])
    validate_review_subject(**review)


@pytest.mark.parametrize(
    "field,value",
    [("provider_validation_cutoff", EARLY), ("provider_validation_cutoff", LATER), ("decided_at", CAPTURED)],
)
def test_review_requires_ordered_capture_access_and_decision_times(review, field, value):
    review["decision"][field] = value
    assert_denied(validate_review_subject, review, "PRD_REVIEW_CHRONOLOGY_INVALID")


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("field,value", [("valid_from", DECIDED), ("valid_until", CUTOFF), ("valid_until", DECIDED)])
def test_gate_validity_covers_validation_cutoff_through_decision(review, index, field, value):
    review["assignments"][index][field] = value
    assert_denied(validate_review_subject, review, "PRD_REVIEW_ASSIGNMENT_EXPIRED")


def test_assignment_validity_boundary(review):
    for assignment in review["assignments"]:
        assignment.update(valid_from=CUTOFF, valid_until=LATER)
    validate_review_subject(**review)


@pytest.mark.parametrize("index", [1, 2])
def test_another_gate_cannot_substitute_for_product_approver(review, index):
    review["decision"]["decided_by"] = deepcopy(review["assignments"][index]["approver"])
    review["authenticated_actor"] = deepcopy(review["decision"]["decided_by"])
    review["decision"]["gate_assignment_id"] = review["assignments"][index]["id"]
    assert_denied(validate_review_subject, review, "PRD_REVIEW_PRODUCT_APPROVER_REQUIRED")


def test_replaced_assignment_with_same_human_requires_redisplay(review):
    review["assignments"][0]["id"] = uid()
    assert_denied(validate_review_subject, review, "PRD_REVIEW_PRODUCT_APPROVER_REQUIRED")


@pytest.mark.parametrize("rationale", ["", " \n\t", "a" * 2001, None], ids=["empty", "blank", "too-long", "null"])
def test_review_rationale_schema_errors_do_not_echo_content(review, rationale):
    review["decision"]["rationale"] = rationale
    assert_denied(validate_review_subject, review, "PRD_METADATA_SCHEMA_INVALID")


@pytest.mark.parametrize("target", ["checkpoint", "decision"])
def test_review_rejects_inline_content_unknown_fields_without_echo(review, target):
    review[target]["body"] = "Synthetic private-looking content must never be echoed."
    assert_denied(validate_review_subject, review, "PRD_METADATA_SCHEMA_INVALID")


def test_service_identity_rejected_even_if_assigned(review):
    review["decision"]["decided_by"]["actor_type"] = "SERVICE"
    assert_denied(validate_review_subject, review, "PRD_METADATA_SCHEMA_INVALID")


def test_non_json_integer_cannot_pass_candidate_number_schema(graph):
    graph["checkpoint"]["checkpoint_number"] = 1.0
    assert_denied(validate_checkpoint_subject, graph, "PRD_METADATA_TYPE_INVALID")


def test_timezone_offsets_compare_instants(review):
    review["decision"]["provider_validation_cutoff"] = "2025-12-31T21:02:00-03:00"
    validate_review_subject(**review)
