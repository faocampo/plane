/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ICurveOperationSummary } from "@plane/types";
import { CurveFoundationStatus } from "@/components/curve/curve-foundation-status";

const { useCurveFoundationMock } = vi.hoisted(() => ({
  useCurveFoundationMock: vi.fn(),
}));

vi.mock("@/hooks/use-curve-foundation", () => ({
  useCurveFoundation: useCurveFoundationMock,
}));

const runningOperation: ICurveOperationSummary = {
  schema_version: "1.0",
  id: "operation-1",
  workspace_id: "workspace-1",
  operation_type: "FOUNDATION_PROBE",
  status: "RUNNING",
  version: 3,
  progress_percent: 50,
};

const defaultHookValue = {
  operation: undefined,
  etag: undefined,
  problem: undefined,
  connectionState: "LIVE",
  updates: [],
  lastEventId: undefined,
  lastUpdateAt: undefined,
  isLoading: false,
  isCreating: false,
  isCancelling: false,
  isPermissionLimited: false,
  createProbe: vi.fn(),
  cancelProbe: vi.fn(),
  resync: vi.fn(),
  refresh: vi.fn(),
};

describe("Curve Foundation status", () => {
  beforeEach(() => {
    useCurveFoundationMock.mockReset();
    useCurveFoundationMock.mockReturnValue({ ...defaultHookValue });
  });

  it("renders the ready state and starts the local verification", () => {
    const createProbe = vi.fn();
    useCurveFoundationMock.mockReturnValue({ ...defaultHookValue, createProbe });
    render(<CurveFoundationStatus workspaceSlug="x3m" workspaceId="workspace-1" />);

    expect(screen.getByRole("heading", { name: "Foundation status" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run foundation probe" }));
    expect(createProbe).toHaveBeenCalledOnce();
  });

  it("offers explicit resynchronization for an expired event cursor", () => {
    const resync = vi.fn();
    useCurveFoundationMock.mockReturnValue({
      ...defaultHookValue,
      connectionState: "STALE",
      problem: {
        type: "https://curve.x3m.internal/problems/curve-event-cursor-stale",
        title: "Live updates need to be resynchronized",
        status: 410,
      },
      resync,
    });
    render(<CurveFoundationStatus workspaceSlug="x3m" workspaceId="workspace-1" />);

    fireEvent.click(screen.getByRole("button", { name: "Resync status" }));
    expect(resync).toHaveBeenCalledOnce();
  });

  it("requires confirmation before cancelling an active probe", async () => {
    useCurveFoundationMock.mockReturnValue({
      ...defaultHookValue,
      operation: runningOperation,
      etag: '"curve-operation:operation-1:v3"',
    });
    render(<CurveFoundationStatus workspaceSlug="x3m" workspaceId="workspace-1" />);

    fireEvent.click(screen.getByRole("button", { name: "Cancel probe" }));
    expect(screen.getByRole("heading", { name: "Cancel foundation probe?" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Keep running" })).toHaveFocus());
  });
});
