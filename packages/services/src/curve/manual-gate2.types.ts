import type { ManualPlanSave, ManualPlanTarget } from "./manual-plan-draft.types";
export type ManualGate2Action = "PREPARE" | "APPROVE" | "REQUEST_CHANGES" | "RECONCILE" | "RELEASE";
export type ManualGate2Reference = { entity_id: string; digest: string };
export type ManualGate2Object = {
  object_id: string;
  digest: string;
  size_bytes: number;
  media_type: "application/json";
};
export type ManualGate2Claim = {
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
export type ManualGate2Command = {
  payload: {
    schema_version: "curve.manual-gate2.command/v2-candidate";
    action: ManualGate2Action;
    draft_revision_id: string;
    subject_ref: ManualGate2Reference | null;
    rationale_ref: ManualGate2Object | null;
    claims: { claim_id: string; generation: number }[];
    reconciliation_ref: ManualGate2Reference | null;
  };
  expectedVersion: number;
  idempotencyKey: string;
};
export type ManualGate2Record = {
  schema_version: "curve.manual-gate2.record/v2-candidate";
  policy_edition: "LOCAL_MANUAL_GATE2_RECONSTRUCTION_V2";
  id: string;
  workspace_id: string;
  product_id: string;
  initiative_id: string;
  sequence: number;
  initiative_version: number;
  action: ManualGate2Action;
  actor_id: string;
  subject_id: string;
  subject_digest: string;
  draft_revision_id: string;
  rationale_ref: ManualGate2Object | null;
  reconciliation_id: string | null;
  claims: ManualGate2Claim[];
  recorded_at: string;
  digest: string;
  request_digest: string;
};
export type ManualGate2Status = {
  schema_version: "curve.manual-gate2.status/v2-candidate";
  workspace_id: string;
  product_id: string;
  initiative_id: string;
  initiative_version: number;
  state: "ABSENT" | "PLAN_REVIEW" | "CHANGES_REQUESTED" | "MANUAL_APPROVED" | "RELEASED";
  effective_hold: "PAUSED" | "CANCELLED" | null;
  current_record: ManualGate2Record | null;
  subject_ref: ManualGate2Reference | null;
  draft_revision_id: string;
  definition_ref: ManualGate2Object;
  claims: ManualGate2Claim[];
  allowed_actions: ManualGate2Action[];
  rationales: { reference: ManualGate2Object; intent: "APPROVE" | "REQUEST_CHANGES" | "RECONCILE" }[];
  execution_authorized: false;
  completion_credit: false;
};
export type ManualPlanPreparation = {
  schema_version: "curve.manual-plan.preparation/v2-candidate";
  workspace_id: string;
  product_id: string;
  initiative_id: string;
  initiative_version: number;
  plans: { payload: ManualPlanSave }[];
};
export type ManualGate2Material = {
  schema_version: "curve.manual-gate2.material/v2-candidate";
  workspace_id: string;
  product_id: string;
  initiative_id: string;
  initiative_version: number;
  kind: "DEFINITION" | "RATIONALE";
  reference: ManualGate2Object;
  content: string;
};
export type ManualGate2Result<T> = { data: T; currentVersion: number };
export interface ManualGate2Api {
  preparation(target: ManualPlanTarget, signal?: AbortSignal): Promise<ManualGate2Result<ManualPlanPreparation>>;
  status(target: ManualPlanTarget, signal?: AbortSignal): Promise<ManualGate2Result<ManualGate2Status>>;
  material(
    target: ManualPlanTarget,
    reference: ManualGate2Object,
    signal?: AbortSignal
  ): Promise<ManualGate2Result<ManualGate2Material>>;
  execute(
    target: ManualPlanTarget,
    command: ManualGate2Command,
    signal?: AbortSignal
  ): Promise<ManualGate2Result<ManualGate2Record>>;
}
