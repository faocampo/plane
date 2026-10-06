import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ManualPlanPanel } from "../../core/components/curve/initiatives/manual-plan-panel";
import { ManualPlanClientError } from "@plane/services";
import { fixture, payload, revision, status, target, result } from "./manual-plan-fixtures";
import type { ManualPlanStatus } from "../../../../packages/services/src/curve/manual-plan-draft.types";
const api = () => ({
  status: vi.fn().mockResolvedValue(result(status)),
  current: vi.fn().mockResolvedValue(result(revision)),
  revision: vi.fn(),
  save: vi.fn(),
});
const props = (service = api()) => ({ api: service, target, viewerId: revision.created_by, initiativeVersion: 10 });

describe("manual plan candidate panel", () => {
  it("reads exact current metadata and separates draft from approval", async () => {
    const p = props();
    render(<ManualPlanPanel {...p} />);
    await screen.findByText("Draft saved for review");
    expect(screen.getByText("Not approved")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save prepared draft" })).toBeDisabled();
    expect(p.api.save).not.toHaveBeenCalled();
  });
  it("shows an empty state without fetching an absent body", async () => {
    const p = props();
    p.api.status.mockResolvedValue(
      result({ ...fixture<ManualPlanStatus>("status-absent.valid"), initiative_version: 9 }, 9)
    );
    render(<ManualPlanPanel {...p} />);
    await screen.findByText("No draft saved");
    expect(p.api.current).not.toHaveBeenCalled();
  });
  it("shows stale scope without fetching protected content", async () => {
    const p = props();
    p.api.status.mockResolvedValue(result({ ...status, draft_status: "STALE" }));
    render(<ManualPlanPanel {...p} />);
    await screen.findByText("Draft needs a fresh plan");
    expect(p.api.current).not.toHaveBeenCalled();
  });
  it("clears protected metadata before refresh and keeps it clear on denial", async () => {
    const p = props();
    render(<ManualPlanPanel {...p} />);
    await screen.findByText("Not approved");
    p.api.status.mockRejectedValue(new Error("private provider body"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(screen.queryByText("Not approved")).not.toBeInTheDocument();
    await screen.findByText("Draft unavailable for this view");
    expect(screen.queryByText(/private provider/)).not.toBeInTheDocument();
  });
  it("removes old metadata synchronously on viewer change", async () => {
    const p = props();
    const mounted = render(<ManualPlanPanel {...p} />);
    await screen.findByText("Not approved");
    p.api.status.mockReturnValue(new Promise(() => {}));
    mounted.rerender(<ManualPlanPanel {...p} viewerId="other" />);
    expect(screen.queryByText("Not approved")).not.toBeInTheDocument();
  });
  it("does not read when signed out", () => {
    const p = props();
    render(<ManualPlanPanel {...p} viewerId={undefined} />);
    expect(p.api.status).not.toHaveBeenCalled();
  });
  it("rejects inconsistent status and current responses", async () => {
    const p = props();
    p.api.current.mockResolvedValue(result(revision, 11));
    render(<ManualPlanPanel {...p} />);
    await screen.findByText("Draft unavailable for this view");
    expect(screen.queryByText("Not approved")).not.toBeInTheDocument();
  });
  it("retains same command for deliberate unknown-outcome retry", async () => {
    const p = props();
    p.api.status.mockResolvedValue(
      result({ ...fixture<ManualPlanStatus>("status-absent.valid"), initiative_version: 9 }, 9)
    );
    p.api.save.mockRejectedValueOnce(new ManualPlanClientError("UNKNOWN")).mockResolvedValueOnce(result(revision));
    render(<ManualPlanPanel {...p} prepared={{ payload, initiativeVersion: 9 }} />);
    await screen.findByText("No draft saved");
    fireEvent.click(screen.getByRole("button", { name: "Save prepared draft" }));
    await screen.findByRole("button", { name: "Retry same save" });
    expect(p.api.save).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Retry same save" }));
    await waitFor(() => expect(p.api.save).toHaveBeenCalledTimes(2));
    expect(p.api.save.mock.calls[0][1]).toEqual(p.api.save.mock.calls[1][1]);
  });
  it("rechecks on focus without retaining old metadata", async () => {
    const p = props();
    render(<ManualPlanPanel {...p} />);
    await screen.findByText("Not approved");
    p.api.status.mockReturnValue(new Promise(() => {}));
    fireEvent(window, new Event("focus"));
    expect(screen.queryByText("Not approved")).not.toBeInTheDocument();
  });
});
