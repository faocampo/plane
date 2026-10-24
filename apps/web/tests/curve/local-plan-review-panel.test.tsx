// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ICurveInitiative } from "@plane/types";
import { LocalPlanReviewPanel } from "@/components/curve/initiatives/local-plan-review-panel";
const { retrieveCurrent, retrieveContent, upload, retrieveReview, review, retrieveFeedback } = vi.hoisted(() => ({
  retrieveCurrent: vi.fn(),
  retrieveContent: vi.fn(),
  upload: vi.fn(),
  retrieveReview: vi.fn(),
  review: vi.fn(),
  retrieveFeedback: vi.fn(),
}));
vi.mock("@/services/curve-local-plan.service", () => ({
  default: { retrieveCurrent, retrieveContent, upload, retrieveReview, review, retrieveFeedback },
}));
const initiative = {
  id: "initiative",
  product_id: "product",
  workspace_id: "workspace",
  version: 2,
} as ICurveInitiative;
const empty = {
  revision: null,
  initiative_version: 2,
  upload_available: true,
  prd_submission: { id: "prd" },
  prd_approval: { id: "approval" },
};
const record = {
  id: "source",
  version: 1,
  uploaded_at: "2026-10-21T12:00:00Z",
  original: { media_type: "text/plain" },
};
const renderPanel = (onReviewSaved?: () => void) =>
  render(
    <LocalPlanReviewPanel
      workspaceSlug="example"
      initiative={initiative}
      viewerId="viewer"
      onReviewSaved={onReviewSaved}
    />
  );
beforeEach(() => {
  vi.clearAllMocks();
  retrieveCurrent.mockResolvedValue(empty);
  retrieveReview.mockResolvedValue({
    revision: null,
    submission: null,
    decision: null,
    revision_is_current: false,
    initiative_version: 2,
    initiative_state: "PLANNING",
    available_actions: [],
  });
  review.mockResolvedValue({});
  retrieveFeedback.mockResolvedValue("Clarify the outcome.");
  retrieveContent.mockResolvedValue({ text: async () => "Synthetic requirements" });
  upload.mockResolvedValue({ data: record });
});
describe("local plan review screen", () => {
  it("uploads one selected file and displays saved document content", async () => {
    renderPanel();
    const input = await screen.findByLabelText("Upload plan");
    retrieveCurrent.mockResolvedValue({ ...empty, revision: record });
    fireEvent.change(input, { target: { files: [new File(["requirements"], "prd.txt")] } });
    expect(await screen.findByText("plan version 1 saved.")).toBeVisible();
    expect(await screen.findByText("Synthetic requirements")).toBeVisible();
    expect(upload).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Replace plan")).toBeEnabled();
  });
  it("retains the exact retry command after an unknown outcome", async () => {
    upload.mockRejectedValueOnce({ code: "MUTATION_OUTCOME_UNKNOWN" });
    renderPanel();
    fireEvent.change(await screen.findByLabelText("Upload plan"), {
      target: { files: [new File(["requirements"], "prd.txt")] },
    });
    const retry = await screen.findByRole("button", { name: "Retry same upload" });
    expect(screen.getByLabelText("Upload plan")).toBeDisabled();
    const original = upload.mock.calls[0];
    fireEvent.click(retry);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    expect(upload.mock.calls[1].slice(0, 5)).toEqual(original.slice(0, 5));
    expect(upload.mock.calls[1][5].idempotencyKey).toBe(original[5].idempotencyKey);
  });
  it("rejects an unsupported selection with a useful message", async () => {
    renderPanel();
    fireEvent.change(await screen.findByLabelText("Upload plan"), { target: { files: [new File(["x"], "prd.docx")] } });
    expect(screen.getByText(/Choose a non-empty PDF/)).toBeVisible();
    expect(upload).not.toHaveBeenCalled();
  });
  it("clears private text immediately when the viewer changes", async () => {
    retrieveCurrent.mockResolvedValue({ ...empty, revision: record });
    const view = renderPanel();
    expect(await screen.findByText("Synthetic requirements")).toBeVisible();
    retrieveCurrent.mockReturnValue(new Promise(() => {}));
    view.rerender(<LocalPlanReviewPanel workspaceSlug="example" initiative={initiative} viewerId="different" />);
    expect(screen.queryByText("Synthetic requirements")).not.toBeInTheDocument();
  });
  it("keeps text markup inert", async () => {
    retrieveCurrent.mockResolvedValue({ ...empty, revision: record });
    retrieveContent.mockResolvedValue({ text: async () => '<img src=x onerror="alert(1)">' });
    renderPanel();
    expect(await screen.findByText('<img src=x onerror="alert(1)">')).toBeVisible();
    expect(document.querySelector("img")).toBeNull();
  });
  it("hides upload when current authorization is read-only", async () => {
    retrieveCurrent.mockResolvedValue({ ...empty, upload_available: false });
    renderPanel();
    await waitFor(() => expect(retrieveCurrent).toHaveBeenCalled());
    expect(screen.queryByLabelText("Upload plan")).not.toBeInTheDocument();
  });
});

describe("connected Technical actions", () => {
  const ready = {
    revision: record,
    submission: { id: "submission" },
    decision: null,
    revision_is_current: true,
    initiative_version: 3,
    initiative_state: "PLANNING",
    available_actions: ["APPROVE", "REQUEST_CHANGES"],
  };
  it("approves the displayed document and shows the saved outcome", async () => {
    retrieveCurrent.mockResolvedValue({ ...empty, revision: record });
    retrieveReview.mockResolvedValue(ready);
    const refreshProject = vi.fn();
    renderPanel(refreshProject);
    await screen.findByText("Synthetic requirements");
    const approve = await screen.findByRole("button", { name: "Approve plan" });
    await waitFor(() => expect(approve).toBeEnabled());
    fireEvent.click(approve);
    expect(await screen.findByText("Plan approved. Both document reviews are complete.")).toBeVisible();
    expect(refreshProject).toHaveBeenCalledTimes(1);
    expect(review).toHaveBeenCalledWith(
      "example",
      expect.anything(),
      ready,
      "APPROVE",
      null,
      expect.objectContaining({ expectedVersion: 3 })
    );
  });
  it("requires feedback and sends literal reviewer text", async () => {
    retrieveCurrent.mockResolvedValue({ ...empty, revision: record });
    retrieveReview.mockResolvedValue(ready);
    renderPanel();
    await screen.findByText("Synthetic requirements");
    fireEvent.click(await screen.findByRole("button", { name: "Request changes" }));
    const send = screen.getByRole("button", { name: "Send feedback" });
    expect(send).toBeDisabled();
    fireEvent.change(screen.getByLabelText("What needs to change?"), { target: { value: "Clarify the outcome." } });
    fireEvent.click(send);
    expect(await screen.findByText("Feedback saved. The plan is ready for revision.")).toBeVisible();
    expect(review.mock.calls[0][4]).toBe("Clarify the outcome.");
  });
  it("keeps the exact pending decision for explicit retry", async () => {
    retrieveCurrent.mockResolvedValue({ ...empty, revision: record });
    retrieveReview.mockResolvedValue(ready);
    review.mockRejectedValueOnce({ code: "MUTATION_OUTCOME_UNKNOWN" });
    renderPanel();
    await screen.findByText("Synthetic requirements");
    fireEvent.click(await screen.findByRole("button", { name: "Approve plan" }));
    const retry = await screen.findByRole("button", { name: "Retry same review" });
    expect(screen.getByLabelText("Replace plan")).toBeDisabled();
    const first = review.mock.calls[0];
    fireEvent.click(retry);
    await waitFor(() => expect(review).toHaveBeenCalledTimes(2));
    expect(review.mock.calls[1].slice(0, 5)).toEqual(first.slice(0, 5));
    expect(review.mock.calls[1][5].idempotencyKey).toBe(first[5].idempotencyKey);
  });
});

it("keeps the retained plan readable and requests a new plan after renewed Product approval", async () => {
  const historical = { prd_submission: { id: "old-prd" }, prd_approval: { id: "old-approval" } };
  retrieveCurrent.mockResolvedValue({ ...empty, revision: record, revision_approval: historical });
  retrieveReview.mockResolvedValue({
    revision: record,
    revision_is_current: false,
    submission: { id: "old-submission" },
    decision: { state: "APPROVED" },
    initiative_version: 2,
    initiative_state: "PLANNING",
    available_actions: [],
  });
  renderPanel();
  expect(await screen.findByRole("heading", { name: "Update the plan" })).toBeVisible();
  expect(screen.getByText(/Product approved a new PRD/)).toBeVisible();
  expect(await screen.findByText("Synthetic requirements")).toBeVisible();
  expect(retrieveContent).toHaveBeenCalledWith(
    "example",
    expect.any(Object),
    record,
    historical,
    expect.any(AbortSignal)
  );
  expect(screen.queryByRole("button", { name: "Approve plan" })).not.toBeInTheDocument();
  expect(screen.queryByText("Your plan is approved. Both document reviews are complete.")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Replace plan")).toBeEnabled();
});
