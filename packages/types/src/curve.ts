/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export type TCurveWorkspaceShellState = "EMPTY";

export type TCurveOperationStatus =
  | "PENDING"
  | "QUEUED"
  | "RUNNING"
  | "WAITING_FOR_HUMAN"
  | "CANCEL_REQUESTED"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELLED";

export type TCurveOperationType = "FOUNDATION_PROBE" | "WORKFLOW_COMMAND" | "PROVIDER_RECONCILIATION";

export type TCurveConnectionState = "CONNECTING" | "LIVE" | "RECONNECTING" | "STALE" | "OFFLINE";

export interface ICurveWorkspaceShell {
  workspace_id: string;
  workspace_slug: string;
  state: TCurveWorkspaceShellState;
}

export interface ICurveOperationSummary {
  schema_version: "1.0";
  id: string;
  workspace_id: string;
  operation_type: TCurveOperationType;
  status: TCurveOperationStatus;
  version: number;
  progress_percent?: number;
}

export interface ICurveOperationPage {
  results: ICurveOperationSummary[];
  next_cursor?: string | null;
}

export interface ICurveProblemDetails {
  type: string;
  title: string;
  status: number;
  correlation_id?: string;
  errors?: Array<{
    code: string;
    field?: string;
    message: string;
  }>;
  resync?: {
    action: "FETCH_CURRENT_OPERATIONS";
    cursor: null;
  };
}

export interface ICurveSSEEvent {
  schema_version: "1.0";
  event_id: string;
  workspace_id: string;
  event_type: string;
  occurred_at: string;
  resource: {
    type: string;
    id: string;
    version: number;
  };
  data: {
    status?: TCurveOperationStatus;
    progress_percent?: number;
  };
}

export interface ICurveOperationMutationResult {
  operation: ICurveOperationSummary;
  etag: string;
  location?: string;
}

export type TCurveProductState = "ACTIVE" | "ARCHIVED";

export type TCurveInitiativeMode = "ROADMAP" | "STANDALONE";

export type TCurveInitiativeRiskTier = "LOW" | "STANDARD" | "HIGH";

export type TCurveInitiativeBusinessIntent = "STRATEGIC" | "CUSTOMER_COMMITMENT" | "BUSINESS_IMPROVEMENT" | "MANDATORY";

export type TCurveInitiativeState =
  | "DRAFT"
  | "ALIGNING"
  | "PRD_REVIEW"
  | "PLANNING"
  | "PLAN_REVIEW"
  | "EXECUTING"
  | "CODE_READINESS_REVIEW"
  | "READY_FOR_REPOSITORY_REVIEW"
  | "PAUSED"
  | "FAILED"
  | "CANCELLED";

export type TCurveInitiativeListState = Extract<TCurveInitiativeState, "DRAFT" | "ALIGNING" | "PAUSED" | "CANCELLED">;

export type TCurveGateType = "PRD_APPROVAL" | "PLAN_APPROVAL" | "CODE_READINESS";

export interface ICurveHumanActor {
  actor_type: "HUMAN";
  actor_id: string;
}

export interface ICurveRichTextDocument {
  schema_version: "1.0";
  format: "MARKDOWN";
  body: string;
}

export interface ICurveProduct {
  schema_version: "1.0";
  id: string;
  workspace_id: string;
  key: string;
  name: string;
  description: string | null;
  timezone: string;
  state: TCurveProductState;
  owner: ICurveHumanActor;
  version: number;
  created_at: string;
  updated_at: string;
  created_by: ICurveHumanActor;
  updated_by: ICurveHumanActor;
  archived_at: string | null;
  archived_by: ICurveHumanActor | null;
}

export interface ICurveProductPage {
  results: ICurveProduct[];
  next_cursor?: string | null;
}

export interface ICurveProductListFilters {
  state?: TCurveProductState;
  pageSize?: number;
  cursor?: string;
}

export interface ICurveGateAssignment {
  id: string;
  workspace_id: string;
  initiative_id: string;
  gate_type: TCurveGateType;
  approver: ICurveHumanActor;
  valid_from: string;
  valid_until: string | null;
  delegation_reason: string | null;
}

export interface ICurveInitiative {
  schema_version: "1.0" | "1.1";
  id: string;
  workspace_id: string;
  product_id: string;
  mode: TCurveInitiativeMode;
  roadmap_item_id: string | null;
  keyword: string;
  title: string;
  description: ICurveRichTextDocument;
  risk_tier: TCurveInitiativeRiskTier;
  business_intent?: TCurveInitiativeBusinessIntent | null;
  state: TCurveInitiativeState;
  paused_from_state: Extract<TCurveInitiativeState, "DRAFT" | "ALIGNING"> | null;
  workflow_version_id: string | null;
  creator: ICurveHumanActor;
  gate_assignments: ICurveGateAssignment[];
  first_external_resource_at: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  updated_by: ICurveHumanActor;
}

export interface ICurveInitiativePage {
  results: ICurveInitiative[];
  next_cursor?: string | null;
}

export interface ICurveInitiativeListFilters {
  state?: TCurveInitiativeListState;
  productId?: string;
  pageSize?: number;
  cursor?: string;
}

export interface ICurveGateAssignmentRequest {
  gate_type: TCurveGateType;
  approver_user_id: string;
}

export interface ICurveInitiativeCreateRequest {
  product_id: string;
  mode: TCurveInitiativeMode;
  roadmap_item_id?: string | null;
  keyword: string;
  title: string;
  description: ICurveRichTextDocument;
  risk_tier: TCurveInitiativeRiskTier;
  business_intent?: TCurveInitiativeBusinessIntent | null;
  gate_assignments: ICurveGateAssignmentRequest[];
}

export interface ICurveInitiativeDraftUpdateRequest {
  keyword?: string;
  title?: string;
  description?: ICurveRichTextDocument;
  risk_tier?: TCurveInitiativeRiskTier;
  business_intent?: TCurveInitiativeBusinessIntent | null;
}

export interface ICurveInitiativeTransitionRequest {
  reason: string;
}

export interface ICurveInitiativeMutationResult {
  initiative: ICurveInitiative;
  etag: string;
  location?: string;
}
