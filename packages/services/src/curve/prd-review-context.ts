/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ICurvePrdReviewContext } from "@plane/types";
import validateWire from "./prd-review-context.validator.mjs";

export class CurvePrdContextValidationError extends Error {
  constructor() {
    super("PRD review context could not be verified. Refresh the Initiative and try again.");
    this.name = "CurvePrdContextValidationError";
  }
}

export function decodeCurvePrdReviewContext(
  input: unknown,
  scope: { workspaceId: string; initiativeId: string; initiativeVersion: number }
): ICurvePrdReviewContext {
  const fail = (): never => {
    throw new CurvePrdContextValidationError();
  };
  if (!validateWire(input)) return fail();
  const context = input;
  if (
    context.workspace_id !== scope.workspaceId ||
    context.initiative_id !== scope.initiativeId ||
    context.initiative_version !== scope.initiativeVersion ||
    context.command_preconditions.initiative_version !== scope.initiativeVersion ||
    context.command_preconditions.commandETag !== `"${scope.initiativeVersion}"`
  )
    return fail();
  const checkpoint = context.checkpoint.metadata;
  const decision = context.decision.metadata;
  const readiness = context.readiness.metadata;
  if (decision) {
    if (
      !checkpoint ||
      decision.checkpoint_id !== checkpoint.id ||
      decision.artifact_version_id !== checkpoint.artifact_version_id ||
      decision.evidence_snapshot_id !== checkpoint.evidence_snapshot_id ||
      decision.provider_version !== checkpoint.provider_version ||
      decision.content_digest !== checkpoint.content_digest
    )
      return fail();
  }
  if (context.state === "PRD_REVIEW" && (context.checkpoint.availability === "ABSENT" || decision)) return fail();
  if (
    readiness &&
    readiness.ready_for_submission !== (readiness.status === "READY" && readiness.applicability === "CURRENT")
  )
    return fail();
  for (const capability of Object.values(context.capabilities)) {
    if (capability.evaluated_at !== context.observed_at) return fail();
  }
  if (readiness) {
    const reasons: Record<typeof readiness.applicability, readonly string[]> = {
      CURRENT: ["EXACT_SUBJECT_MATCH"],
      STALE: ["EXACT_SUBJECT_CHANGED", "PROFILE_CHANGED"],
      UNVERIFIED: ["CURRENT_OBSERVATION_UNAVAILABLE", "BINDING_NOT_CURRENT"],
    };
    if (!reasons[readiness.applicability].includes(readiness.applicability_reasons[0]!)) return fail();
  }
  if (context.reviewer.validity !== "VALID" && context.reviewer.requesting_human_is_reviewer) return fail();
  // Neither schema validation nor metadata reads grant command authority.
  return structuredClone(context);
}
