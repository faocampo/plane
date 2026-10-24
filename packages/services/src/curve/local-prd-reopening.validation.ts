// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import type { CurveExistingWorkInitiativeScope } from "@plane/types";
import { isCurveUuid, isCurveVersion, requireCurve, requireCurveDigest } from "./existing-work-validation";
import { decodeLocalSubmission, decodeLocalDecision, localReviewExact } from "./local-prd-review.validation";
import type { LocalSubmission, LocalDecision } from "./local-prd-review.validation";
export type LocalPrdReopening = {
  schema_version: "curve.local-prd-reopening/v1-candidate";
  id: string;
  workspace_id: string;
  initiative_id: string;
  initiative_version: number;
  source_id: string;
  source_digest: string;
  submission_id: string;
  submission_digest: string;
  decision_id: string;
  decision_digest: string;
  reopened_by: string;
  reopened_at: string;
  digest: string;
};
export type LocalPrdReopeningCurrent = {
  schema_version: "curve.local-prd-reopening-current/v1-candidate";
  initiative_version: number;
  initiative_state: string;
  can_reopen: boolean;
  reopening: LocalPrdReopening | null;
};
export async function decodeLocalPrdReopening(
  input: unknown,
  scope: CurveExistingWorkInitiativeScope,
  submission: LocalSubmission,
  decision: LocalDecision
): Promise<LocalPrdReopening> {
  const subject = await decodeLocalSubmission(submission, scope);
  const approval = await decodeLocalDecision(decision, scope, subject);
  requireCurve(approval.state === "APPROVED");
  const data: unknown = structuredClone(input);
  localReviewExact(
    data,
    "schema_version,id,workspace_id,initiative_id,initiative_version,source_id,source_digest,submission_id,submission_digest,decision_id,decision_digest,reopened_by,reopened_at,digest"
  );
  requireCurve(data.schema_version === "curve.local-prd-reopening/v1-candidate");
  requireCurve(data.workspace_id === scope.workspaceId && data.initiative_id === scope.initiativeId);
  requireCurve(isCurveUuid(data.id) && isCurveUuid(data.reopened_by) && isCurveVersion(data.initiative_version));
  requireCurve(
    data.initiative_version > approval.initiative_version &&
      data.source_id === subject.source_id &&
      data.source_digest === subject.source_digest &&
      data.submission_id === subject.id &&
      data.submission_digest === subject.digest &&
      data.decision_id === approval.id &&
      data.decision_digest === approval.digest
  );
  requireCurve(
    typeof data.reopened_at === "string" &&
      /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$/.test(data.reopened_at) &&
      Number.isFinite(Date.parse(data.reopened_at)) &&
      Date.parse(data.reopened_at) >= Date.parse(approval.decided_at)
  );
  requireCurve(typeof data.digest === "string" && /^sha256:[0-9a-f]{64}$/.test(data.digest));
  const { digest, ...value } = data;
  await requireCurveDigest(value, digest);
  return data as LocalPrdReopening;
}
