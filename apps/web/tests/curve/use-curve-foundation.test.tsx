import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ICurveOperationSummary } from "@plane/types";
import { prependCurveVisibleUpdate, useCurveFoundation } from "@/hooks/use-curve-foundation";
import curveService from "@/services/curve.service";

vi.mock("@/services/curve.service", () => ({
  default: {
    listOperations: vi.fn(),
    retrieveOperation: vi.fn(),
    createFoundationProbe: vi.fn(),
    cancelOperation: vi.fn(),
  },
}));

const mockedCurveService = vi.mocked(curveService);

const runningOperation: ICurveOperationSummary = {
  schema_version: "1.0",
  id: "operation-1",
  workspace_id: "workspace-1",
  operation_type: "FOUNDATION_PROBE",
  status: "RUNNING",
  version: 3,
  progress_percent: 50,
};

const abortableStream = vi.fn(
  (_input: RequestInfo | URL, init?: RequestInit) =>
    new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    })
);

describe("useCurveFoundation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", abortableStream);
    mockedCurveService.listOperations.mockResolvedValue({ results: [] });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps one visible update for consecutive events with the same public status", () => {
    const queued = {
      eventId: "event-1",
      eventType: "curve.operation.queued",
      status: "QUEUED" as const,
      occurredAt: "2026-08-21T12:00:00Z",
    };
    const repeatedQueued = {
      ...queued,
      eventId: "event-2",
      eventType: "curve.operation.updated",
    };

    expect(prependCurveVisibleUpdate([queued], repeatedQueued)).toEqual([queued]);
  });

  it("allows only one create command while the first request is in flight", async () => {
    let resolveCreate: ((value: { operation: ICurveOperationSummary; etag: string }) => void) | undefined;
    mockedCurveService.createFoundationProbe.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveCreate = resolve;
        })
    );
    const { result, unmount } = renderHook(() => useCurveFoundation("x3m", "workspace-1"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      void result.current.createProbe();
      void result.current.createProbe();
    });

    expect(mockedCurveService.createFoundationProbe).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolveCreate?.({ operation: runningOperation, etag: '"curve-operation:operation-1:v3"' });
    });
    expect(result.current.operation).toEqual(runningOperation);
    unmount();
  });

  it("refreshes authoritative state and preserves a safe cancellation diagnostic", async () => {
    mockedCurveService.listOperations.mockResolvedValue({ results: [runningOperation] });
    mockedCurveService.retrieveOperation.mockResolvedValue({
      operation: runningOperation,
      etag: '"curve-operation:operation-1:v3"',
    });
    mockedCurveService.cancelOperation.mockRejectedValue({
      status: 412,
      data: {
        type: "https://curve.x3m.internal/problems/precondition-failed",
        title: "The Operation changed",
        detail: "private diagnostic",
      },
    });
    const { result, unmount } = renderHook(() => useCurveFoundation("x3m", "workspace-1"));
    await waitFor(() => expect(result.current.operation).toEqual(runningOperation));

    await act(async () => {
      await result.current.cancelProbe();
    });

    expect(mockedCurveService.retrieveOperation).toHaveBeenCalledTimes(2);
    expect(result.current.problem).toEqual({
      type: "https://curve.x3m.internal/problems/precondition-failed",
      title: "The Operation changed",
      status: 412,
    });
    unmount();
  });

  it("loads only a server-filtered Foundation probe", async () => {
    mockedCurveService.listOperations.mockResolvedValue({ results: [runningOperation] });
    mockedCurveService.retrieveOperation.mockResolvedValue({
      operation: runningOperation,
      etag: '"curve-operation:operation-1:v3"',
    });
    const { result, unmount } = renderHook(() => useCurveFoundation("x3m", "workspace-1"));

    await waitFor(() => expect(result.current.operation).toEqual(runningOperation));

    expect(mockedCurveService.listOperations).toHaveBeenCalledWith("x3m", 1, undefined, "FOUNDATION_PROBE");
    unmount();
  });

  it("rejects a non-Foundation projection and cannot cancel it", async () => {
    const workflowOperation: ICurveOperationSummary = {
      ...runningOperation,
      id: "workflow-operation-1",
      operation_type: "WORKFLOW_COMMAND",
    };
    mockedCurveService.listOperations.mockResolvedValue({ results: [workflowOperation] });
    const { result, unmount } = renderHook(() => useCurveFoundation("x3m", "workspace-1"));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    await act(async () => {
      await result.current.cancelProbe();
    });

    expect(result.current.operation).toBeUndefined();
    expect(mockedCurveService.retrieveOperation).not.toHaveBeenCalled();
    expect(mockedCurveService.cancelOperation).not.toHaveBeenCalled();
    unmount();
  });
});
