// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import type {
  CurveExistingWorkInitiativeScope,
  CurveScopedPrdScopeV2,
  CurveScopedPrdCheckpointV2,
  CurveScopedPrdObservationV2,
  CurveScopedPrdSubjectV2,
} from "@plane/types";
import {
  validateCurveScopedPrdObservationV2,
  validateCurveScopedPrdSubjectV2,
} from "./existing-work-contracts/validators.mjs";
import {
  requireScopedExpectation,
  validateCurveWire,
  requireInitiative,
  requireCurveMatches,
  requireOrderedMembers,
  requireCurve,
  requireCurveDigest,
  isCurveUuid,
} from "./existing-work-validation";
export async function decodeCurveScopedPrdObservationV2(
  input: unknown,
  scope: CurveExistingWorkInitiativeScope,
  expected: CurveScopedPrdScopeV2 & Partial<Pick<CurveScopedPrdObservationV2, "id" | "digest" | "initiative_version">>
): Promise<CurveScopedPrdObservationV2> {
  requireScopedExpectation(expected);
  const data = validateCurveWire(validateCurveScopedPrdObservationV2, input);
  requireInitiative(data, scope);
  requireCurveMatches(data, expected);
  requireOrderedMembers(data.members);
  requireCurve(data.reviewers.map((item) => item.gate_type).join(",") === "PLAN_APPROVAL,PRD_APPROVAL");
  requireCurve(new Set(data.reviewers.map((item) => item.gate_assignment_id)).size === 2);
  const { digest, ...metadata } = data;
  await requireCurveDigest(metadata, digest);
  return data;
}
export async function decodeCurveScopedPrdSubjectV2(
  input: unknown,
  scope: CurveExistingWorkInitiativeScope,
  expected: CurveScopedPrdScopeV2 &
    CurveScopedPrdCheckpointV2 &
    Partial<Pick<CurveScopedPrdSubjectV2, "id" | "digest" | "observation_set_id" | "observation_digest">>
): Promise<CurveScopedPrdSubjectV2> {
  requireScopedExpectation(expected);
  requireCurve(
    isCurveUuid(expected.checkpoint_id) &&
      isCurveUuid(expected.artifact_version_id) &&
      isCurveUuid(expected.evidence_snapshot_id)
  );
  requireCurve(typeof expected.content_digest === "string" && /^sha256:[0-9a-f]{64}$/.test(expected.content_digest));
  requireCurve(typeof expected.provider_version === "string" && expected.provider_version.length > 0);
  const data = validateCurveWire(validateCurveScopedPrdSubjectV2, input);
  requireInitiative(data, scope);
  requireCurveMatches(data, expected);
  requireOrderedMembers(data.members);
  const { digest, ...metadata } = data;
  await requireCurveDigest(metadata, digest);
  return data;
}
