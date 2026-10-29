/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { useState } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RoadmapItemCreateForm } from "@/components/curve/roadmap/item-create-form";
const props = () => ({
  milestones: [{ id: "milestone", name: "Guided setup" }],
  features: [{ id: "feature", name: "Getting started" }],
  reviewers: [
    { id: "product", name: "Alex Example" },
    { id: "technical", name: "Sam Example" },
  ],
  selectedMilestoneId: "milestone",
  canCreate: true,
  state: "ready" as const,
  onCreate: vi.fn().mockResolvedValue(undefined),
  onRetry: vi.fn().mockResolvedValue(undefined),
});
function fill() {
  fireEvent.change(screen.getByLabelText("Item name"), { target: { value: "Example item" } });
  fireEvent.change(screen.getByLabelText("Product reviewer"), { target: { value: "product" } });
  fireEvent.change(screen.getByLabelText("Technical reviewer"), { target: { value: "technical" } });
}
describe("Roadmap item creation form", () => {
  it("submits the approved two-stage draft with the selected milestone and only Feature preselected", async () => {
    const callbacks = props();
    render(<RoadmapItemCreateForm {...callbacks} />);
    expect(screen.queryByLabelText(/Code reviewer|Code Approver/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Product reviewer")).toHaveValue("");
    expect(screen.getByLabelText("Technical reviewer")).toHaveValue("");
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Create item" }));
    await waitFor(() =>
      expect(callbacks.onCreate).toHaveBeenCalledExactlyOnceWith({
        title: "Example item",
        milestoneId: "milestone",
        featureId: "feature",
        productReviewerId: "product",
        technicalReviewerId: "technical",
        riskTier: "STANDARD",
      })
    );
  });
  it("focuses the first invalid field and requires two distinct reviewers at Standard risk", async () => {
    const callbacks = props();
    render(<RoadmapItemCreateForm {...callbacks} />);
    fireEvent.click(screen.getByRole("button", { name: "Create item" }));
    expect(screen.getByLabelText("Item name")).toHaveFocus();
    fill();
    fireEvent.change(screen.getByLabelText("Technical reviewer"), { target: { value: "product" } });
    fireEvent.click(screen.getByRole("button", { name: "Create item" }));
    expect(screen.getByLabelText("Technical reviewer")).toHaveFocus();
    expect(screen.getByText(/Choose a different person/)).toBeInTheDocument();
    expect(callbacks.onCreate).not.toHaveBeenCalled();
  });
  it("permits one reviewer for both stages only at Low risk", async () => {
    const callbacks = props();
    render(<RoadmapItemCreateForm {...callbacks} />);
    fill();
    fireEvent.change(screen.getByLabelText("Technical reviewer"), { target: { value: "product" } });
    fireEvent.change(screen.getByLabelText("Risk level"), { target: { value: "LOW" } });
    fireEvent.click(screen.getByRole("button", { name: "Create item" }));
    await waitFor(() => expect(callbacks.onCreate).toHaveBeenCalledTimes(1));
  });
  it("revalidates reviewer choices when membership changes", async () => {
    const callbacks = props();
    const { rerender } = render(<RoadmapItemCreateForm {...callbacks} />);
    fill();
    rerender(<RoadmapItemCreateForm {...callbacks} reviewers={[callbacks.reviewers[0]]} />);
    fireEvent.click(screen.getByRole("button", { name: "Create item" }));
    expect(screen.getByText("Choose an active reviewer.")).toBeInTheDocument();
    expect(callbacks.onCreate).not.toHaveBeenCalled();
  });
  it("locks double clicks until the pending operation settles", async () => {
    let finish!: () => void;
    const callbacks = props();
    callbacks.onCreate.mockReturnValue(
      new Promise<void>((resolve) => {
        finish = resolve;
      })
    );
    render(<RoadmapItemCreateForm {...callbacks} />);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Create item" }));
    expect(screen.getByLabelText("Item name")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Creating item…" })).toBeDisabled();
    await act(async () => finish());
    expect(callbacks.onCreate).toHaveBeenCalledTimes(1);
  });
  it("offers exact recovery, locks edits and warns before leaving an uncertain save", async () => {
    const callbacks = props();
    render(<RoadmapItemCreateForm {...callbacks} state="unknown" />);
    expect(screen.getByLabelText("Item name")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Create item" })).not.toBeInTheDocument();
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Recover creation" }));
    await waitFor(() => expect(callbacks.onRetry).toHaveBeenCalledTimes(1));
    expect(callbacks.onCreate).not.toHaveBeenCalled();
  });
  it("keeps unexpected callback failures uncertain and permits no replacement submission", async () => {
    const callbacks = props();
    callbacks.onCreate.mockRejectedValue(new Error("Private diagnostics"));
    render(<RoadmapItemCreateForm {...callbacks} />);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Create item" }));
    await screen.findByRole("button", { name: "Recover creation" });
    expect(screen.queryByText("Private diagnostics")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Item name")).toBeDisabled();
  });
  it("blocks creation and recovery without current owner access", () => {
    const callbacks = props();
    const { rerender } = render(<RoadmapItemCreateForm {...callbacks} canCreate={false} />);
    expect(screen.getByRole("button", { name: "Create item" })).toBeDisabled();
    rerender(<RoadmapItemCreateForm {...callbacks} canCreate={false} state="unknown" />);
    expect(screen.getByRole("button", { name: "Recover creation" })).toBeDisabled();
  });
});

it("offers explicit cancellation only for an unresolved known attempt", async () => {
  const onCancel = vi.fn().mockResolvedValue(undefined);
  const callbacks = props();
  const { rerender } = render(<RoadmapItemCreateForm {...callbacks} state="unknown" canCancel onCancel={onCancel} />);
  fireEvent.click(screen.getByRole("button", { name: "Cancel attempt" }));
  await waitFor(() => expect(onCancel).toHaveBeenCalledTimes(1));
  expect(callbacks.onCreate).not.toHaveBeenCalled();
  rerender(<RoadmapItemCreateForm {...callbacks} state="unknown" canCancel={false} onCancel={onCancel} />);
  expect(screen.queryByRole("button", { name: "Cancel attempt" })).not.toBeInTheDocument();
});

it("announces confirmed cancellation and lets the user review the retained draft", () => {
  const callbacks = props();
  const { rerender } = render(<RoadmapItemCreateForm {...callbacks} />);
  fill();
  rerender(<RoadmapItemCreateForm {...callbacks} state="cancelled" />);
  expect(screen.getByRole("status")).toHaveTextContent("The previous attempt was cancelled");
  expect(screen.getByLabelText("Item name")).toHaveValue("Example item");
  expect(screen.getByLabelText("Item name")).toHaveFocus();
  expect(callbacks.onCreate).not.toHaveBeenCalled();
});

it("focuses the retained draft after the cancellation callback settles", async () => {
  const callbacks = props();
  function Harness() {
    const [state, setState] = useState<"unknown" | "cancelled">("unknown");
    return (
      <RoadmapItemCreateForm
        {...callbacks}
        state={state}
        canCancel
        onCancel={async () => {
          setState("cancelled");
        }}
      />
    );
  }
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Cancel attempt" }));
  await waitFor(() => expect(screen.getByLabelText("Item name")).toHaveFocus());
});

it.each([
  ["checking", "Checking creation…"],
  ["cancelling", "Cancelling attempt…"],
] as const)("names the %s operation and keeps recovery controls disabled", (state, label) => {
  render(<RoadmapItemCreateForm {...props()} state={state} canCancel onCancel={vi.fn()} />);
  expect(screen.getByRole("button", { name: label })).toBeDisabled();
  expect(screen.getByRole("alert")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Creating item…" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("Item name")).toBeDisabled();
});
