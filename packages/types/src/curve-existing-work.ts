/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// Explicit candidate wire DTOs. All values require runtime validation before use.
// Source schemas are mirrored byte-for-byte in @plane/services/existing-work-contracts.

export type CurveProjectAssociationCreate = {
  provider_installation_id: string;
  source_project_id: string;
};

export type CurveProjectAssociationEnd = {
  expected_product_version: number;
  reason: string;
};

export type CurveProjectAssociation = {
  schema_version: "1.0";
  id: string;
  workspace_id: string;
  provider_installation_id: string;
  source_project_id: string;
  product_id: string;
  state: "ACTIVE" | "ENDED";
  version: number;
  effective_at: string;
  initiated_by: string;
  policy_edition: "EXPLICIT_EXISTING_PROJECT_ASSOCIATION_V1";
  command_receipt_id: string;
  source_observed_at: string;
  source_version: string;
  ended_at: string | null;
  ended_by: string | null;
  end_reason: string | null;
  end_receipt_id: string | null;
};

export type CurveScopeProposalReplace = {
  expected_scope_revision: number;
  items: Array<{
    association_id: string;
    association_version: number;
    source_issue_id: string;
    purpose: "CONTEXT_EVIDENCE" | "PROPOSED_DELIVERY";
  }>;
};

export type CurveScopeProposalRevision = {
  schema_version: "1.0";
  id: string;
  workspace_id: string;
  proposal_id: string;
  initiative_id: string;
  product_id: string;
  version: number;
  initiative_version: number;
  predecessor_id: string | null;
  item_count: number;
  delivery_count: number;
  membership_digest: string;
  created_by: string;
  recorded_at: string;
  policy_edition: "EXPLICIT_EXISTING_WORK_SCOPE_PROPOSAL_V1";
  command_receipt_id: string;
  controlling: false;
  items: Array<{
    association_id: string;
    association_version: number;
    source_issue_id: string;
    purpose: "CONTEXT_EVIDENCE" | "PROPOSED_DELIVERY";
    provider_installation_id: string;
    source_project_id: string;
    source_observed_at: string;
    source_version: string;
    source_fingerprint: string;
  }>;
};

export type CurveScopedPrdObserveV1 = {
  schema_version: "curve.scoped-prd/v1-candidate";
  policy_edition: "EXACT_EXISTING_WORK_SCOPED_PRD_V1";
  proposal_id: string;
  scope_revision_id: string;
  scope_revision: number;
  membership_digest: string;
};

export type CurveScopedPrdObservationV1 = {
  schema_version: "curve.scoped-prd/v1-candidate";
  policy_edition: "EXACT_EXISTING_WORK_SCOPED_PRD_V1";
  id: string;
  workspace_id: string;
  product_id: string;
  initiative_id: string;
  initiative_version: number;
  proposal_id: string;
  scope_revision_id: string;
  scope_revision: number;
  membership_digest: string;
  members: Array<{
    association_id: string;
    association_version: number;
    provider_installation_id: string;
    source_project_id: string;
    source_issue_id: string;
    purpose: "CONTEXT_EVIDENCE" | "PROPOSED_DELIVERY";
    source_version: string;
    source_fingerprint: string;
  }>;
  reviewers: Array<{
    gate_assignment_id: string;
    gate_type: "PRD_APPROVAL" | "PLAN_APPROVAL" | "CODE_READINESS";
    approver_user_id: string;
  }>;
  created_by: string;
  recorded_at: string;
  digest: string;
  controlling: false;
};

export type CurveScopedPrdSubjectV1 = {
  schema_version: "curve.scoped-prd/v1-candidate";
  policy_edition: "EXACT_EXISTING_WORK_SCOPED_PRD_V1";
  id: string;
  workspace_id: string;
  product_id: string;
  initiative_id: string;
  checkpoint_id: string;
  artifact_version_id: string;
  content_digest: string;
  provider_version: string;
  evidence_snapshot_id: string;
  proposal_id: string;
  scope_revision_id: string;
  scope_revision: number;
  membership_digest: string;
  observation_set_id: string;
  observation_digest: string;
  scoped_readiness_id: string;
  scoped_readiness_digest: string;
  members: Array<{
    association_id: string;
    association_version: number;
    provider_installation_id: string;
    source_project_id: string;
    source_issue_id: string;
    purpose: "CONTEXT_EVIDENCE" | "PROPOSED_DELIVERY";
  }>;
  created_by: string;
  recorded_at: string;
  digest: string;
  controlling: false;
};

export type CurveScopedPrdSubmitV1 = {
  schema_version: "curve.scoped-prd/v1-candidate";
  policy_edition: "EXACT_EXISTING_WORK_SCOPED_PRD_V1";
  external_document_binding_id: string;
  evidence_snapshot_id: string;
  completeness_check_id: string;
  proposal_id: string;
  scope_revision_id: string;
  scope_revision: number;
  membership_digest: string;
  observation_set_id: string;
  observation_digest: string;
};

export type CurveScopedPrdApproveV1 = {
  schema_version: "curve.scoped-prd/v1-candidate";
  policy_edition: "EXACT_EXISTING_WORK_SCOPED_PRD_V1";
  gate_assignment_id: string;
  checkpoint_id: string;
  artifact_version_id: string;
  content_digest: string;
  provider_version: string;
  evidence_snapshot_id: string;
  confirmed_risk_tier: "LOW" | "STANDARD" | "HIGH";
  rationale: string;
  scoped_subject_id: string;
  scoped_subject_digest: string;
};

export type CurveScopedPrdReturnV1 = {
  schema_version: "curve.scoped-prd/v1-candidate";
  policy_edition: "EXACT_EXISTING_WORK_SCOPED_PRD_V1";
  gate_assignment_id: string;
  checkpoint_id: string;
  artifact_version_id: string;
  content_digest: string;
  provider_version: string;
  evidence_snapshot_id: string;
  confirmed_risk_tier: "LOW" | "STANDARD" | "HIGH";
  decision: "CHANGES_REQUESTED" | "REJECTED";
  rationale: string;
  scoped_subject_id: string;
  scoped_subject_digest: string;
};

export type CurveExistingWorkProductScope = { workspaceId: string; productId: string };
export type CurveExistingWorkInitiativeScope = CurveExistingWorkProductScope & { initiativeId: string };
export type CurveExistingWorkMutation = { expectedVersion: number; idempotencyKey: string; signal?: AbortSignal };
export type CurveExistingWorkResult<T> = { data: T; etag: string };
export type CurveScopedPrdScopeV1 = Pick<
  CurveScopedPrdObserveV1,
  "proposal_id" | "scope_revision_id" | "scope_revision" | "membership_digest"
>;
export type CurveScopedPrdCheckpointV1 = Pick<
  CurveScopedPrdSubjectV1,
  "checkpoint_id" | "artifact_version_id" | "content_digest" | "provider_version" | "evidence_snapshot_id"
>;
// The acceptance envelope is the exact six-field projection in scoped_prd_views.py.
// Its ETag is the command's Initiative precondition, not the Operation's version.
export type CurveScopedPrdOperationAcceptance = {
  schema_version: "1.0";
  id: string;
  workspace_id: string;
  operation_type: "WORKFLOW_COMMAND";
  status:
    | "PENDING"
    | "QUEUED"
    | "RUNNING"
    | "WAITING_FOR_HUMAN"
    | "CANCEL_REQUESTED"
    | "SUCCEEDED"
    | "FAILED"
    | "CANCELLED";
  version: number;
};
