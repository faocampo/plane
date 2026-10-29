// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import type { CurveExistingWorkInitiativeScope, CurveItemScopeReference } from "@plane/types";
import {
  requireCurve,
  requireCurveDigest,
  isCurveUuid,
  isCurveVersion,
  validateCurveScope,
} from "./existing-work-validation";
export type LocalReviewAction = "SUBMIT" | "APPROVE" | "REQUEST_CHANGES";
type LocalSubmissionCommon = {
  id: string;
  workspace_id: string;
  initiative_id: string;
  initiative_version: number;
  source_id: string;
  source_version: number;
  source_digest: string;
  content_digest: string;
  reviewers: { gate_type: "PLAN_APPROVAL" | "PRD_APPROVAL"; gate_assignment_id: string; approver_user_id: string }[];
  risk_tier: "LOW" | "STANDARD" | "HIGH";
  submitted_by: string;
  submitted_at: string;
  digest: string;
};
export type LocalSubmission = LocalSubmissionCommon &
  (
    | {
        schema_version: "curve.local-prd-submission/v1-candidate";
        scope_revision_id: string;
        scope_revision: number;
        membership_digest: string;
      }
    | {
        schema_version: "curve.local-prd-submission/v2-candidate";
        product_id: string;
        product_version: number;
        business_intent: "STRATEGIC" | "CUSTOMER_COMMITMENT" | "BUSINESS_IMPROVEMENT" | "MANDATORY";
      }
    | {
        schema_version: "curve.local-prd-submission/v3-roadmap-candidate";
        product_id: string;
        product_version: number;
        business_intent: "STRATEGIC" | "CUSTOMER_COMMITMENT" | "BUSINESS_IMPROVEMENT" | "MANDATORY";
        roadmap_item_id: string;
        roadmap_item_scope: CurveItemScopeReference;
      }
  );
export type LocalDecision = {
  schema_version: "curve.local-prd-decision/v1-candidate";
  id: string;
  workspace_id: string;
  initiative_id: string;
  initiative_version: number;
  submission_id: string;
  submission_digest: string;
  source_id: string;
  source_digest: string;
  gate_assignment_id: string;
  state: "APPROVED" | "CHANGES_REQUESTED";
  decided_by: string;
  decided_at: string;
  feedback: { object_id: string; digest: string; size_bytes: number; media_type: "text/plain" } | null;
  digest: string;
};
export function localReviewExact(input: unknown, keys: string): asserts input is Record<string, unknown> {
  requireCurve(input !== null && typeof input === "object" && !Array.isArray(input));
  const expected = keys.split(",");
  requireCurve(Object.keys(input).length === expected.length && expected.every((key) => Object.hasOwn(input, key)));
}
const digest = (value: unknown) => typeof value === "string" && /^sha256:[0-9a-f]{64}$/.test(value);
function instant(value: unknown): asserts value is string {
  requireCurve(
    typeof value === "string" &&
      /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$/.test(value) &&
      Number.isFinite(Date.parse(value))
  );
}
export async function decodeLocalSubmission(
  input: unknown,
  scope: CurveExistingWorkInitiativeScope
): Promise<LocalSubmission> {
  validateCurveScope(scope);
  const data: unknown = structuredClone(input);
  requireCurve(typeof data === "object" && data !== null && !Array.isArray(data));
  const roadmap =
    (data as Record<string, unknown>).schema_version === "curve.local-prd-submission/v3-roadmap-candidate";
  const newWork =
    roadmap || (data as Record<string, unknown>).schema_version === "curve.local-prd-submission/v2-candidate";
  localReviewExact(
    data,
    "schema_version,id,workspace_id,initiative_id,initiative_version,source_id,source_version,source_digest,content_digest,reviewers,risk_tier,submitted_by,submitted_at,digest," +
      (newWork ? "product_id,product_version,business_intent" : "scope_revision_id,scope_revision,membership_digest") +
      (roadmap ? ",roadmap_item_id,roadmap_item_scope" : "")
  );
  requireCurve(newWork || data.schema_version === "curve.local-prd-submission/v1-candidate");
  requireCurve(data.workspace_id === scope.workspaceId && data.initiative_id === scope.initiativeId);
  for (const key of ["id", "source_id", "submitted_by"]) requireCurve(isCurveUuid(data[key]));
  for (const key of ["initiative_version", "source_version"]) requireCurve(isCurveVersion(data[key]));
  for (const key of ["source_digest", "content_digest", "digest"]) requireCurve(digest(data[key]));
  if (newWork) {
    requireCurve(
      data.product_id === scope.productId && isCurveUuid(data.product_id) && isCurveVersion(data.product_version)
    );
    requireCurve(
      ["STRATEGIC", "CUSTOMER_COMMITMENT", "BUSINESS_IMPROVEMENT", "MANDATORY"].includes(String(data.business_intent))
    );
  } else {
    requireCurve(
      isCurveUuid(data.scope_revision_id) && isCurveVersion(data.scope_revision) && digest(data.membership_digest)
    );
  }
  if (roadmap) {
    requireCurve(isCurveUuid(data.roadmap_item_id));
    const reference = data.roadmap_item_scope;
    localReviewExact(reference, "object_id,digest,size_bytes,media_type,editor_schema_version");
    requireCurve(isCurveUuid(reference.object_id) && digest(reference.digest));
    requireCurve(Number.isSafeInteger(reference.size_bytes) && Number(reference.size_bytes) >= 0);
    for (const [field, limit] of [
      ["media_type", 255],
      ["editor_schema_version", 100],
    ] as const) {
      const value = reference[field];
      requireCurve(typeof value === "string" && value.trim() === value && value.length > 0 && value.length <= limit);
    }
  }
  instant(data.submitted_at);
  requireCurve(["LOW", "STANDARD", "HIGH"].includes(String(data.risk_tier)));
  requireCurve(Array.isArray(data.reviewers) && data.reviewers.length === 2);
  data.reviewers.forEach((row: unknown, index: number) => {
    localReviewExact(row, "gate_type,gate_assignment_id,approver_user_id");
    requireCurve(
      row.gate_type === ["PLAN_APPROVAL", "PRD_APPROVAL"][index] &&
        isCurveUuid(row.gate_assignment_id) &&
        isCurveUuid(row.approver_user_id)
    );
  });
  requireCurve(data.reviewers[0].gate_assignment_id !== data.reviewers[1].gate_assignment_id);
  requireCurve(data.risk_tier === "LOW" || data.reviewers[0].approver_user_id !== data.reviewers[1].approver_user_id);
  const { digest: expected, ...metadata } = data;
  await requireCurveDigest(metadata, expected as string);
  return data as LocalSubmission;
}
export async function decodeLocalDecision(
  input: unknown,
  scope: CurveExistingWorkInitiativeScope,
  submission: LocalSubmission
): Promise<LocalDecision> {
  const subject = await decodeLocalSubmission(submission, scope);
  const data: unknown = structuredClone(input);
  localReviewExact(
    data,
    "schema_version,id,workspace_id,initiative_id,initiative_version,submission_id,submission_digest,source_id,source_digest,gate_assignment_id,state,decided_by,decided_at,feedback,digest"
  );
  requireCurve(data.schema_version === "curve.local-prd-decision/v1-candidate" && isCurveUuid(data.id));
  requireCurve(isCurveVersion(data.initiative_version) && data.initiative_version > subject.initiative_version);
  for (const key of ["workspace_id", "initiative_id", "source_id", "source_digest"] as const)
    requireCurve(data[key] === subject[key]);
  requireCurve(data.submission_id === subject.id && data.submission_digest === subject.digest);
  requireCurve(
    data.gate_assignment_id === subject.reviewers[1].gate_assignment_id &&
      data.decided_by === subject.reviewers[1].approver_user_id
  );
  instant(data.decided_at);
  requireCurve(Date.parse(data.decided_at) >= Date.parse(subject.submitted_at));
  requireCurve(data.state === "APPROVED" || data.state === "CHANGES_REQUESTED");
  if (data.state === "APPROVED") requireCurve(data.feedback === null);
  else {
    localReviewExact(data.feedback, "object_id,digest,size_bytes,media_type");
    requireCurve(
      isCurveUuid(data.feedback.object_id) &&
        digest(data.feedback.digest) &&
        isCurveVersion(data.feedback.size_bytes) &&
        data.feedback.size_bytes <= 16384 &&
        data.feedback.media_type === "text/plain"
    );
  }
  requireCurve(digest(data.digest));
  const { digest: expected, ...metadata } = data;
  await requireCurveDigest(metadata, expected as string);
  return data as LocalDecision;
}
