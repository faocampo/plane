// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ICurveInitiative } from "@plane/types";
import { LocalDocumentReview } from "@/components/curve/initiatives/local-document-review";
const { prd, plan } = vi.hoisted(() => {
  const service = () => ({
    retrieveCurrent: vi.fn(),
    retrieveContent: vi.fn(),
    retrieveReview: vi.fn(),
    retrieveFeedback: vi.fn(),
    retrieveReopening: vi.fn(),
  });
  return { prd: service(), plan: service() };
});
vi.mock("@/services/curve-local-prd.service", () => ({ default: prd }));
vi.mock("@/services/curve-local-plan.service", () => ({ default: plan }));
const source = {
  id: "source",
  version: 1,
  uploaded_at: "2026-10-21T12:00:00Z",
  original: { media_type: "text/plain" },
};
const initiative = {
  id: "initiative",
  product_id: "product",
  workspace_id: "workspace",
  version: 2,
  state: "PLANNING",
} as ICurveInitiative;
beforeEach(() => {
  vi.resetAllMocks();
  prd.retrieveCurrent.mockResolvedValue({ source, initiative_version: 2, upload_available: false });
  prd.retrieveContent.mockResolvedValue({ text: async () => "Protected requirements" });
  prd.retrieveReview.mockResolvedValue({
    source,
    submission: { id: "submission" },
    decision: { id: "approval", state: "APPROVED" },
    submission_is_current: true,
    initiative_state: "PLANNING",
    available_actions: [],
  });
  prd.retrieveReopening.mockResolvedValue({ can_reopen: false, reopening: null });
  plan.retrieveCurrent.mockResolvedValue({ revision: source, initiative_version: 2, upload_available: false });
  plan.retrieveContent.mockResolvedValue({ text: async () => "Protected implementation" });
  plan.retrieveReview.mockResolvedValue({
    revision: source,
    submission: { id: "plan-submission" },
    decision: { id: "plan-approval", state: "APPROVED" },
    revision_is_current: true,
    initiative_state: "PLANNING",
    available_actions: [],
  });
});
async function openPlan() {
  render(
    <LocalDocumentReview workspaceSlug="example" initiative={initiative} viewerId="reviewer" onReviewSaved={vi.fn()} />
  );
  await screen.findByText("Protected requirements");
  await waitFor(() => expect(screen.getByRole("tab", { name: /Implementation plan.*Approved/ })).toBeVisible());
  fireEvent.click(screen.getByRole("tab", { name: /Implementation plan/ }));
  expect(await screen.findByText("Protected implementation")).toBeVisible();
}
describe("shared document access loss", () => {
  it.each([
    [401, "retrieveCurrent"],
    [403, "retrieveContent"],
    [404, "retrieveReview"],
  ] as const)("clears both cached documents after HTTP %s from %s and explicitly recovers", async (status, method) => {
    await openPlan();
    plan[method].mockRejectedValueOnce({ code: "UNAVAILABLE", status });
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByRole("heading", { name: "Document access unavailable" });
    expect(screen.queryByText("Protected implementation")).not.toBeInTheDocument();
    expect(screen.queryByText("Protected requirements")).not.toBeInTheDocument();
    expect(screen.getAllByRole("tab", { name: /Status unavailable/ })).toHaveLength(2);
    fireEvent.click(screen.getByRole("tab", { name: /Product requirements/ }));
    expect(screen.queryByText("Protected requirements")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve|Update PRD|Send for/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh document access" }));
    expect(await screen.findByText("Protected requirements")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: /Implementation plan/ }));
    expect(await screen.findByText("Protected implementation")).toBeVisible();
  });
  it("clears Technical content when Product content access is denied", async () => {
    await openPlan();
    fireEvent.click(screen.getByRole("tab", { name: /Product requirements/ }));
    prd.retrieveContent.mockRejectedValueOnce({ code: "UNAVAILABLE", status: 404 });
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByRole("heading", { name: "Document access unavailable" });
    expect(screen.queryByText("Protected implementation")).not.toBeInTheDocument();
    expect(screen.queryByText("Protected requirements")).not.toBeInTheDocument();
  });
  it("keeps transport failures distinct from an access denial", async () => {
    await openPlan();
    plan.retrieveCurrent.mockRejectedValueOnce({ code: "TRANSPORT" });
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText(/We couldn’t load the current document/);
    expect(screen.queryByRole("heading", { name: "Document access unavailable" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Product requirements/ }));
    expect(screen.getByText("Protected requirements")).toBeVisible();
  });
});
