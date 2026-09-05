/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { describe, expect, it } from "vitest";

import type { ICurveOperationSummary, ICurveSSEEvent, TCurveOperationStatus } from "@plane/types";
import {
  applyCurveSSEEvent,
  deriveCurveProgressStages,
  normalizeCurveProblem,
  parseCurveSSEBlock,
} from "@/components/curve/curve-foundation-state";

const operation: ICurveOperationSummary = {
  schema_version: "1.0",
  id: "operation-1",
  workspace_id: "workspace-1",
  operation_type: "FOUNDATION_PROBE",
  status: "RUNNING",
  version: 3,
  progress_percent: 50,
};

const event: ICurveSSEEvent = {
  schema_version: "1.0",
  event_id: "event-4",
  workspace_id: "workspace-1",
  event_type: "curve.operation.updated",
  occurred_at: "2026-08-21T12:00:00Z",
  resource: {
    type: "OPERATION",
    id: "operation-1",
    version: 4,
  },
  data: {
    status: "SUCCEEDED",
    progress_percent: 100,
  },
};

describe("Curve Foundation state projection", () => {
  it("parses a contract-valid SSE block", () => {
    const block = `id: event-4\nevent: curve.operation.updated\ndata: ${JSON.stringify(event)}`;

    expect(parseCurveSSEBlock(block)).toEqual(event);
  });

  it.each([
    "data: {}",
    "id: event-4\ndata: not-json",
    `id: wrong-event\ndata: ${JSON.stringify(event)}`,
    `id: event-4\ndata: ${JSON.stringify({ ...event, schema_version: "2.0" })}`,
    `id: event-4\ndata: ${JSON.stringify({ ...event, data: { status: "UNKNOWN" } })}`,
  ])("rejects malformed or unsupported SSE data", (block) => {
    expect(parseCurveSSEBlock(block)).toBeNull();
  });

  it("applies only a newer event for the same workspace Operation", () => {
    expect(applyCurveSSEEvent(operation, event)).toEqual({
      ...operation,
      status: "SUCCEEDED",
      version: 4,
      progress_percent: 100,
    });
    expect(
      applyCurveSSEEvent(operation, { ...event, event_id: "stale", resource: { ...event.resource, version: 3 } })
    ).toBe(operation);
    expect(applyCurveSSEEvent(operation, { ...event, workspace_id: "workspace-2" })).toBe(operation);
    expect(applyCurveSSEEvent(operation, { ...event, resource: { ...event.resource, id: "operation-2" } })).toBe(
      operation
    );
  });

  it("maps the terminal success projection to five completed stages", () => {
    const stages = deriveCurveProgressStages({ ...operation, status: "SUCCEEDED", version: 4 });

    expect(stages).toHaveLength(5);
    expect(stages.every((stage) => stage.state === "complete")).toBe(true);
  });

  it.each([
    ["queued cancellation", "CANCELLED", ["QUEUED", "CANCEL_REQUESTED", "CANCELLED"], 2],
    ["running cancellation", "CANCELLED", ["RUNNING", "CANCEL_REQUESTED", "CANCELLED"], 3],
  ] as const)("retains only completed evidence for %s", (_label, status, observedStatuses, completedCount) => {
    const stages = deriveCurveProgressStages({ ...operation, status }, [...observedStatuses]);

    expect(stages.filter((stage) => stage.state === "complete")).toHaveLength(completedCount);
    expect(stages.slice(completedCount).every((stage) => stage.state === "waiting")).toBe(true);
  });

  it.each([
    ["early failure", [], 2],
    ["late failure", ["QUEUED", "RUNNING"], 3],
  ] as const)("retains only completed evidence for %s", (_label, observedStatuses, completedCount) => {
    const stages = deriveCurveProgressStages({ ...operation, status: "FAILED" }, [
      ...observedStatuses,
    ] as TCurveOperationStatus[]);

    expect(stages.filter((stage) => stage.state === "complete")).toHaveLength(completedCount);
    expect(stages.slice(completedCount).every((stage) => stage.state === "waiting")).toBe(true);
  });

  it("exposes only safe Problem Details fields", () => {
    expect(
      normalizeCurveProblem({
        status: 409,
        data: {
          type: "https://curve.example.invalid/problems/conflict",
          title: "The Operation changed",
          detail: "private stack trace",
          credential: "secret",
          correlation_id: "correlation-1",
        },
      })
    ).toEqual({
      type: "https://curve.example.invalid/problems/conflict",
      title: "The Operation changed",
      status: 409,
      correlation_id: "correlation-1",
    });
  });
});
