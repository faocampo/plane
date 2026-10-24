/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 */
/** Manual draft candidate metadata. No approval or execution authority. */
export type ManualPlanTarget = { workspaceSlug: string; workspaceId: string; productId: string; initiativeId: string };
export type ManualPlanRef = { entity_id: string; digest: string };
export type ManualPlanDefinitionRef = {
  object_id: string;
  digest: string;
  size_bytes: number;
  media_type: "application/json";
};
export type ManualPlanSave = {
  schema_version: "curve.manual-plan-draft.save/v2-candidate";
  policy_edition: "LOCAL_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2";
  expected_draft_revision: number;
  approved_subject_ref: ManualPlanRef;
  definition_ref: ManualPlanDefinitionRef;
  manual_profile_ref: ManualPlanRef;
};
export type ManualPlanStatus = {
  schema_version: "curve.manual-plan-draft.status/v2-candidate";
  policy_edition: ManualPlanSave["policy_edition"];
  workspace_id: string;
  initiative_id: string;
  initiative_version: number;
  draft_status: "ABSENT" | "CURRENT" | "STALE";
  current_revision_id: string | null;
  expected_draft_revision: number;
};
export type ManualPlanRevision = {
  schema_version: "curve.manual-plan-draft.revision/v2-candidate";
  policy_edition: ManualPlanSave["policy_edition"];
  id: string;
  workspace_id: string;
  product_id: string;
  initiative_id: string;
  draft_id: string;
  revision: number;
  initiative_version: number;
  predecessor_id: string | null;
  approved_subject_ref: ManualPlanRef;
  definition_ref: ManualPlanDefinitionRef;
  manual_profile_ref: ManualPlanRef;
  created_by: string;
  recorded_at: string;
  digest: string;
  controlling: false;
};
export type ManualPlanResult<T> = { data: T; etag: string; currentVersion: number };
export type ManualPlanCommand = { payload: ManualPlanSave; expectedVersion: number; idempotencyKey: string };
export type ManualPlanApi = {
  status(target: ManualPlanTarget, signal?: AbortSignal): Promise<ManualPlanResult<ManualPlanStatus>>;
  current(target: ManualPlanTarget, signal?: AbortSignal): Promise<ManualPlanResult<ManualPlanRevision>>;
  revision(target: ManualPlanTarget, id: string, signal?: AbortSignal): Promise<ManualPlanResult<ManualPlanRevision>>;
  save(
    target: ManualPlanTarget,
    command: ManualPlanCommand,
    signal?: AbortSignal
  ): Promise<ManualPlanResult<ManualPlanRevision>>;
};
