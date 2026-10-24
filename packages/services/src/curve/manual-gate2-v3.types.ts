// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import type { ManualPlanSaveV3, ManualPlanTargetV3 } from "./manual-plan-draft-v3.types";
export type ManualGate2ActionV3 = "PREPARE" | "APPROVE" | "REQUEST_CHANGES" | "RECONCILE" | "RELEASE";
export type ManualGate2ReferenceV3 = { entity_id: string; digest: string };
export type ManualGate2ObjectV3 = {
  object_id: string;
  digest: string;
  size_bytes: number;
  media_type: "application/json";
};
export type ManualGate2ClaimV3 = {
  claim_id: string;
  history_id: string;
  installation_id: string;
  issue_id: string;
  initiative_id: string;
  subject_id: string;
  generation: number;
  state: "ACTIVE" | "RELEASED";
  record_id: string;
};
export type ManualGate2CommandV3 = {
  payload: {
    schema_version: "curve.manual-gate2.command/v3-candidate";
    action: ManualGate2ActionV3;
    draft_revision_id: string;
    subject_ref: ManualGate2ReferenceV3 | null;
    rationale_ref: ManualGate2ObjectV3 | null;
    claims: { claim_id: string; generation: number }[];
    reconciliation_ref: ManualGate2ReferenceV3 | null;
  };
  expectedVersion: number;
  idempotencyKey: string;
};
export type ManualGate2RecordV3 = {
  schema_version: "curve.manual-gate2.record/v3-candidate";
  policy_edition: "LOCAL_MANUAL_GATE2_RECONSTRUCTION_V3";
  id: string;
  workspace_id: string;
  product_id: string;
  initiative_id: string;
  sequence: number;
  initiative_version: number;
  action: ManualGate2ActionV3;
  actor_id: string;
  subject_id: string;
  subject_digest: string;
  draft_revision_id: string;
  rationale_ref: ManualGate2ObjectV3 | null;
  reconciliation_id: string | null;
  claims: ManualGate2ClaimV3[];
  recorded_at: string;
  digest: string;
  request_digest: string;
};
export type ManualGate2StatusV3 = {
  schema_version: "curve.manual-gate2.status/v3-candidate";
  workspace_id: string;
  product_id: string;
  initiative_id: string;
  initiative_version: number;
  state: "ABSENT" | "PLAN_REVIEW" | "CHANGES_REQUESTED" | "MANUAL_APPROVED" | "RELEASED";
  effective_hold: "PAUSED" | "CANCELLED" | null;
  current_record: ManualGate2RecordV3 | null;
  subject_ref: ManualGate2ReferenceV3 | null;
  draft_revision_id: string;
  definition_ref: ManualGate2ObjectV3;
  claims: ManualGate2ClaimV3[];
  allowed_actions: ManualGate2ActionV3[];
  rationales: { reference: ManualGate2ObjectV3; intent: "APPROVE" | "REQUEST_CHANGES" | "RECONCILE" }[];
  execution_authorized: false;
  completion_credit: false;
};
export type ManualPlanPreparationV3 = {
  schema_version: "curve.manual-plan.preparation/v3-candidate";
  workspace_id: string;
  product_id: string;
  initiative_id: string;
  initiative_version: number;
  plans: { payload: ManualPlanSaveV3 }[];
};
export type ManualGate2MaterialV3 = {
  schema_version: "curve.manual-gate2.material/v3-candidate";
  workspace_id: string;
  product_id: string;
  initiative_id: string;
  initiative_version: number;
  kind: "DEFINITION" | "RATIONALE";
  reference: ManualGate2ObjectV3;
  content: string;
};
export type ManualGate2ResultV3<T> = { data: T; currentVersion: number };
export interface ManualGate2ApiV3 {
  preparation(target: ManualPlanTargetV3, signal?: AbortSignal): Promise<ManualGate2ResultV3<ManualPlanPreparationV3>>;
  status(target: ManualPlanTargetV3, signal?: AbortSignal): Promise<ManualGate2ResultV3<ManualGate2StatusV3>>;
  material(
    target: ManualPlanTargetV3,
    reference: ManualGate2ObjectV3,
    signal?: AbortSignal
  ): Promise<ManualGate2ResultV3<ManualGate2MaterialV3>>;
  execute(
    target: ManualPlanTargetV3,
    command: ManualGate2CommandV3,
    signal?: AbortSignal
  ): Promise<ManualGate2ResultV3<ManualGate2RecordV3>>;
}
