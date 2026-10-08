/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { fireEvent, render, screen, waitFor, act } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ICurveInitiative } from "@plane/types";
import { PrdReviewPanel } from "@/components/curve/initiatives/prd-review-panel";
import fixture from "./fixtures/prd-review-context.json";
const { retrieve } = vi.hoisted(() => ({ retrieve: vi.fn() }));
vi.mock("@/services/curve.service", () => ({ default: { retrievePrdReviewContext: retrieve } }));
const initiative = { id: fixture.initiative_id, workspace_id: fixture.workspace_id, version: 7 } as ICurveInitiative;
const deferred = () => {
  let resolve!: (value: unknown) => void;
  const promise = new Promise((r) => {
    resolve = r;
  });
  return { promise, resolve };
};

beforeEach(() => {
  retrieve.mockReset();
  retrieve.mockResolvedValue(structuredClone(fixture));
});

describe("protected PRD review panel", () => {
  it("shows exact checkpoint and reviewer, with no executable approval", async () => {
    render(<PrdReviewPanel viewerId="viewer-1" workspaceSlug="example" initiative={initiative} />);
    expect(await screen.findByText(/Checkpoint 2/)).toBeInTheDocument();
    expect(screen.getByText(/Fictional Reviewer 1/)).toBeInTheDocument();
    expect(screen.getByText(/This is not an approval/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve|Submit|Reject/ })).not.toBeInTheDocument();
    expect(screen.getByText(/separate access/)).toBeInTheDocument();
  });
  it("distinguishes authoritative absence from unavailability", async () => {
    const data = structuredClone(fixture);
    data.decision = { availability: "UNAVAILABLE", metadata: null } as never;
    retrieve.mockResolvedValue(data);
    render(<PrdReviewPanel viewerId="viewer-1" workspaceSlug="example" initiative={initiative} />);
    expect(await screen.findByText("Unavailable for this view")).toBeInTheDocument();
    expect(screen.queryByText("No decision recorded")).not.toBeInTheDocument();
  });
  it("does not call a stale new-submission report an invalid checkpoint", async () => {
    const data = structuredClone(fixture);
    Object.assign(data.readiness.metadata!, { applicability: "STALE", ready_for_submission: false });
    retrieve.mockResolvedValue(data);
    render(<PrdReviewPanel viewerId="viewer-1" workspaceSlug="example" initiative={initiative} />);
    expect(
      await screen.findByText(/does not invalidate review of an existing immutable checkpoint/)
    ).toBeInTheDocument();
    expect(screen.getByText(/Checkpoint 2/)).toBeInTheDocument();
    expect(screen.getByText(/Original assessment: ready/)).toBeInTheDocument();
  });
  it("clears metadata during refresh and never echoes a denial body", async () => {
    render(<PrdReviewPanel viewerId="viewer-1" workspaceSlug="example" initiative={initiative} />);
    await screen.findByText(/Checkpoint 2/);
    const request = deferred();
    retrieve.mockReturnValueOnce(request.promise);
    fireEvent.click(screen.getByRole("button", { name: "Refresh PRD context" }));
    expect(screen.queryByText(/Checkpoint 2/)).not.toBeInTheDocument();
    await act(async () =>
      request.resolve(Promise.reject({ response: { status: 403, data: { body: "PRIVATE_DETAIL" } } }))
    );
    expect(await screen.findByText("PRD context unavailable")).toBeInTheDocument();
    expect(screen.queryByText(/PRIVATE_DETAIL/)).not.toBeInTheDocument();
  });
  it("clears synchronously when scope changes and suppresses late responses", async () => {
    const old = deferred(),
      fresh = deferred();
    retrieve.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    const { rerender } = render(<PrdReviewPanel viewerId="viewer-1" workspaceSlug="example" initiative={initiative} />);
    const oldSignal = retrieve.mock.calls[0][2] as AbortSignal;
    rerender(
      <PrdReviewPanel
        viewerId="viewer-1"
        workspaceSlug="other"
        initiative={{ ...initiative, id: "00000000-0000-4000-8000-000000000099" }}
      />
    );
    expect(oldSignal.aborted).toBe(true);
    expect(retrieve).toHaveBeenCalledTimes(2);
    expect(retrieve.mock.lastCall?.[0]).toBe("other");
    expect(retrieve.mock.lastCall?.[1].initiativeId).toBe("00000000-0000-4000-8000-000000000099");
    await act(async () => old.resolve(fixture));
    expect(screen.queryByText(/Checkpoint 2/)).not.toBeInTheDocument();
    await act(async () =>
      fresh.resolve({
        ...fixture,
        initiative_id: "00000000-0000-4000-8000-000000000099",
        reviewer: { ...fixture.reviewer, display_name: "New reviewer" },
        checkpoint: { availability: "UNAVAILABLE", metadata: null },
        decision: { availability: "UNAVAILABLE", metadata: null },
      })
    );
    expect(screen.queryByText(/Checkpoint 2/)).not.toBeInTheDocument();
    expect(await screen.findByText(/New reviewer/)).toBeInTheDocument();
  });
  it("rechecks on window focus and clears metadata on access loss", async () => {
    render(<PrdReviewPanel viewerId="viewer-1" workspaceSlug="example" initiative={initiative} />);
    await screen.findByText(/Checkpoint 2/);
    retrieve.mockRejectedValueOnce(new Error("Revoked"));
    fireEvent.focus(window);
    expect(await screen.findByText("PRD context unavailable")).toBeInTheDocument();
    expect(screen.queryByText(/Checkpoint 2/)).not.toBeInTheDocument();
  });
  it("aborts pending reads on unmount", async () => {
    const request = deferred();
    retrieve.mockReturnValue(request.promise);
    const { unmount } = render(<PrdReviewPanel viewerId="viewer-1" workspaceSlug="example" initiative={initiative} />);
    const signal = retrieve.mock.calls[0][2] as AbortSignal;
    unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => request.resolve(fixture));
  });
  it("does not reuse metadata after the Initiative version changes", async () => {
    const { rerender } = render(<PrdReviewPanel viewerId="viewer-1" workspaceSlug="example" initiative={initiative} />);
    await screen.findByText(/Checkpoint 2/);
    retrieve.mockRejectedValueOnce(new Error("Version changed"));
    rerender(<PrdReviewPanel viewerId="viewer-1" workspaceSlug="example" initiative={{ ...initiative, version: 8 }} />);
    expect(screen.queryByText(/Checkpoint 2/)).not.toBeInTheDocument();
    await waitFor(() => expect(retrieve.mock.lastCall?.[1].initiativeVersion).toBe(8));
    expect(await screen.findByText("PRD context unavailable")).toBeInTheDocument();
  });
  it("clears metadata and avoids reads after sign-out", async () => {
    const { rerender } = render(<PrdReviewPanel viewerId="viewer-1" workspaceSlug="example" initiative={initiative} />);
    await screen.findByText(/Checkpoint 2/);
    const calls = retrieve.mock.calls.length;
    rerender(<PrdReviewPanel workspaceSlug="example" initiative={initiative} />);
    expect(screen.queryByText(/Checkpoint 2/)).not.toBeInTheDocument();
    expect(await screen.findByText("PRD context unavailable")).toBeInTheDocument();
    expect(retrieve).toHaveBeenCalledTimes(calls);
  });
  it("does not reuse a previous viewer's metadata", async () => {
    const { rerender } = render(<PrdReviewPanel viewerId="viewer-1" workspaceSlug="example" initiative={initiative} />);
    await screen.findByText(/Checkpoint 2/);
    retrieve.mockRejectedValueOnce(new Error("Forbidden"));
    rerender(<PrdReviewPanel viewerId="viewer-2" workspaceSlug="example" initiative={initiative} />);
    expect(screen.queryByText(/Checkpoint 2/)).not.toBeInTheDocument();
    expect(await screen.findByText("PRD context unavailable")).toBeInTheDocument();
  });
});
