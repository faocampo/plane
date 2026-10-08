/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ICurveInitiative, ICurveInitiativeCreateRequest, ICurveProduct, IWorkspaceMember } from "@plane/types";
import { useCurveInitiatives } from "@/hooks/use-curve-initiatives";
import curveService from "@/services/curve.service";

const { workspaceMemberStore } = vi.hoisted(() => ({
  workspaceMemberStore: {
    fetchWorkspaceMembers: vi.fn(),
    getWorkspaceMemberIds: vi.fn(),
    getWorkspaceMemberDetails: vi.fn(),
  },
}));

vi.mock("@/hooks/store/use-member", () => ({
  useMember: () => ({ workspace: workspaceMemberStore }),
}));

vi.mock("@/services/curve.service", () => ({
  default: {
    listProducts: vi.fn(),
    listInitiatives: vi.fn(),
    retrieveInitiative: vi.fn(),
    createInitiative: vi.fn(),
    updateInitiativeDraft: vi.fn(),
    acceptInitiativeRefinement: vi.fn(),
    pauseInitiative: vi.fn(),
    resumeInitiative: vi.fn(),
    cancelInitiative: vi.fn(),
  },
}));

const mockedCurveService = vi.mocked(curveService);

const product = (id: string): ICurveProduct => ({
  schema_version: "1.0",
  id,
  workspace_id: "workspace-1",
  key: id.toUpperCase(),
  name: `Product ${id}`,
  description: null,
  timezone: "America/Argentina/Buenos_Aires",
  state: "ACTIVE",
  owner: { actor_type: "HUMAN", actor_id: "human-1" },
  version: 1,
  created_at: "2026-09-01T12:00:00Z",
  updated_at: "2026-09-01T12:00:00Z",
  created_by: { actor_type: "HUMAN", actor_id: "human-1" },
  updated_by: { actor_type: "HUMAN", actor_id: "human-1" },
  archived_at: null,
  archived_by: null,
});

const initiative = (id: string, overrides: Partial<ICurveInitiative> = {}): ICurveInitiative => ({
  schema_version: "1.1",
  id,
  workspace_id: "workspace-1",
  product_id: "product-1",
  mode: "STANDALONE",
  roadmap_item_id: null,
  keyword: `${id}-keyword`,
  title: `Initiative ${id}`,
  description: { schema_version: "1.0", format: "MARKDOWN", body: `Outcome for ${id}` },
  risk_tier: "STANDARD",
  business_intent: "STRATEGIC",
  state: "DRAFT",
  paused_from_state: null,
  workflow_version_id: null,
  creator: { actor_type: "HUMAN", actor_id: "human-1" },
  gate_assignments: [],
  first_external_resource_at: null,
  version: 1,
  created_at: "2026-09-01T12:00:00Z",
  updated_at: "2026-09-01T12:00:00Z",
  updated_by: { actor_type: "HUMAN", actor_id: "human-1" },
  ...overrides,
});

const createPayload: ICurveInitiativeCreateRequest = {
  product_id: "product-1",
  mode: "STANDALONE",
  roadmap_item_id: null,
  keyword: "capability-overview",
  title: "Example capability overview",
  description: { schema_version: "1.0", format: "MARKDOWN", body: "Show compatibility state." },
  risk_tier: "STANDARD",
  business_intent: "STRATEGIC",
  gate_assignments: [
    { gate_type: "PRD_APPROVAL", approver_user_id: "human-1" },
    { gate_type: "PLAN_APPROVAL", approver_user_id: "human-2" },
    { gate_type: "CODE_READINESS", approver_user_id: "human-3" },
  ],
};

const member = (id: string, isActive = true, isBot = false): IWorkspaceMember => ({
  id: `membership-${id}`,
  member: {
    avatar_url: "",
    display_name: id,
    first_name: id,
    id,
    is_bot: isBot,
    last_name: "Tester",
  },
  role: 15,
  is_active: isActive,
});

describe("useCurveInitiatives", () => {
  let memberIds: string[];
  let members: Map<string, IWorkspaceMember>;

  beforeEach(() => {
    vi.clearAllMocks();
    memberIds = [];
    members = new Map([
      ["human-1", member("human-1")],
      ["inactive-1", member("inactive-1", false)],
      ["bot-1", member("bot-1", true, true)],
    ]);
    workspaceMemberStore.getWorkspaceMemberIds.mockImplementation(() => memberIds);
    workspaceMemberStore.getWorkspaceMemberDetails.mockImplementation((id: string) => members.get(id));
    workspaceMemberStore.fetchWorkspaceMembers.mockImplementation(async () => {
      memberIds = ["human-1", "inactive-1", "bot-1"];
    });
    mockedCurveService.listProducts.mockResolvedValue({ results: [] });
    mockedCurveService.listInitiatives.mockResolvedValue({ results: [] });
  });

  it("loads every active Product page, members, and the first confirmed Initiative", async () => {
    const draft = initiative("initiative-1");
    mockedCurveService.listProducts
      .mockResolvedValueOnce({ results: [product("product-1")], next_cursor: "product-page-2" })
      .mockResolvedValueOnce({ results: [product("product-1"), product("product-2")] });
    mockedCurveService.listInitiatives.mockResolvedValue({ results: [draft], next_cursor: "initiative-page-2" });
    mockedCurveService.retrieveInitiative.mockResolvedValue({ initiative: draft, etag: '"initiative-v1"' });

    const { result, unmount } = renderHook(() => useCurveInitiatives("example-workspace"));

    await waitFor(() => expect(result.current.selectedEtag).toBe('"initiative-v1"'));
    expect(result.current.products.map(({ id }) => id)).toEqual(["product-1", "product-2"]);
    expect(result.current.nextCursor).toBe("initiative-page-2");
    expect(result.current.activeMembers.map(({ member: user }) => user.id)).toEqual(["human-1"]);
    expect(mockedCurveService.listProducts).toHaveBeenNthCalledWith(1, "example-workspace", {
      state: "ACTIVE",
      pageSize: 100,
      cursor: undefined,
    });
    expect(mockedCurveService.listProducts).toHaveBeenNthCalledWith(2, "example-workspace", {
      state: "ACTIVE",
      pageSize: 100,
      cursor: "product-page-2",
    });
    expect(workspaceMemberStore.fetchWorkspaceMembers).toHaveBeenCalledWith("example-workspace");
    unmount();
  });

  it("merges paginated Initiative updates once and preserves server order", async () => {
    const original = initiative("initiative-1");
    const updated = initiative("initiative-1", { title: "Updated title", version: 2 });
    const second = initiative("initiative-2");
    mockedCurveService.listInitiatives
      .mockResolvedValueOnce({ results: [original], next_cursor: "initiative-page-2" })
      .mockResolvedValueOnce({ results: [updated, second] });
    mockedCurveService.retrieveInitiative.mockResolvedValue({ initiative: original, etag: '"initiative-v1"' });
    const { result, unmount } = renderHook(() => useCurveInitiatives("example-workspace"));
    await waitFor(() => expect(result.current.nextCursor).toBe("initiative-page-2"));

    await act(async () => {
      await result.current.loadMore();
    });

    expect(result.current.initiatives.map(({ id }) => id)).toEqual(["initiative-1", "initiative-2"]);
    expect(result.current.initiatives[0]).toMatchObject({ title: "Updated title", version: 2 });
    expect(result.current.nextCursor).toBeUndefined();
    unmount();
  });

  it("allows one create request at a time and selects the commit-bound result", async () => {
    const created = initiative("initiative-created");
    let resolveCreate: ((value: { initiative: ICurveInitiative; etag: string }) => void) | undefined;
    mockedCurveService.createInitiative.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveCreate = resolve;
        })
    );
    mockedCurveService.retrieveInitiative.mockImplementation(async (_slug, id) => ({
      initiative: id === created.id ? created : initiative(id),
      etag: id === created.id ? '"created-v1"' : '"initiative-v1"',
    }));
    const { result, unmount } = renderHook(() => useCurveInitiatives("example-workspace"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      void result.current.createInitiative(createPayload);
      void result.current.createInitiative(createPayload);
    });

    expect(mockedCurveService.createInitiative).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolveCreate?.({ initiative: created, etag: '"created-v1"' });
    });
    await waitFor(() => expect(result.current.selectedInitiative?.id).toBe(created.id));
    expect(result.current.initiatives[0]).toEqual(created);
    expect(result.current.selectedEtag).toBe('"created-v1"');
    unmount();
  });

  it("reuses an idempotency key for the same failed intent and rotates it when the intent changes", async () => {
    mockedCurveService.createInitiative.mockRejectedValue({ status: 503 });
    const { result, unmount } = renderHook(() => useCurveInitiatives("example-workspace"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.createInitiative(createPayload);
      await result.current.createInitiative({ ...createPayload });
      await result.current.createInitiative({ ...createPayload, title: "Changed title" });
    });

    const firstKey = mockedCurveService.createInitiative.mock.calls[0][2];
    const retryKey = mockedCurveService.createInitiative.mock.calls[1][2];
    const changedIntentKey = mockedCurveService.createInitiative.mock.calls[2][2];
    expect(retryKey).toBe(firstKey);
    expect(changedIntentKey).not.toBe(firstKey);
    unmount();
  });

  it("preserves the confirmed Initiative and reports a safe conflict when an update loses the race", async () => {
    const draft = initiative("initiative-1");
    mockedCurveService.listInitiatives.mockResolvedValue({ results: [draft] });
    mockedCurveService.retrieveInitiative.mockResolvedValue({ initiative: draft, etag: '"initiative-v1"' });
    mockedCurveService.updateInitiativeDraft.mockRejectedValue({
      status: 412,
      data: { title: "private internal diagnostic", correlation_id: "curve-correlation-1" },
    });
    const { result, unmount } = renderHook(() => useCurveInitiatives("example-workspace"));
    await waitFor(() => expect(result.current.selectedEtag).toBe('"initiative-v1"'));

    await act(async () => {
      await result.current.updateInitiativeDraft({ title: "Unconfirmed title" });
    });

    expect(result.current.selectedInitiative).toEqual(draft);
    expect(result.current.isConflict).toBe(true);
    expect(result.current.problem).toEqual({
      type: "https://curve.example.invalid/problems/request-failed",
      title: "A newer Initiative version is available",
      status: 412,
      correlation_id: "curve-correlation-1",
    });
    unmount();
  });

  it.each([
    ["acceptRefinement", "acceptInitiativeRefinement", undefined, "ALIGNING"],
    ["pauseInitiative", "pauseInitiative", "Dependency unavailable", "PAUSED"],
    ["resumeInitiative", "resumeInitiative", "Dependency restored", "DRAFT"],
    ["cancelInitiative", "cancelInitiative", "Outcome no longer needed", "CANCELLED"],
  ] as const)(
    "commits the %s lifecycle action with the selected ETag",
    async (action, serviceMethod, reason, state) => {
      const draft = initiative("initiative-1");
      const transitioned = initiative("initiative-1", { state, version: 2 });
      mockedCurveService.listInitiatives.mockResolvedValue({ results: [draft] });
      mockedCurveService.retrieveInitiative.mockResolvedValue({ initiative: draft, etag: '"initiative-v1"' });
      mockedCurveService[serviceMethod].mockResolvedValue({ initiative: transitioned, etag: '"initiative-v2"' });
      const { result, unmount } = renderHook(() => useCurveInitiatives("example-workspace"));
      await waitFor(() => expect(result.current.selectedEtag).toBe('"initiative-v1"'));

      await act(async () => {
        if (reason === undefined) await result.current[action]();
        else await result.current[action](reason);
      });

      expect(result.current.selectedInitiative).toEqual(transitioned);
      expect(result.current.selectedEtag).toBe('"initiative-v2"');
      const call = mockedCurveService[serviceMethod].mock.calls[0];
      expect(call[0]).toBe("example-workspace");
      expect(call[1]).toBe("initiative-1");
      expect(call.at(-2)).toBe('"initiative-v1"');
      expect(call.at(-1)).toEqual(expect.any(String));
      unmount();
    }
  );

  it("ignores stale data after the workspace changes", async () => {
    let resolveOldInitiatives: ((value: { results: ICurveInitiative[] }) => void) | undefined;
    mockedCurveService.listInitiatives.mockImplementation((slug) =>
      slug === "old-workspace"
        ? new Promise((resolve) => {
            resolveOldInitiatives = resolve;
          })
        : Promise.resolve({ results: [initiative("new-initiative", { workspace_id: "workspace-new" })] })
    );
    mockedCurveService.retrieveInitiative.mockImplementation(async (_slug, id) => ({
      initiative: initiative(id, { workspace_id: "workspace-new" }),
      etag: '"new-v1"',
    }));
    const { result, rerender, unmount } = renderHook(({ slug }) => useCurveInitiatives(slug), {
      initialProps: { slug: "old-workspace" },
    });

    rerender({ slug: "new-workspace" });
    await waitFor(() => expect(result.current.selectedInitiative?.id).toBe("new-initiative"));
    await act(async () => {
      resolveOldInitiatives?.({ results: [initiative("stale-initiative")] });
    });

    expect(result.current.initiatives.map(({ id }) => id)).toEqual(["new-initiative"]);
    expect(result.current.selectedInitiative?.workspace_id).toBe("workspace-new");
    unmount();
  });
});
