// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ManualControlEntry, ManualControlPanel } from "../../components/curve/initiatives/manual-control-panel";
import { ManualPlanClientError } from "@plane/services";
import { definitionRef, material, rationaleRef, record, result, status, target } from "./manual-plan-gate2-fixtures";
import { payload as draftPayload } from "./manual-plan-fixtures";
const api = () => ({
  preparation: vi.fn().mockRejectedValue(new Error()),
  status: vi.fn().mockResolvedValue(result(status)),
  material: vi
    .fn()
    .mockImplementation((_t, ref) =>
      Promise.resolve(result(material(ref.object_id === definitionRef.object_id ? "DEFINITION" : "RATIONALE")))
    ),
  execute: vi.fn(),
});
const props = (service = api()) => ({ api: service, target, viewerId: record.actor_id, initiativeVersion: 10 });
async function review() {
  await screen.findByText("Plan awaiting review");
  fireEvent.click(screen.getByRole("button", { name: "Read plan definition" }));
  await screen.findByText("A synthetic user can review the local plan.");
  fireEvent.change(screen.getByRole("combobox", { name: "Decision evidence" }), {
    target: { value: rationaleRef.object_id },
  });
  fireEvent.click(screen.getByRole("button", { name: "Read decision evidence" }));
  await screen.findByText("Synthetic approval evidence.");
  fireEvent.click(screen.getByRole("checkbox"));
}
describe("manual control panel", () => {
  it("mounts only for an explicit UI switch, signed-in viewer and manual lifecycle", async () => {
    const p = props();
    vi.stubEnv("VITE_CURVE_MANUAL_PLAN_V2_ENABLED", "");
    try {
      const view = render(<ManualControlEntry {...p} state="PLANNING" />);
      expect(p.api.status).not.toHaveBeenCalled();
      vi.stubEnv("VITE_CURVE_MANUAL_PLAN_V2_ENABLED", "true");
      view.rerender(<ManualControlEntry {...p} state="PRD_REVIEW" />);
      expect(p.api.status).not.toHaveBeenCalled();
      view.rerender(<ManualControlEntry {...p} viewerId={undefined} state="PLANNING" />);
      expect(p.api.status).not.toHaveBeenCalled();
      view.rerender(<ManualControlEntry {...p} state="PLANNING" />);
      await screen.findByText("Plan awaiting review");
      expect(p.api.status).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllEnvs();
    }
  });
  it("reading a prepared replacement cannot approve the older saved draft", async () => {
    const p = props();
    const replacement = { ...definitionRef, object_id: "50000000-0000-4000-8000-000000000001" };
    p.api.preparation.mockResolvedValue(
      result({
        schema_version: "curve.manual-plan.preparation/v2-candidate",
        workspace_id: target.workspaceId,
        product_id: target.productId,
        initiative_id: target.initiativeId,
        initiative_version: 10,
        plans: [{ payload: { ...draftPayload, definition_ref: replacement } }],
      })
    );
    p.api.material.mockResolvedValue(result({ ...material("DEFINITION"), reference: replacement }));
    const drafts = {
      status: vi.fn().mockRejectedValue(new Error()),
      current: vi.fn(),
      revision: vi.fn(),
      save: vi.fn(),
    };
    render(<ManualControlPanel {...p} drafts={drafts} />);
    fireEvent.click(await screen.findByRole("button", { name: "Read prepared definition" }));
    await screen.findByText("A synthetic user can review the local plan.");
    expect(p.api.material.mock.calls[0][1]).toEqual(replacement);
    expect(screen.getByRole("button", { name: "Approve and reserve tasks" })).toBeDisabled();
    expect(p.api.execute).not.toHaveBeenCalled();
  });
  it("requires material review before approving", async () => {
    const p = props();
    render(<ManualControlPanel {...p} />);
    await screen.findByText("Plan awaiting review");
    expect(screen.getByRole("button", { name: "Approve and reserve tasks" })).toBeDisabled();
    await review();
    expect(screen.getByRole("button", { name: "Approve and reserve tasks" })).toBeEnabled();
    expect(p.api.execute).not.toHaveBeenCalled();
  });
  it("retains an uncertain command for deliberate identical retry", async () => {
    const p = props();
    p.api.execute.mockRejectedValue(new ManualPlanClientError("UNKNOWN"));
    render(<ManualControlPanel {...p} />);
    await review();
    fireEvent.click(screen.getByRole("button", { name: "Approve and reserve tasks" }));
    await screen.findByRole("button", { name: "Retry the same decision" });
    expect(screen.queryByText("Synthetic approval evidence.")).not.toBeInTheDocument();
    fireEvent(window, new Event("focus"));
    expect(screen.getByRole("button", { name: "Retry the same decision" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Retry the same decision" }));
    await waitFor(() => expect(p.api.execute).toHaveBeenCalledTimes(2));
    expect(p.api.execute.mock.calls[0][1]).toEqual(p.api.execute.mock.calls[1][1]);
  });
  it("clears body data and authority on focus or identity change", async () => {
    const p = props();
    const view = render(<ManualControlPanel {...p} />);
    await review();
    p.api.status.mockReturnValue(new Promise(() => {}));
    fireEvent(window, new Event("focus"));
    expect(screen.queryByText("Synthetic approval evidence.")).not.toBeInTheDocument();
    view.rerender(<ManualControlPanel {...p} viewerId="different" />);
    expect(screen.queryByText("Plan awaiting review")).not.toBeInTheDocument();
  });
  it("does not fetch when signed out", () => {
    const p = props();
    render(<ManualControlPanel {...p} viewerId={undefined} />);
    expect(p.api.status).not.toHaveBeenCalled();
  });
  it("rejects changed version while reading a material", async () => {
    const p = props();
    p.api.material.mockResolvedValue(result(material("DEFINITION"), 11));
    render(<ManualControlPanel {...p} />);
    await screen.findByText("Plan awaiting review");
    fireEvent.click(screen.getByRole("button", { name: "Read plan definition" }));
    await screen.findByText("The material or your access changed. Refresh before continuing.");
    expect(screen.queryByText("A synthetic user can review the local plan.")).not.toBeInTheDocument();
    expect(p.api.execute).not.toHaveBeenCalled();
  });
});
