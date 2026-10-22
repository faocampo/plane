// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ICurveInitiative } from "@plane/types";
import { LocalPrdReviewPanel } from "@/components/curve/initiatives/local-prd-review-panel";
const {
  retrieveCurrent,
  retrieveContent,
  upload,
  retrieveReview,
  review,
  retrieveFeedback,
  retrieveReopening,
  reopen,
} = vi.hoisted(() => ({
  retrieveCurrent: vi.fn(),
  retrieveContent: vi.fn(),
  upload: vi.fn(),
  retrieveReview: vi.fn(),
  review: vi.fn(),
  retrieveFeedback: vi.fn(),
  retrieveReopening: vi.fn(),
  reopen: vi.fn(),
}));
vi.mock("@/services/curve-local-prd.service", () => ({
  default: {
    retrieveCurrent,
    retrieveContent,
    upload,
    retrieveReview,
    review,
    retrieveFeedback,
    retrieveReopening,
    reopen,
  },
}));
const initiative = {
  id: "initiative",
  product_id: "product",
  workspace_id: "workspace",
  version: 2,
} as ICurveInitiative;
const empty = { source: null, initiative_version: 2, upload_available: true };
const record = {
  id: "source",
  version: 1,
  uploaded_at: "2026-10-21T12:00:00Z",
  original: { media_type: "text/plain" },
};
const renderPanel = (onReviewSaved?: () => void) =>
  render(
    <LocalPrdReviewPanel
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
    source: null,
    submission: null,
    decision: null,
    submission_is_current: false,
    initiative_version: 2,
    initiative_state: "ALIGNING",
    available_actions: [],
  });
  review.mockResolvedValue({});
  retrieveReopening.mockResolvedValue({ can_reopen: false, reopening: null });
  reopen.mockResolvedValue({});
  retrieveFeedback.mockResolvedValue("Clarify the outcome.");
  retrieveContent.mockResolvedValue({ text: async () => "Synthetic requirements" });
  upload.mockResolvedValue({ data: record });
});
describe("local PRD review screen", () => {
  it("uploads one selected file and displays saved document content", async () => {
    renderPanel();
    const input = await screen.findByLabelText("Upload PRD");
    retrieveCurrent.mockResolvedValue({ ...empty, source: record });
    fireEvent.change(input, { target: { files: [new File(["requirements"], "prd.txt")] } });
    expect(await screen.findByText("PRD version 1 saved.")).toBeVisible();
    expect(await screen.findByText("Synthetic requirements")).toBeVisible();
    expect(upload).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Replace PRD")).toBeEnabled();
  });
  it("retains the exact retry command after an unknown outcome", async () => {
    upload.mockRejectedValueOnce({ code: "MUTATION_OUTCOME_UNKNOWN" });
    renderPanel();
    fireEvent.change(await screen.findByLabelText("Upload PRD"), {
      target: { files: [new File(["requirements"], "prd.txt")] },
    });
    const retry = await screen.findByRole("button", { name: "Retry same upload" });
    expect(screen.getByLabelText("Upload PRD")).toBeDisabled();
    const original = upload.mock.calls[0];
    fireEvent.click(retry);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    expect(upload.mock.calls[1].slice(0, 4)).toEqual(original.slice(0, 4));
    expect(upload.mock.calls[1][4].idempotencyKey).toBe(original[4].idempotencyKey);
  });
  it("rejects an unsupported selection with a useful message", async () => {
    renderPanel();
    fireEvent.change(await screen.findByLabelText("Upload PRD"), { target: { files: [new File(["x"], "prd.docx")] } });
    expect(screen.getByText(/Choose a non-empty PDF/)).toBeVisible();
    expect(upload).not.toHaveBeenCalled();
  });
  it("clears private text immediately when the viewer changes", async () => {
    retrieveCurrent.mockResolvedValue({ ...empty, source: record });
    const view = renderPanel();
    expect(await screen.findByText("Synthetic requirements")).toBeVisible();
    retrieveCurrent.mockReturnValue(new Promise(() => {}));
    view.rerender(<LocalPrdReviewPanel workspaceSlug="example" initiative={initiative} viewerId="different" />);
    expect(screen.queryByText("Synthetic requirements")).not.toBeInTheDocument();
  });
  it("keeps text markup inert", async () => {
    retrieveCurrent.mockResolvedValue({ ...empty, source: record });
    retrieveContent.mockResolvedValue({ text: async () => '<img src=x onerror="alert(1)">' });
    renderPanel();
    expect(await screen.findByText('<img src=x onerror="alert(1)">')).toBeVisible();
    expect(document.querySelector("img")).toBeNull();
  });
  it("hides upload when current authorization is read-only", async () => {
    retrieveCurrent.mockResolvedValue({ ...empty, upload_available: false });
    renderPanel();
    await waitFor(() => expect(retrieveCurrent).toHaveBeenCalled());
    expect(screen.queryByLabelText("Upload PRD")).not.toBeInTheDocument();
  });
});

describe("connected Product actions", () => {
  const ready = {
    source: record,
    submission: { id: "submission" },
    decision: null,
    submission_is_current: true,
    initiative_version: 3,
    initiative_state: "PRD_REVIEW",
    available_actions: ["APPROVE", "REQUEST_CHANGES"],
  };
  it("approves the displayed document and shows the saved outcome", async () => {
    retrieveCurrent.mockResolvedValue({ ...empty, source: record });
    retrieveReview.mockResolvedValue(ready);
    const refreshProject = vi.fn();
    renderPanel(refreshProject);
    await screen.findByText("Synthetic requirements");
    const approve = await screen.findByRole("button", { name: "Approve PRD" });
    await waitFor(() => expect(approve).toBeEnabled());
    fireEvent.click(approve);
    expect(await screen.findByText("PRD approved. The implementation plan is next.")).toBeVisible();
    expect(refreshProject).toHaveBeenCalledTimes(1);
    expect(review).toHaveBeenCalledWith(
      "example",
      expect.anything(),
      record,
      "APPROVE",
      ready.submission,
      null,
      expect.objectContaining({ expectedVersion: 3 })
    );
  });
  it("shows a replacement as ready while retaining earlier feedback", async () => {
    retrieveCurrent.mockResolvedValue({ ...empty, source: record });
    retrieveReview.mockResolvedValue({
      ...ready,
      submission_is_current: false,
      initiative_state: "ALIGNING",
      decision: { state: "CHANGES_REQUESTED", feedback: {} },
      available_actions: ["SUBMIT"],
    });
    retrieveFeedback.mockResolvedValue("Add acceptance criteria.");
    renderPanel();
    expect(await screen.findByRole("heading", { name: "Ready for Product review" })).toBeVisible();
    expect(await screen.findByText("Add acceptance criteria.")).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Changes requested" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Send for Product review" })).toBeEnabled());
  });
  it("requires feedback and sends literal reviewer text", async () => {
    retrieveCurrent.mockResolvedValue({ ...empty, source: record });
    retrieveReview.mockResolvedValue(ready);
    renderPanel();
    await screen.findByText("Synthetic requirements");
    fireEvent.click(await screen.findByRole("button", { name: "Request changes" }));
    const send = screen.getByRole("button", { name: "Send feedback" });
    expect(send).toBeDisabled();
    fireEvent.change(screen.getByLabelText("What needs to change?"), { target: { value: "Clarify the outcome." } });
    fireEvent.click(send);
    expect(await screen.findByText("Feedback saved. The PRD is ready for revision.")).toBeVisible();
    expect(review.mock.calls[0][5]).toBe("Clarify the outcome.");
  });
  it("keeps the exact pending decision for explicit retry", async () => {
    retrieveCurrent.mockResolvedValue({ ...empty, source: record });
    retrieveReview.mockResolvedValue(ready);
    review.mockRejectedValueOnce({ code: "MUTATION_OUTCOME_UNKNOWN" });
    renderPanel();
    await screen.findByText("Synthetic requirements");
    fireEvent.click(await screen.findByRole("button", { name: "Approve PRD" }));
    const retry = await screen.findByRole("button", { name: "Retry same review" });
    expect(screen.getByLabelText("Replace PRD")).toBeDisabled();
    const first = review.mock.calls[0];
    fireEvent.click(retry);
    await waitFor(() => expect(review).toHaveBeenCalledTimes(2));
    expect(review.mock.calls[1].slice(0, 6)).toEqual(first.slice(0, 6));
    expect(review.mock.calls[1][6].idempotencyKey).toBe(first[6].idempotencyKey);
  });
});

function approvedReview() {
  retrieveCurrent.mockResolvedValue({ ...empty, source: record, upload_available: false });
  retrieveReview.mockResolvedValue({
    source: record,
    submission: { id: "submission" },
    decision: { id: "decision", state: "APPROVED" },
    submission_is_current: true,
    initiative_version: 2,
    initiative_state: "PLANNING",
    available_actions: [],
  });
  retrieveReopening.mockResolvedValue({ can_reopen: true, reopening: null });
}
describe("approved PRD updates", () => {
  it("explains renewed approvals and reopens only after confirmation", async () => {
    approvedReview();
    const saved = vi.fn();
    renderPanel(saved);
    fireEvent.click(await screen.findByRole("button", { name: "Update PRD" }));
    expect(screen.getByText(/updated PRD will need Product approval/)).toBeVisible();
    expect(reopen).not.toHaveBeenCalled();
    const confirm = screen.getByRole("button", { name: "Reopen PRD" });
    expect(confirm).toHaveFocus();
    fireEvent.click(confirm);
    await waitFor(() => expect(reopen).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("PRD reopened. Upload the updated document to begin a new review.")).toBeVisible();
    expect(saved).toHaveBeenCalled();
  });
  it("keeps the approval when the owner cancels", async () => {
    approvedReview();
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Update PRD" }));
    fireEvent.click(screen.getByRole("button", { name: "Keep current approval" }));
    expect(screen.getByRole("button", { name: "Update PRD" })).toBeVisible();
    expect(reopen).not.toHaveBeenCalled();
  });
  it("retries an uncertain reopening with the same snapshot and key", async () => {
    approvedReview();
    reopen.mockRejectedValueOnce({ code: "MUTATION_OUTCOME_UNKNOWN" }).mockResolvedValueOnce({});
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Update PRD" }));
    fireEvent.click(screen.getByRole("button", { name: "Reopen PRD" }));
    fireEvent.click(await screen.findByRole("button", { name: "Retry reopening" }));
    await waitFor(() => expect(reopen).toHaveBeenCalledTimes(2));
    expect(reopen.mock.calls[0][2]).toBe(reopen.mock.calls[1][2]);
    expect(reopen.mock.calls[0][3].idempotencyKey).toBe(reopen.mock.calls[1][3].idempotencyKey);
  });
  it("asks for a replacement while keeping the previous approval in history", async () => {
    approvedReview();
    retrieveCurrent.mockResolvedValue({ ...empty, source: record });
    retrieveReview.mockResolvedValue({
      source: record,
      submission: { id: "submission" },
      decision: { id: "decision", state: "APPROVED" },
      submission_is_current: false,
      initiative_version: 2,
      initiative_state: "ALIGNING",
      available_actions: [],
    });
    retrieveReopening.mockResolvedValue({ can_reopen: false, reopening: { source_id: record.id } });
    renderPanel();
    expect(await screen.findByRole("heading", { name: "Update the PRD" })).toBeVisible();
    expect(screen.getByText(/previous approval stays in history/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Send for Product review" })).not.toBeInTheDocument();
  });
});
