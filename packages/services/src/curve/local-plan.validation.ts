// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import type { CurveExistingWorkInitiativeScope } from "@plane/types";
import { requireCurve, requireCurveDigest, isCurveUuid, isCurveVersion } from "./existing-work-validation";
import { decodeLocalSubmission, decodeLocalDecision, localReviewExact } from "./local-prd-review.validation";
import type { LocalSubmission, LocalDecision } from "./local-prd-review.validation";
export type LocalPlanApproval = { prd_submission: LocalSubmission; prd_approval: LocalDecision };
export type LocalPlanReference = { object_id: string; digest: string; size_bytes: number; media_type: string };
export type LocalPlanRevision = {
  schema_version: "curve.local-plan-revision/v1-candidate";
  id: string;
  workspace_id: string;
  initiative_id: string;
  initiative_version: number;
  version: number;
  predecessor_id: string | null;
  prd_submission_id: string;
  prd_submission_digest: string;
  prd_decision_id: string;
  prd_decision_digest: string;
  original: LocalPlanReference;
  snapshot: LocalPlanReference;
  normalization_schema_version: "curve.local-upload.normalized/v1-candidate";
  uploaded_by: string;
  uploaded_at: string;
  digest: string;
};
export type LocalPlanSubmission = {
  schema_version: "curve.local-plan-submission/v1-candidate";
  id: string;
  workspace_id: string;
  initiative_id: string;
  initiative_version: number;
  plan_revision_id: string;
  plan_revision_digest: string;
  plan_version: number;
  content_digest: string;
  prd_submission_id: string;
  prd_submission_digest: string;
  prd_decision_id: string;
  prd_decision_digest: string;
  technical_gate_assignment_id: string;
  technical_approver_id: string;
  submitted_by: string;
  submitted_at: string;
  digest: string;
};
export type LocalPlanDecision = {
  schema_version: "curve.local-plan-decision/v1-candidate";
  id: string;
  workspace_id: string;
  initiative_id: string;
  initiative_version: number;
  plan_submission_id: string;
  plan_submission_digest: string;
  plan_revision_id: string;
  plan_revision_digest: string;
  technical_gate_assignment_id: string;
  state: "APPROVED" | "CHANGES_REQUESTED";
  decided_by: string;
  decided_at: string;
  feedback: LocalPlanReference | null;
  digest: string;
};
const digest = (v: unknown) => typeof v === "string" && /^sha256:[0-9a-f]{64}$/.test(v);
function instant(v: unknown): asserts v is string {
  requireCurve(
    typeof v === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$/.test(v) && Number.isFinite(Date.parse(v))
  );
}
function reference(v: unknown, media: string[], max: number): asserts v is LocalPlanReference {
  localReviewExact(v, "object_id,digest,size_bytes,media_type");
  requireCurve(
    isCurveUuid(v.object_id) &&
      digest(v.digest) &&
      isCurveVersion(v.size_bytes) &&
      v.size_bytes <= max &&
      media.includes(String(v.media_type))
  );
}
async function pinned(data: Record<string, unknown>) {
  requireCurve(digest(data.digest));
  const { digest: expected, ...metadata } = data;
  await requireCurveDigest(metadata, expected as string);
}
export async function decodeLocalPlanApproval(
  input: LocalPlanApproval,
  scope: CurveExistingWorkInitiativeScope
): Promise<LocalPlanApproval> {
  const prd_submission = await decodeLocalSubmission(input.prd_submission, scope);
  const prd_approval = await decodeLocalDecision(input.prd_approval, scope, prd_submission);
  requireCurve(prd_approval.state === "APPROVED");
  return { prd_submission, prd_approval };
}
/** Validate scoped immutable references before fetching a historical Product approval. */
export async function localPlanRevisionApprovalReferences(input: unknown, scope: CurveExistingWorkInitiativeScope) {
  const data: unknown = structuredClone(input);
  localReviewExact(
    data,
    "schema_version,id,workspace_id,initiative_id,initiative_version,version,predecessor_id,prd_submission_id,prd_submission_digest,prd_decision_id,prd_decision_digest,original,snapshot,normalization_schema_version,uploaded_by,uploaded_at,digest"
  );
  requireCurve(
    data.schema_version === "curve.local-plan-revision/v1-candidate" &&
      data.workspace_id === scope.workspaceId &&
      data.initiative_id === scope.initiativeId
  );
  requireCurve(isCurveUuid(data.prd_submission_id) && isCurveUuid(data.prd_decision_id));
  requireCurve(
    typeof data.prd_submission_digest === "string" &&
      /^sha256:[0-9a-f]{64}$/.test(data.prd_submission_digest) &&
      typeof data.prd_decision_digest === "string" &&
      /^sha256:[0-9a-f]{64}$/.test(data.prd_decision_digest)
  );
  await pinned(data);
  return {
    submissionId: data.prd_submission_id,
    submissionDigest: data.prd_submission_digest,
    decisionId: data.prd_decision_id,
    decisionDigest: data.prd_decision_digest,
  };
}

export async function decodeLocalPlanRevision(
  input: unknown,
  scope: CurveExistingWorkInitiativeScope,
  approval: LocalPlanApproval
): Promise<LocalPlanRevision> {
  const accepted = await decodeLocalPlanApproval(approval, scope);
  const data: unknown = structuredClone(input);
  localReviewExact(
    data,
    "schema_version,id,workspace_id,initiative_id,initiative_version,version,predecessor_id,prd_submission_id,prd_submission_digest,prd_decision_id,prd_decision_digest,original,snapshot,normalization_schema_version,uploaded_by,uploaded_at,digest"
  );
  requireCurve(
    data.schema_version === "curve.local-plan-revision/v1-candidate" &&
      data.normalization_schema_version === "curve.local-upload.normalized/v1-candidate"
  );
  requireCurve(data.workspace_id === scope.workspaceId && data.initiative_id === scope.initiativeId);
  requireCurve(
    isCurveUuid(data.id) &&
      isCurveUuid(data.uploaded_by) &&
      isCurveVersion(data.version) &&
      isCurveVersion(data.initiative_version) &&
      data.initiative_version > accepted.prd_approval.initiative_version
  );
  requireCurve(
    data.version === 1
      ? data.predecessor_id === null
      : isCurveUuid(data.predecessor_id) && data.predecessor_id !== data.id
  );
  requireCurve(
    data.prd_submission_id === accepted.prd_submission.id &&
      data.prd_submission_digest === accepted.prd_submission.digest &&
      data.prd_decision_id === accepted.prd_approval.id &&
      data.prd_decision_digest === accepted.prd_approval.digest
  );
  instant(data.uploaded_at);
  requireCurve(Date.parse(data.uploaded_at) >= Date.parse(accepted.prd_approval.decided_at));
  reference(data.original, ["application/pdf", "text/markdown", "text/plain"], 10485760);
  reference(data.snapshot, ["application/json"], 62918656);
  requireCurve(data.original.object_id !== data.snapshot.object_id);
  await pinned(data);
  return data as LocalPlanRevision;
}
export async function decodeLocalPlanSubmission(
  input: unknown,
  scope: CurveExistingWorkInitiativeScope,
  plan: LocalPlanRevision,
  approval: LocalPlanApproval
): Promise<LocalPlanSubmission> {
  const revision = await decodeLocalPlanRevision(plan, scope, approval);
  const data: unknown = structuredClone(input);
  localReviewExact(
    data,
    "schema_version,id,workspace_id,initiative_id,initiative_version,plan_revision_id,plan_revision_digest,plan_version,content_digest,prd_submission_id,prd_submission_digest,prd_decision_id,prd_decision_digest,technical_gate_assignment_id,technical_approver_id,submitted_by,submitted_at,digest"
  );
  requireCurve(
    data.schema_version === "curve.local-plan-submission/v1-candidate" &&
      isCurveUuid(data.id) &&
      isCurveVersion(data.initiative_version) &&
      data.initiative_version >= revision.initiative_version
  );
  for (const key of [
    "workspace_id",
    "initiative_id",
    "prd_submission_id",
    "prd_submission_digest",
    "prd_decision_id",
    "prd_decision_digest",
  ] as const)
    requireCurve(data[key] === revision[key]);
  requireCurve(
    data.plan_revision_id === revision.id &&
      data.plan_revision_digest === revision.digest &&
      data.plan_version === revision.version &&
      data.content_digest === revision.snapshot.digest &&
      data.submitted_by === revision.uploaded_by
  );
  requireCurve(
    data.technical_gate_assignment_id === approval.prd_submission.reviewers[0].gate_assignment_id &&
      data.technical_approver_id === approval.prd_submission.reviewers[0].approver_user_id
  );
  instant(data.submitted_at);
  requireCurve(Date.parse(data.submitted_at) >= Date.parse(revision.uploaded_at));
  await pinned(data);
  return data as LocalPlanSubmission;
}
export async function decodeLocalPlanDecision(
  input: unknown,
  scope: CurveExistingWorkInitiativeScope,
  plan: LocalPlanRevision,
  submission: LocalPlanSubmission,
  approval: LocalPlanApproval
): Promise<LocalPlanDecision> {
  const subject = await decodeLocalPlanSubmission(submission, scope, plan, approval);
  const data: unknown = structuredClone(input);
  localReviewExact(
    data,
    "schema_version,id,workspace_id,initiative_id,initiative_version,plan_submission_id,plan_submission_digest,plan_revision_id,plan_revision_digest,technical_gate_assignment_id,state,decided_by,decided_at,feedback,digest"
  );
  requireCurve(
    data.schema_version === "curve.local-plan-decision/v1-candidate" &&
      isCurveUuid(data.id) &&
      isCurveVersion(data.initiative_version) &&
      data.initiative_version >= subject.initiative_version
  );
  for (const key of [
    "workspace_id",
    "initiative_id",
    "plan_revision_id",
    "plan_revision_digest",
    "technical_gate_assignment_id",
  ] as const)
    requireCurve(data[key] === subject[key]);
  requireCurve(
    data.plan_submission_id === subject.id &&
      data.plan_submission_digest === subject.digest &&
      data.decided_by === subject.technical_approver_id
  );
  instant(data.decided_at);
  requireCurve(Date.parse(data.decided_at) >= Date.parse(subject.submitted_at));
  requireCurve(data.state === "APPROVED" || data.state === "CHANGES_REQUESTED");
  if (data.state === "APPROVED") requireCurve(data.feedback === null);
  else reference(data.feedback, ["text/plain"], 16384);
  await pinned(data);
  return data as LocalPlanDecision;
}
