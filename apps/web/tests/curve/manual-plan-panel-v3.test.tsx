// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ManualPlanPanelV3 } from "../../components/curve/initiatives/manual-plan-panel-v3";
import { ManualPlanClientError } from "@plane/services";
import { fixture, payload, revision, status, target, result } from "./manual-plan-v3-fixtures";
import type { ManualPlanStatusV3 } from "../../../../packages/services/src/curve/manual-plan-draft-v3.types";
const api = () => ({
  status: vi.fn().mockResolvedValue(result(status)),
  current: vi.fn().mockResolvedValue(result(revision)),
  revision: vi.fn(),
  save: vi.fn(),
});
const props = (service = api()) => ({ api: service, target, viewerId: revision.created_by, initiativeVersion: 10 });

describe("two-stage plan versions panel", () => {
  it("reads exact current metadata and separates draft from approval", async () => {
    const p = props();
    render(<ManualPlanPanelV3 {...p} />);
    await screen.findByText("Draft saved for review");
    expect(screen.getByText("See Technical review")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save prepared draft" })).toBeDisabled();
    expect(p.api.save).not.toHaveBeenCalled();
  });
  it("shows an empty state without fetching an absent body", async () => {
    const p = props();
    p.api.status.mockResolvedValue(
      result({ ...fixture<ManualPlanStatusV3>("status-absent.valid"), initiative_version: 9 }, 9)
    );
    render(<ManualPlanPanelV3 {...p} />);
    await screen.findByText("No draft saved");
    expect(p.api.current).not.toHaveBeenCalled();
  });
  it("shows stale scope without fetching protected content", async () => {
    const p = props();
    p.api.status.mockResolvedValue(result({ ...status, draft_status: "STALE" }));
    render(<ManualPlanPanelV3 {...p} />);
    await screen.findByText("Draft needs a fresh plan");
    expect(p.api.current).not.toHaveBeenCalled();
  });
  it("clears protected metadata before refresh and keeps it clear on denial", async () => {
    const p = props();
    render(<ManualPlanPanelV3 {...p} />);
    await screen.findByText("See Technical review");
    p.api.status.mockRejectedValue(new Error("private provider body"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(screen.queryByText("See Technical review")).not.toBeInTheDocument();
    await screen.findByText("Draft unavailable for this view");
    expect(screen.queryByText(/private provider/)).not.toBeInTheDocument();
  });
  it("removes old metadata synchronously on viewer change", async () => {
    const p = props();
    const mounted = render(<ManualPlanPanelV3 {...p} />);
    await screen.findByText("See Technical review");
    p.api.status.mockReturnValue(new Promise(() => {}));
    mounted.rerender(<ManualPlanPanelV3 {...p} viewerId="other" />);
    expect(screen.queryByText("See Technical review")).not.toBeInTheDocument();
  });
  it("does not read when signed out", () => {
    const p = props();
    render(<ManualPlanPanelV3 {...p} viewerId={undefined} />);
    expect(p.api.status).not.toHaveBeenCalled();
  });
  it("rejects inconsistent status and current responses", async () => {
    const p = props();
    p.api.current.mockResolvedValue(result(revision, 11));
    render(<ManualPlanPanelV3 {...p} />);
    await screen.findByText("Draft unavailable for this view");
    expect(screen.queryByText("See Technical review")).not.toBeInTheDocument();
  });
  it("retains same command for deliberate unknown-outcome retry", async () => {
    const p = props();
    p.api.status.mockResolvedValue(
      result({ ...fixture<ManualPlanStatusV3>("status-absent.valid"), initiative_version: 9 }, 9)
    );
    p.api.save.mockRejectedValueOnce(new ManualPlanClientError("UNKNOWN")).mockResolvedValueOnce(result(revision));
    render(<ManualPlanPanelV3 {...p} prepared={{ payload, initiativeVersion: 9 }} />);
    await screen.findByText("No draft saved");
    fireEvent.click(screen.getByRole("button", { name: "Save prepared draft" }));
    await screen.findByRole("button", { name: "Retry same save" });
    expect(p.api.save).toHaveBeenCalledTimes(1);
    fireEvent.focus(window);
    expect(p.api.status).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Retry same save" }));
    await waitFor(() => expect(p.api.save).toHaveBeenCalledTimes(2));
    expect(p.api.save.mock.calls[0][1]).toEqual(p.api.save.mock.calls[1][1]);
  });
  it("rechecks on focus without retaining old metadata", async () => {
    const p = props();
    render(<ManualPlanPanelV3 {...p} />);
    await screen.findByText("See Technical review");
    p.api.status.mockReturnValue(new Promise(() => {}));
    fireEvent(window, new Event("focus"));
    expect(screen.queryByText("See Technical review")).not.toBeInTheDocument();
  });
});
