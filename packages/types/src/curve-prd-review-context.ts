/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// Read-only candidate wire types. Runtime decoding is required before use.
export type TCurvePrdHuman = { actor_type: "HUMAN"; actor_id: string };

export type TCurvePrdBinding = {
  id: string;
  metadata_schema_version: "1.0";
  version: number;
  synchronization_status:
    | "CURRENT"
    | "CHANGED_SINCE_SUBMISSION"
    | "CHANGED_SINCE_APPROVAL"
    | "ACCESS_REVOKED"
    | "MOVED_OUTSIDE_POLICY"
    | "DELETED"
    | "PROVIDER_UNAVAILABLE"
    | "RECONCILIATION_REQUIRED";
  last_reconciled_at: string | null;
};

export type TCurvePrdCheckpoint = {
  id: string;
  metadata_schema_version: "1.0" | "2.0";
  checkpoint_number: number;
  artifact_version_id: string;
  evidence_snapshot_id: string;
  provider_version: string;
  content_digest: string;
  recorded_at: string;
};

export type TCurvePrdDecision = {
  id: string;
  metadata_schema_version: "1.0-candidate" | "2.0-candidate";
  state: "APPROVED" | "CHANGES_REQUESTED" | "REJECTED";
  gate_assignment_id: string;
  checkpoint_id: string;
  artifact_version_id: string;
  evidence_snapshot_id: string;
  provider_version: string;
  content_digest: string;
  confirmed_risk_tier: "LOW" | "STANDARD" | "HIGH";
  decided_by: TCurvePrdHuman;
  decided_at: string;
};

export type TCurvePrdReadiness = {
  id: string;
  schema_version: "curve.prd-readiness/v1-candidate";
  status: "READY" | "BLOCKED";
  reasons: Array<
    | "PRD_SECTION_MISSING:executive_summary"
    | "PRD_SECTION_MISSING:problem_context"
    | "PRD_SECTION_MISSING:goals"
    | "PRD_SECTION_MISSING:non_goals"
    | "PRD_SECTION_MISSING:personas"
    | "PRD_SECTION_MISSING:workflow"
    | "PRD_SECTION_MISSING:requirements"
    | "PRD_SECTION_MISSING:gates"
    | "PRD_SECTION_MISSING:integrations"
    | "PRD_SECTION_MISSING:data_security"
    | "PRD_SECTION_MISSING:quality"
    | "PRD_SECTION_MISSING:rollout"
    | "PRD_SECTION_MISSING:kpis"
    | "PRD_SECTION_MISSING:acceptance"
    | "PRD_SECTION_MISSING:risks"
    | "PRD_SECTION_MISSING:assumptions"
    | "PRD_SECTION_MISSING:open_questions"
    | "PRD_SECTION_EMPTY:executive_summary"
    | "PRD_SECTION_EMPTY:problem_context"
    | "PRD_SECTION_EMPTY:goals"
    | "PRD_SECTION_EMPTY:non_goals"
    | "PRD_SECTION_EMPTY:personas"
    | "PRD_SECTION_EMPTY:workflow"
    | "PRD_SECTION_EMPTY:requirements"
    | "PRD_SECTION_EMPTY:gates"
    | "PRD_SECTION_EMPTY:integrations"
    | "PRD_SECTION_EMPTY:data_security"
    | "PRD_SECTION_EMPTY:quality"
    | "PRD_SECTION_EMPTY:rollout"
    | "PRD_SECTION_EMPTY:kpis"
    | "PRD_SECTION_EMPTY:acceptance"
    | "PRD_SECTION_EMPTY:risks"
    | "PRD_SECTION_EMPTY:assumptions"
    | "PRD_SECTION_EMPTY:open_questions"
    | "PRD_SECTION_DUPLICATE:executive_summary"
    | "PRD_SECTION_DUPLICATE:problem_context"
    | "PRD_SECTION_DUPLICATE:goals"
    | "PRD_SECTION_DUPLICATE:non_goals"
    | "PRD_SECTION_DUPLICATE:personas"
    | "PRD_SECTION_DUPLICATE:workflow"
    | "PRD_SECTION_DUPLICATE:requirements"
    | "PRD_SECTION_DUPLICATE:gates"
    | "PRD_SECTION_DUPLICATE:integrations"
    | "PRD_SECTION_DUPLICATE:data_security"
    | "PRD_SECTION_DUPLICATE:quality"
    | "PRD_SECTION_DUPLICATE:rollout"
    | "PRD_SECTION_DUPLICATE:kpis"
    | "PRD_SECTION_DUPLICATE:acceptance"
    | "PRD_SECTION_DUPLICATE:risks"
    | "PRD_SECTION_DUPLICATE:assumptions"
    | "PRD_SECTION_DUPLICATE:open_questions"
    | "IDEA_BRIEF_SECTION_MISSING:problem"
    | "IDEA_BRIEF_SECTION_MISSING:affected_users"
    | "IDEA_BRIEF_SECTION_MISSING:desired_outcomes"
    | "IDEA_BRIEF_SECTION_MISSING:non_goals"
    | "IDEA_BRIEF_SECTION_MISSING:constraints"
    | "IDEA_BRIEF_SECTION_MISSING:assumptions"
    | "IDEA_BRIEF_SECTION_MISSING:contradictions"
    | "IDEA_BRIEF_SECTION_MISSING:blockers"
    | "IDEA_BRIEF_SECTION_MISSING:unknowns"
    | "IDEA_BRIEF_SECTION_EMPTY:problem"
    | "IDEA_BRIEF_SECTION_EMPTY:affected_users"
    | "IDEA_BRIEF_SECTION_EMPTY:desired_outcomes"
    | "IDEA_BRIEF_SECTION_EMPTY:non_goals"
    | "IDEA_BRIEF_SECTION_EMPTY:constraints"
    | "IDEA_BRIEF_SECTION_EMPTY:assumptions"
    | "IDEA_BRIEF_SECTION_EMPTY:contradictions"
    | "IDEA_BRIEF_SECTION_EMPTY:blockers"
    | "IDEA_BRIEF_SECTION_EMPTY:unknowns"
    | "IDEA_BRIEF_SECTION_DUPLICATE:problem"
    | "IDEA_BRIEF_SECTION_DUPLICATE:affected_users"
    | "IDEA_BRIEF_SECTION_DUPLICATE:desired_outcomes"
    | "IDEA_BRIEF_SECTION_DUPLICATE:non_goals"
    | "IDEA_BRIEF_SECTION_DUPLICATE:constraints"
    | "IDEA_BRIEF_SECTION_DUPLICATE:assumptions"
    | "IDEA_BRIEF_SECTION_DUPLICATE:contradictions"
    | "IDEA_BRIEF_SECTION_DUPLICATE:blockers"
    | "IDEA_BRIEF_SECTION_DUPLICATE:unknowns"
    | "PRD_REQUIREMENT_ID_REQUIRED"
    | "PRD_REQUIREMENT_DUPLICATE"
    | "PRD_REQUIREMENT_EMPTY"
    | "PRD_ACCEPTANCE_ID_REQUIRED"
    | "PRD_ACCEPTANCE_DUPLICATE"
    | "PRD_ACCEPTANCE_EMPTY"
    | "PRD_ACCEPTANCE_TRACE_REQUIRED"
    | "PRD_ACCEPTANCE_UNKNOWN_REQUIREMENT"
    | "PRD_REQUIREMENT_UNCOVERED"
    | "READINESS_INVENTORY_STALE"
    | "READINESS_INVENTORY_INVALID"
    | "BLOCKERS_UNRESOLVED"
    | "ASSUMPTION_PLAN_REQUIRED"
  >;
  checked_at: string;
  profile_digest: string;
  applicability_scope: "NEW_SUBMISSION";
  applicability: "CURRENT" | "STALE" | "UNVERIFIED";
  applicability_reasons: Array<
    | "EXACT_SUBJECT_MATCH"
    | "EXACT_SUBJECT_CHANGED"
    | "PROFILE_CHANGED"
    | "CURRENT_OBSERVATION_UNAVAILABLE"
    | "BINDING_NOT_CURRENT"
  >;
  ready_for_submission: boolean;
};

export type TCurvePrdBindingEnvelope = {
  availability: "PRESENT" | "ABSENT" | "UNAVAILABLE";
  metadata: TCurvePrdBinding | null;
};

export type TCurvePrdCheckpointEnvelope = {
  availability: "PRESENT" | "ABSENT" | "UNAVAILABLE";
  metadata: TCurvePrdCheckpoint | null;
};

export type TCurvePrdDecisionEnvelope = {
  availability: "PRESENT" | "ABSENT" | "UNAVAILABLE";
  metadata: TCurvePrdDecision | null;
};

export type TCurvePrdReadinessEnvelope = {
  availability: "PRESENT" | "ABSENT" | "UNAVAILABLE";
  metadata: TCurvePrdReadiness | null;
};

export type TCurvePrdCapability = {
  available: false;
  reason_codes: Array<
    | "COMMAND_RUNTIME_NOT_EVALUATED"
    | "STATE_NOT_ALLOWED"
    | "READINESS_NOT_CURRENT"
    | "READINESS_BLOCKED"
    | "CHECKPOINT_UNAVAILABLE"
    | "CURRENT_REVIEWER_REQUIRED"
    | "ASSIGNMENTS_INVALID"
    | "ALREADY_DECIDED"
  >;
  evaluated_at: string;
};

export type TCurvePrdReviewer = {
  assignment_id: string | null;
  identity: TCurvePrdHuman | null;
  display_name: string | null;
  validity: "VALID" | "INVALID" | "UNAVAILABLE";
  reason_codes: Array<"CURRENT_ASSIGNMENT" | "ASSIGNMENTS_INVALID" | "CURRENT_ASSIGNMENT_UNAVAILABLE">;
  requesting_human_is_reviewer: boolean;
};

export type ICurvePrdReviewContext = {
  schema_version: "curve.prd-review-context/v1-candidate";
  workspace_id: string;
  initiative_id: string;
  initiative_version: number;
  state:
    | "DRAFT"
    | "ALIGNING"
    | "PRD_REVIEW"
    | "PLANNING"
    | "PLAN_REVIEW"
    | "EXECUTING"
    | "CODE_READINESS_REVIEW"
    | "READY_FOR_REPOSITORY_REVIEW"
    | "PAUSED"
    | "FAILED"
    | "CANCELLED";
  observed_at: string;
  binding: TCurvePrdBindingEnvelope;
  checkpoint: TCurvePrdCheckpointEnvelope;
  readiness: TCurvePrdReadinessEnvelope;
  decision: TCurvePrdDecisionEnvelope;
  reviewer: TCurvePrdReviewer;
  capabilities: {
    submit: TCurvePrdCapability;
    approve: TCurvePrdCapability;
    request_changes: TCurvePrdCapability;
    reject: TCurvePrdCapability;
  };
  command_preconditions: { initiative_version: number; commandETag: string };
};
