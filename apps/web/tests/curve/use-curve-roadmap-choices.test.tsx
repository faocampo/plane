/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { IWorkspaceMember } from "@plane/types";
import { useCurveRoadmapChoices } from "@/hooks/use-curve-roadmap-choices";
import hierarchy from "@/services/curve-roadmap-hierarchy.service";
import native from "@/services/curve-project-read.service";
vi.mock("@/services/curve-roadmap-hierarchy.service", () => ({
  default: { listRoadmaps: vi.fn(), listMilestones: vi.fn(), listFeatures: vi.fn() },
}));
vi.mock("@/services/curve-project-read.service", () => ({ default: { listMembers: vi.fn() } }));
const service = vi.mocked(hierarchy);
const members = vi.mocked(native);
const scope = { workspaceId: "workspace", productId: "product" };
const row = (
  id: string,
  options: Partial<IWorkspaceMember["member"]> & { is_active?: boolean } = {}
): IWorkspaceMember => {
  const member = {
    id,
    display_name: `Example ${id}`,
    first_name: "Example",
    last_name: id,
    avatar_url: "",
    is_active: true,
    is_bot: false,
    ...options,
  };
  return { id: `membership-${id}`, role: 15, is_active: true, member };
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  vi.resetAllMocks();
  service.listRoadmaps.mockResolvedValue({ results: [], next_cursor: null });
  service.listMilestones.mockResolvedValue({ results: [], next_cursor: null, roadmap_version: 2 });
  service.listFeatures.mockResolvedValue({ results: [], next_cursor: null, is_editor: false });
  members.listMembers.mockResolvedValue([row("human")]);
});
describe("Roadmap choices", () => {
  it("reads native choices only for the signed-in actor and selected Roadmap", async () => {
    const { result, rerender } = renderHook(
      ({ actor, roadmap }) => useCurveRoadmapChoices("example", actor, scope, roadmap),
      { initialProps: { actor: undefined as string | undefined, roadmap: undefined as string | undefined } }
    );
    expect(service.listRoadmaps).not.toHaveBeenCalled();
    rerender({ actor: "actor", roadmap: undefined });
    await waitFor(() => expect(result.current.choices.status).toBe("READY"));
    expect(service.listMilestones).not.toHaveBeenCalled();
    rerender({ actor: "actor", roadmap: "roadmap" });
    await waitFor(() => expect(result.current.choices.status).toBe("READY"));
    expect(service.listMilestones).toHaveBeenCalledWith(
      "example",
      { ...scope, roadmapId: "roadmap" },
      expect.objectContaining({ pageSize: 100 })
    );
  });
  it("excludes inactive humans, bots and removed memberships from reviewer choices", async () => {
    members.listMembers.mockResolvedValue([
      row("human"),
      row("bot", { is_bot: true }),
      row("inactive", { is_active: false }),
      { ...row("removed"), is_active: false },
    ]);
    const { result } = renderHook(() => useCurveRoadmapChoices("example", "actor", scope));
    await waitFor(() => expect(result.current.choices.status).toBe("READY"));
    expect(result.current.choices.data?.reviewers).toEqual([{ id: "human", name: "Example human" }]);
  });
  it("discards the entire choice set when any source denies access", async () => {
    const { result } = renderHook(() => useCurveRoadmapChoices("example", "actor", scope, "roadmap"));
    await waitFor(() => expect(result.current.choices.status).toBe("READY"));
    members.listMembers.mockRejectedValueOnce({ response: { status: 403, data: "Private detail" } });
    act(() => result.current.refresh());
    expect(result.current.choices.data).toBeNull();
    await waitFor(() =>
      expect(result.current.choices).toEqual({ status: "UNAVAILABLE", data: null, code: "UNAVAILABLE" })
    );
  });
  it("aborts refresh immediately and ignores late same-scope responses", async () => {
    const old = deferred<IWorkspaceMember[]>();
    members.listMembers.mockReturnValueOnce(old.promise);
    const { result } = renderHook(() => useCurveRoadmapChoices("example", "actor", scope));
    const signal = members.listMembers.mock.calls[0][1];
    act(() => result.current.refresh());
    expect(signal.aborted).toBe(true);
    await waitFor(() => expect(result.current.choices.status).toBe("READY"));
    await act(async () => old.resolve([row("old")]));
    expect(result.current.choices.data?.reviewers[0].id).toBe("human");
  });
  it("hides old choices and ignores A-B-A completions", async () => {
    const old = deferred<IWorkspaceMember[]>();
    members.listMembers.mockReturnValueOnce(old.promise);
    const { result, rerender } = renderHook(({ actor }) => useCurveRoadmapChoices("example", actor, scope), {
      initialProps: { actor: "a" },
    });
    rerender({ actor: "b" });
    rerender({ actor: "a" });
    await waitFor(() => expect(result.current.choices.status).toBe("READY"));
    await act(async () => old.resolve([row("old")]));
    expect(result.current.choices.data?.reviewers[0].id).toBe("human");
  });
  it("preserves explicit next-page cursors without silently dropping remaining choices", async () => {
    service.listRoadmaps.mockResolvedValue({ results: [], next_cursor: "next-roadmap" });
    service.listFeatures.mockResolvedValue({ results: [], next_cursor: "next-feature", is_editor: false });
    const { result } = renderHook(() =>
      useCurveRoadmapChoices("example", "actor", scope, "roadmap", {
        roadmaps: "roadmap-after",
        features: "feature-after",
        milestones: "version:position:id",
      })
    );
    await waitFor(() => expect(result.current.choices.status).toBe("READY"));
    expect(result.current.choices.data?.features.next_cursor).toBe("next-feature");
    expect(service.listRoadmaps.mock.calls[0][2]?.cursor).toBe("roadmap-after");
    expect(service.listMilestones.mock.calls[0][2]?.cursor).toBe("version:position:id");
  });
});
