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
