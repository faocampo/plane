/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CurveItemMetadata } from "@plane/types";
import { readRoadmapApprovals, useCurveRoadmapApprovals } from "@/hooks/use-curve-roadmap-approvals";
import { useCurveRoadmapOverview } from "@/hooks/use-curve-roadmap-directory";
import items from "@/services/curve-roadmap-items.service";
import prd from "@/services/curve-local-prd.service";
import plan from "@/services/curve-local-plan.service";
vi.mock("@/services/curve-local-prd.service", () => ({
  default: { retrieveReview: vi.fn(), retrieveReopening: vi.fn() },
}));
vi.mock("@/services/curve-local-plan.service", () => ({ default: { retrieveReview: vi.fn() } }));
vi.mock("@/services/curve-roadmap-items.service", () => ({ default: { list: vi.fn() } }));
const product = vi.mocked(prd),
  technical = vi.mocked(plan);
const item = { id: "item", initiative: { id: "initiative", version: 3 } } as CurveItemMetadata;
function productResult(changes: Record<string, unknown> = {}) {
  return {
    initiative_version: 3,
    source: { id: "source" },
    submission_is_current: true,
    submission: { id: "submission", digest: "submission-digest" },
    decision: { id: "decision", digest: "decision-digest", state: "APPROVED" },
    ...changes,
  } as unknown as Awaited<ReturnType<typeof prd.retrieveReview>>;
}
function planResult(changes: Record<string, unknown> = {}) {
  return {
    initiative_version: 3,
    prd_submission: { id: "submission", digest: "submission-digest" },
    prd_approval: { id: "decision", digest: "decision-digest" },
    revision: { id: "revision" },
    revision_is_current: true,
    submission: { id: "plan-submission" },
    decision: { state: "APPROVED" },
    ...changes,
  } as unknown as Awaited<ReturnType<typeof plan.retrieveReview>>;
}
const read = () => readRoadmapApprovals("example", "workspace", "product", item, new AbortController().signal);
beforeEach(() => {
  vi.resetAllMocks();
  product.retrieveReview.mockResolvedValue(productResult());
  product.retrieveReopening.mockResolvedValue({ reopening: null } as Awaited<ReturnType<typeof prd.retrieveReopening>>);
  technical.retrieveReview.mockResolvedValue(planResult());
});
describe("Roadmap document approval evidence", () => {
  it("shows both approvals only with matching current document context", async () => {
    await expect(read()).resolves.toEqual(["APPROVED", "APPROVED"]);
  });
  it("does not promote an old Product decision when the submission changed", async () => {
    product.retrieveReview.mockResolvedValue(productResult({ submission_is_current: false }));
    await expect(read()).resolves.toEqual(["READY", "LOCKED"]);
    expect(technical.retrieveReview).not.toHaveBeenCalled();
  });
  it("shows changes requested and retains the Technical prerequisite", async () => {
    product.retrieveReview.mockResolvedValue(productResult({ decision: { state: "CHANGES_REQUESTED" } }));
    await expect(read()).resolves.toEqual(["CHANGES", "LOCKED"]);
  });
  it("reopening invalidates the previously approved presentation", async () => {
    product.retrieveReopening.mockResolvedValue({ reopening: { source_id: "source" } } as Awaited<
      ReturnType<typeof prd.retrieveReopening>
    >);
    await expect(read()).resolves.toEqual(["UPDATING", "LOCKED"]);
    expect(technical.retrieveReview).not.toHaveBeenCalled();
  });
  it.each(["initiative", "Product pin"])("clears both statuses when the %s changed between reads", async (kind) => {
    technical.retrieveReview.mockResolvedValue(
      planResult(kind === "initiative" ? { initiative_version: 4 } : { prd_approval: { id: "other", digest: "other" } })
    );
    await expect(read()).resolves.toEqual(["UNAVAILABLE", "UNAVAILABLE"]);
  });
  it("clears both statuses when document access is denied", async () => {
    technical.retrieveReview.mockRejectedValue(new Error("synthetic denied"));
    const { result } = renderHook(() => useCurveRoadmapApprovals("example", "workspace", "product", "actor", [item]));
    await waitFor(() => expect(result.current.item).toEqual(["UNAVAILABLE", "UNAVAILABLE"]));
  });
});

it("refresh re-reads approvals even when Item and Initiative versions stay fixed", async () => {
  vi.mocked(items.list).mockResolvedValue({ results: [item], next_cursor: null, roadmap_version: 1, can_create: true });
  const { result } = renderHook(() => {
    const overview = useCurveRoadmapOverview("example", "actor", { productId: "product", roadmapId: "roadmap" });
    const approvals = useCurveRoadmapApprovals(
      "example",
      "workspace",
      "product",
      "actor",
      overview.read.status === "READY" ? overview.read.data.items : []
    );
    return { overview, approvals };
  });
  await waitFor(() => expect(result.current.approvals.item).toEqual(["APPROVED", "APPROVED"]));
  technical.retrieveReview.mockResolvedValue(planResult({ decision: { state: "CHANGES_REQUESTED" } }));
  act(() => result.current.overview.refresh());
  expect(result.current.approvals.item).toBeUndefined();
  await waitFor(() => expect(result.current.approvals.item).toEqual(["APPROVED", "CHANGES"]));
  expect(technical.retrieveReview).toHaveBeenCalledTimes(2);
});
