/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
/** Minimal advisory read edition. Eligibility never grants write authority. */
export type CurveScopeReopeningPreconditionsV1 = {
  schema_version: "curve.scope-reopening-precondition/v1-candidate";
  policy_edition: "EXPLICIT_SCOPE_REOPENING_PRECONDITION_READ_V1";
  workspace_id: string;
  initiative_id: string;
  initiative_version: number;
  expected_scope_revision: number;
  eligibility: "REOPENABLE" | "STATE_BLOCKED";
  pending_reopening: boolean;
};
export type CurveScopeReopeningReadTarget = {
  workspaceId: string;
  initiativeId: string;
  /** Optional known Initiative snapshot to reject a stale response; omitted for initial pin discovery. */
  expectedInitiativeVersion?: number;
};
