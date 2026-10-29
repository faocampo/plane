/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CurveItemMetadata } from "@plane/types";
import { useCurveRoadmapOverview } from "@/hooks/use-curve-roadmap-directory";
import items from "@/services/curve-roadmap-items.service";
vi.mock("@/services/curve-roadmap-items.service", () => ({ default: { list: vi.fn() } }));
vi.mock("@/services/curve-project-association.service", () => ({
  curveProjectAssociationPort: { listProducts: vi.fn() },
}));
const service = vi.mocked(items);
const scope = { productId: "p", roadmapId: "r" };
const item = (id: string) => ({ id }) as CurveItemMetadata;
const page = (ids: string[], cursor: string | null = null, version = 1) => ({
  results: ids.map(item),
  next_cursor: cursor,
  roadmap_version: version,
  can_create: true,
});
beforeEach(() => vi.resetAllMocks());
describe("complete milestone item directory", () => {
  it("loads each page before exposing complete items", async () => {
    service.list.mockResolvedValueOnce(page(["a"], "a")).mockResolvedValueOnce(page(["b"]));
    const { result } = renderHook(() => useCurveRoadmapOverview("example", "actor", scope));
    await waitFor(() => expect(result.current.read.status).toBe("READY"));
    expect(result.current.read.data?.items.map(({ id }) => id)).toEqual(["a", "b"]);
    expect(service.list.mock.calls[1][2]?.after).toBe("a");
  });
  it.each(["denied", "changed", "duplicate"])("never presents a partial directory after %s", async (mode) => {
    service.list.mockResolvedValueOnce(page(["a"], "a"));
    if (mode === "denied") service.list.mockRejectedValueOnce(new Error("synthetic unavailable"));
    else service.list.mockResolvedValueOnce(page([mode === "duplicate" ? "a" : "b"], null, mode === "changed" ? 2 : 1));
    const { result } = renderHook(() => useCurveRoadmapOverview("example", "actor", scope));
    await waitFor(() => expect(result.current.read.status).toBe("UNAVAILABLE"));
    expect(result.current.read.data).toBeNull();
  });
  it("clears old items before a refresh completes", async () => {
    service.list.mockResolvedValueOnce(page(["a"])).mockReturnValueOnce(new Promise(() => {}));
    const { result } = renderHook(() => useCurveRoadmapOverview("example", "actor", scope));
    await waitFor(() => expect(result.current.read.status).toBe("READY"));
    act(() => result.current.refresh());
    expect(result.current.read.data).toBeNull();
  });
  it("does not request a directory without an actor", async () => {
    renderHook(() => useCurveRoadmapOverview("example", undefined, scope));
    expect(service.list).not.toHaveBeenCalled();
  });
});
