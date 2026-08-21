/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ICurveOperationSummary, ICurveProblemDetails, ICurveSSEEvent, TCurveOperationStatus } from "@plane/types";

export const CURVE_OPERATION_STATUSES: readonly TCurveOperationStatus[] = [
  "PENDING",
  "QUEUED",
  "RUNNING",
  "WAITING_FOR_HUMAN",
  "CANCEL_REQUESTED",
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
];

export const CURVE_TERMINAL_STATUSES = new Set<TCurveOperationStatus>(["SUCCEEDED", "FAILED", "CANCELLED"]);
export const CURVE_CANCELLABLE_STATUSES = new Set<TCurveOperationStatus>(["QUEUED", "RUNNING"]);

export type TCurveStageState = "waiting" | "active" | "complete" | "failed";

export interface ICurveProgressStage {
  key: string;
  label: string;
  description: string;
  state: TCurveStageState;
}

const PROGRESS_STAGES = [
  ["request", "Request accepted", "Authorized command returned one Operation"],
  ["record", "Operation recorded", "Operation and delivery event committed atomically"],
  ["workflow", "Workflow started", "One Temporal workflow accepted the Operation"],
  ["worker", "Worker completed", "Synthetic activity reached a terminal result"],
  ["browser", "Status received", "Browser received the terminal projection"],
] as const;

const WORKFLOW_STARTED_STATUSES = new Set<TCurveOperationStatus>(["RUNNING", "WAITING_FOR_HUMAN", "SUCCEEDED"]);

export const deriveCurveProgressStages = (
  operation?: ICurveOperationSummary,
  observedStatuses: TCurveOperationStatus[] = []
): ICurveProgressStage[] => {
  const evidence = new Set(observedStatuses);
  if (operation) evidence.add(operation.status);
  const workflowStarted = [...evidence].some((status) => WORKFLOW_STARTED_STATUSES.has(status));
  const completed = operation ? (operation.status === "SUCCEEDED" ? 5 : workflowStarted ? 3 : 2) : 0;
  const activeIndex =
    operation && !CURVE_TERMINAL_STATUSES.has(operation.status) && operation.status !== "CANCEL_REQUESTED"
      ? Math.min(completed, 4)
      : -1;

  return PROGRESS_STAGES.map(([key, label, description], index) => ({
    key,
    label,
    description,
    state: index < completed ? "complete" : index === activeIndex ? "active" : "waiting",
  }));
};

export const isCurveOperationStatus = (value: unknown): value is TCurveOperationStatus =>
  typeof value === "string" && CURVE_OPERATION_STATUSES.includes(value as TCurveOperationStatus);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export const parseCurveSSEBlock = (block: string): ICurveSSEEvent | null => {
  let eventId = "";
  const dataLines: string[] = [];

  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith("id:")) eventId = line.slice(3).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (!eventId || dataLines.length === 0) return null;

  try {
    const value: unknown = JSON.parse(dataLines.join("\n"));
    if (!isRecord(value) || value.schema_version !== "1.0" || value.event_id !== eventId) return null;
    if (!isRecord(value.resource) || !isRecord(value.data)) return null;
    if (
      typeof value.workspace_id !== "string" ||
      typeof value.event_type !== "string" ||
      typeof value.occurred_at !== "string" ||
      typeof value.resource.type !== "string" ||
      typeof value.resource.id !== "string" ||
      typeof value.resource.version !== "number"
    )
      return null;
    const status = value.data.status;
    if (status !== undefined && !isCurveOperationStatus(status)) return null;
    const progress = value.data.progress_percent;
    if (progress !== undefined && (typeof progress !== "number" || progress < 0 || progress > 100)) return null;
    return value as unknown as ICurveSSEEvent;
  } catch {
    return null;
  }
};

export const applyCurveSSEEvent = (
  operation: ICurveOperationSummary | undefined,
  event: ICurveSSEEvent
): ICurveOperationSummary | undefined => {
  if (
    !operation ||
    event.workspace_id !== operation.workspace_id ||
    event.resource.type !== "OPERATION" ||
    event.resource.id !== operation.id ||
    event.resource.version <= operation.version ||
    !event.data.status
  )
    return operation;

  return {
    ...operation,
    status: event.data.status,
    version: event.resource.version,
    ...(event.data.progress_percent === undefined ? {} : { progress_percent: event.data.progress_percent }),
  };
};

export const operationETag = (operation: ICurveOperationSummary): string =>
  `"curve-operation:${operation.id}:v${operation.version}"`;

export const normalizeCurveProblem = (error: unknown): ICurveProblemDetails => {
  const response = isRecord(error) ? error : {};
  const data = isRecord(response.data) ? response.data : {};
  const status = typeof response.status === "number" ? response.status : 500;
  const type = typeof data.type === "string" ? data.type : "https://curve.x3m.internal/problems/request-failed";
  const title = typeof data.title === "string" ? data.title : "Curve could not complete the request";
  const correlationId = typeof data.correlation_id === "string" ? data.correlation_id : undefined;
  const errors = Array.isArray(data.errors)
    ? data.errors.flatMap((item) => {
        if (!isRecord(item) || typeof item.code !== "string" || typeof item.message !== "string") return [];
        return [
          { code: item.code, message: item.message, ...(typeof item.field === "string" ? { field: item.field } : {}) },
        ];
      })
    : undefined;

  return {
    type,
    title,
    status,
    ...(correlationId ? { correlation_id: correlationId } : {}),
    ...(errors?.length ? { errors } : {}),
  };
};

export const humanizeCurveStatus = (status: TCurveOperationStatus): string =>
  status
    .toLowerCase()
    .split("_")
    .map((word) => `${word.charAt(0).toUpperCase()}${word.slice(1)}`)
    .join(" ");
