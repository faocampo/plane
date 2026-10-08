/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import type {
  CurveExistingWorkMutation,
  CurveExistingWorkProductScope,
  CurveExistingWorkResult,
  CurveProjectAssociation,
  CurveProjectAssociationCreate,
  CurveProjectAssociationPreconditionsV1,
} from "@plane/types";

export type AssociationProduct = {
  id: string;
  workspace_id: string;
  key: string;
  name: string;
  version: number;
  state: "ACTIVE";
};

/** Advisory discovery only. The command rechecks all current authorization. */
export type AssociationDiscovery = CurveProjectAssociationPreconditionsV1;

export type AssociationPort = {
  listProducts(slug: string, workspaceId: string, signal: AbortSignal): Promise<AssociationProduct[]>;
  discover(
    slug: string,
    scope: CurveExistingWorkProductScope,
    sourceProjectId: string,
    signal: AbortSignal
  ): Promise<AssociationDiscovery>;
  create(
    slug: string,
    scope: CurveExistingWorkProductScope,
    payload: CurveProjectAssociationCreate,
    options: CurveExistingWorkMutation
  ): Promise<CurveExistingWorkResult<CurveProjectAssociation>>;
};

export type AssociationIssue = "denied" | "conflict" | "unavailable" | "invalid" | "unknown";

export function associationIssue(error: unknown): AssociationIssue {
  const safe = error as { code?: string; status?: number; response?: { status?: number } } | null;
  const status = safe?.status ?? safe?.response?.status;
  if (status === 401 || status === 403 || status === 404) return "denied";
  if (safe?.code === "MUTATION_OUTCOME_UNKNOWN") return "unknown";
  if (safe?.code === "CONFLICT" || status === 409 || status === 412) return "conflict";
  if (safe?.code === "INVALID" || status === 400 || status === 422 || status === 428) return "invalid";
  return "unavailable";
}

export const associationMessages: Record<AssociationIssue, { title: string; detail: string }> = {
  denied: {
    title: "Access could not be verified",
    detail: "Protected details have been cleared. Refresh access before choosing a project and Product again.",
  },
  conflict: {
    title: "The relationship changed",
    detail:
      "Your choices are preserved. Check the current relationship and review it again before sending a new command.",
  },
  unavailable: {
    title: "Association is unavailable",
    detail:
      "Current availability could not be read. This does not mean the project is unassociated. Refresh to try again.",
  },
  invalid: {
    title: "The request could not be verified",
    detail: "Your choices are preserved. Read current availability and review the exact relationship again.",
  },
  unknown: {
    title: "The outcome is not confirmed",
    detail:
      "The server may have recorded this association. Retry the same request to recover its result; do not create another request.",
  },
};
