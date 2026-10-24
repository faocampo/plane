// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
/** Two-stage Product-review wire contracts. Historical editions retain their own types. */
export type CurveScopedPrdObserveV2 = {
  schema_version: "curve.scoped-prd/v2-candidate";
  policy_edition: "EXACT_EXISTING_WORK_SCOPED_PRD_V2";
  proposal_id: string;
  scope_revision_id: string;
  scope_revision: number;
  membership_digest: string;
};

export type CurveScopedPrdObservationV2 = {
  schema_version: "curve.scoped-prd/v2-candidate";
  policy_edition: "EXACT_EXISTING_WORK_SCOPED_PRD_V2";
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
    gate_type: "PRD_APPROVAL" | "PLAN_APPROVAL";
    approver_user_id: string;
  }>;
  created_by: string;
  recorded_at: string;
  digest: string;
  controlling: false;
};

export type CurveScopedPrdSubjectV2 = {
  schema_version: "curve.scoped-prd/v2-candidate";
  policy_edition: "EXACT_EXISTING_WORK_SCOPED_PRD_V2";
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

export type CurveScopedPrdSubmitV2 = {
  schema_version: "curve.scoped-prd/v2-candidate";
  policy_edition: "EXACT_EXISTING_WORK_SCOPED_PRD_V2";
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

export type CurveScopedPrdApproveV2 = {
  schema_version: "curve.scoped-prd/v2-candidate";
  policy_edition: "EXACT_EXISTING_WORK_SCOPED_PRD_V2";
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

export type CurveScopedPrdReturnV2 = {
  schema_version: "curve.scoped-prd/v2-candidate";
  policy_edition: "EXACT_EXISTING_WORK_SCOPED_PRD_V2";
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

export type CurveScopedPrdScopeV2 = Pick<
  CurveScopedPrdObserveV2,
  "proposal_id" | "scope_revision_id" | "scope_revision" | "membership_digest"
>;
export type CurveScopedPrdCheckpointV2 = Pick<
  CurveScopedPrdSubjectV2,
  "checkpoint_id" | "artifact_version_id" | "content_digest" | "provider_version" | "evidence_snapshot_id"
>;
