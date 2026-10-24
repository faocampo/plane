/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 */
/** Manual draft candidate metadata. No approval or execution authority. */
export type ManualPlanTargetV3 = {
  workspaceSlug: string;
  workspaceId: string;
  productId: string;
  initiativeId: string;
};
export type ManualPlanRefV3 = { entity_id: string; digest: string };
export type ManualPlanDefinitionRefV3 = {
  object_id: string;
  digest: string;
  size_bytes: number;
  media_type: "application/json";
};
export type ManualPlanSaveV3 = {
  schema_version: "curve.manual-plan-draft.save/v3-candidate";
  policy_edition: "LOCAL_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V3";
  expected_draft_revision: number;
  approved_subject_ref: ManualPlanRefV3;
  definition_ref: ManualPlanDefinitionRefV3;
  manual_profile_ref: ManualPlanRefV3;
};
export type ManualPlanStatusV3 = {
  schema_version: "curve.manual-plan-draft.status/v3-candidate";
  policy_edition: ManualPlanSaveV3["policy_edition"];
  workspace_id: string;
  initiative_id: string;
  initiative_version: number;
  draft_status: "ABSENT" | "CURRENT" | "STALE";
  current_revision_id: string | null;
  expected_draft_revision: number;
};
export type ManualPlanRevisionV3 = {
  schema_version: "curve.manual-plan-draft.revision/v3-candidate";
  policy_edition: ManualPlanSaveV3["policy_edition"];
  id: string;
  workspace_id: string;
  product_id: string;
  initiative_id: string;
  draft_id: string;
  revision: number;
  initiative_version: number;
  predecessor_id: string | null;
  approved_subject_ref: ManualPlanRefV3;
  definition_ref: ManualPlanDefinitionRefV3;
  manual_profile_ref: ManualPlanRefV3;
  created_by: string;
  recorded_at: string;
  digest: string;
  controlling: false;
};
export type ManualPlanResultV3<T> = { data: T; etag: string; currentVersion: number };
export type ManualPlanCommandV3 = { payload: ManualPlanSaveV3; expectedVersion: number; idempotencyKey: string };
export type ManualPlanApiV3 = {
  status(target: ManualPlanTargetV3, signal?: AbortSignal): Promise<ManualPlanResultV3<ManualPlanStatusV3>>;
  current(target: ManualPlanTargetV3, signal?: AbortSignal): Promise<ManualPlanResultV3<ManualPlanRevisionV3>>;
  revision(
    target: ManualPlanTargetV3,
    id: string,
    signal?: AbortSignal
  ): Promise<ManualPlanResultV3<ManualPlanRevisionV3>>;
  save(
    target: ManualPlanTargetV3,
    command: ManualPlanCommandV3,
    signal?: AbortSignal
  ): Promise<ManualPlanResultV3<ManualPlanRevisionV3>>;
};
