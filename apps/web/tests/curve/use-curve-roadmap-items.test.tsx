/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CurveExistingWorkError } from "@plane/services";
import type { CurveItemCreate, CurveItemCreationResult, CurveItemPage } from "@plane/types";
import { itemCreationRecovery } from "@/components/curve/roadmap/item-creation-recovery";
import { useCurveRoadmapItems } from "@/hooks/use-curve-roadmap-items";
import items from "@/services/curve-roadmap-items.service";

vi.mock("@/services/curve-roadmap-items.service", () => ({
  default: {
    list: vi.fn(),
    create: vi.fn(),
    prepareScope: vi.fn(),
    reconcileCreation: vi.fn(),
    cancelCreation: vi.fn(),
  },
}));
const service = vi.mocked(items);
const id = (n: number) => `95000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope = { productId: id(1), roadmapId: id(2) };
const page = (version = 2): CurveItemPage => ({
  results: [],
  next_cursor: null,
  roadmap_version: version,
  can_create: true,
});
const payload = (): CurveItemCreate => ({
  initiative: {
    keyword: "EXAMPLE",
    title: "Example launch",
    description: { schema_version: "1.0", format: "MARKDOWN", body: "Example" },
    risk_tier: "STANDARD",
    business_intent: null,
    gate_assignments: [
      { gate_type: "PRD_APPROVAL", approver_user_id: id(5) },
      { gate_type: "PLAN_APPROVAL", approver_user_id: id(6) },
    ],
  },
  milestone_id: id(3),
  feature_id: id(4),
  scope_body: {
    object_id: id(7),
    digest: "sha256:" + "a".repeat(64),
    size_bytes: 4,
    media_type: "text/plain",
    editor_schema_version: "1.0",
  },
  priority: "MEDIUM",
  confidence: "HIGH",
  health: "UNKNOWN",
  planned_start: null,
  planned_end: null,
});
const created: CurveItemCreationResult = {
  resource_ref: {
    resource_type: "ROADMAP_ITEM",
    resource_id: id(8),
    resource_version: 1,
    initiative_ref: { resource_type: "INITIATIVE", resource_id: id(9), resource_version: 1 },
  },
  etag: `"curve-roadmap-item:${id(8)}:v1"`,
  replayed: false,
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const mount = () => renderHook(() => useCurveRoadmapItems("example", id(10), scope));
beforeEach(() => {
  sessionStorage.clear();
  vi.resetAllMocks();
  service.list.mockResolvedValue(page());
  service.create.mockResolvedValue(created);
  service.prepareScope.mockResolvedValue({
    resource_ref: {
      resource_type: "PREPARED_ITEM_SCOPE",
      resource_id: id(7),
      resource_version: 1,
      scope_body: payload().scope_body,
    },
    replayed: false,
  });
});

describe("Roadmap item session and interrupted creation", () => {
  it("does not read or write without an authenticated actor", async () => {
    const { result } = renderHook(() => useCurveRoadmapItems("example", undefined, scope));
    await act(async () => result.current.create(payload()));
    expect(service.list).not.toHaveBeenCalled();
    expect(service.create).not.toHaveBeenCalled();
  });
  it("uses the observed parent version and exactly Product and Technical assignments, then refreshes", async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    const body = payload();
    await act(async () => result.current.create(body));
    expect(service.create).toHaveBeenCalledWith(
      "example",
      scope,
      body,
      expect.objectContaining({ expectedVersion: 2, idempotencyKey: expect.any(String) })
    );
    expect(result.current.command).toEqual({ status: "CREATED", result: created });
    expect(service.list).toHaveBeenCalledTimes(2);
  });
  it("ignores double activation while creation is in flight", async () => {
    const pending = deferred<CurveItemCreationResult>();
    service.create.mockReturnValue(pending.promise);
    const { result } = mount();
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    act(() => {
      void result.current.create(payload());
      void result.current.create(payload());
    });
    expect(service.create).toHaveBeenCalledTimes(1);
    await act(async () => pending.resolve(created));
  });
  it("requires explicit retry with detached original bytes, original version and the same key", async () => {
    service.create.mockRejectedValueOnce(new CurveExistingWorkError("MUTATION_OUTCOME_UNKNOWN"));
    const { result } = mount();
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    const body = payload();
    const original = structuredClone(body);
    await act(async () => result.current.create(body));
    expect(result.current.command.status).toBe("UNKNOWN");
    expect(service.create).toHaveBeenCalledTimes(1);
    body.initiative.title = "Changed draft";
    await act(async () => result.current.create(body));
    expect(service.create).toHaveBeenCalledTimes(1);
    service.list.mockResolvedValue(page(3));
    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    await act(async () => result.current.retry());
    const first = service.create.mock.calls[0];
    const second = service.create.mock.calls[1];
    expect(second[2]).toEqual(original);
    expect(second[3].idempotencyKey).toBe(first[3].idempotencyKey);
    expect(second[3].expectedVersion).toBe(2);
    expect(result.current.command.status).toBe("CREATED");
  });
  it("retains uncertainty when a retry is rejected and blocks a replacement command", async () => {
    service.create
      .mockRejectedValueOnce(new CurveExistingWorkError("MUTATION_OUTCOME_UNKNOWN"))
      .mockRejectedValueOnce(new CurveExistingWorkError("CONFLICT", 412));
    const { result } = mount();
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    await act(async () => result.current.create(payload()));
    await act(async () => result.current.retry());
    expect(result.current.command).toEqual({ status: "UNKNOWN", code: "CONFLICT" });
    await act(async () => result.current.create(payload()));
    expect(service.create).toHaveBeenCalledTimes(2);
  });
  it("hides stale values during revalidation and denies creation after lost authority", async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    const pending = deferred<CurveItemPage>();
    service.list.mockReturnValueOnce(pending.promise);
    act(() => result.current.refresh());
    expect(result.current.page).toEqual({ status: "LOADING", data: null });
    await act(async () => result.current.create(payload()));
    expect(service.create).not.toHaveBeenCalled();
    await act(async () => pending.resolve({ ...page(), can_create: false }));
    await act(async () => result.current.create(payload()));
    expect(service.create).not.toHaveBeenCalled();
  });
  it.each(["actor", "workspace", "product", "roadmap"])(
    "isolates %s changes and ignores old read completions",
    async (kind) => {
      const pending = deferred<CurveItemPage>();
      service.list.mockReturnValueOnce(pending.promise);
      const initial = { actor: id(10), workspace: "example", product: id(1), roadmap: id(2) };
      const { result, rerender } = renderHook(
        (p) => useCurveRoadmapItems(p.workspace, p.actor, { productId: p.product, roadmapId: p.roadmap }),
        { initialProps: initial }
      );
      const signal = service.list.mock.calls[0][2]?.signal;
      rerender({ ...initial, [kind]: kind === "workspace" ? "other" : id(20) });
      expect(signal?.aborted).toBe(true);
      await waitFor(() => expect(result.current.page.status).toBe("READY"));
      await act(async () => pending.resolve(page(99)));
      expect(result.current.page).toEqual({ status: "READY", data: page() });
    }
  );
  it("does not resurrect an old creation result after A to B to A navigation", async () => {
    const { result, rerender } = renderHook(({ workspace }) => useCurveRoadmapItems(workspace, id(10), scope), {
      initialProps: { workspace: "a" },
    });
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    await act(async () => result.current.create(payload()));
    expect(result.current.command.status).toBe("CREATED");
    rerender({ workspace: "b" });
    rerender({ workspace: "a" });
    expect(result.current.command.status).toBe("IDLE");
  });
  it("aborts an in-flight write on navigation and hides its late result", async () => {
    const pending = deferred<CurveItemCreationResult>();
    service.create.mockReturnValueOnce(pending.promise);
    const { result, rerender } = renderHook(({ actor }) => useCurveRoadmapItems("example", actor, scope), {
      initialProps: { actor: id(10) },
    });
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    act(() => {
      void result.current.create(payload());
    });
    const signal = service.create.mock.calls[0][3].signal;
    rerender({ actor: id(20) });
    expect(signal?.aborted).toBe(true);
    await act(async () => pending.resolve(created));
    expect(result.current.command.status).toBe("IDLE");
  });
  it("loads only the next bounded page and hides previous page while loading", async () => {
    service.list.mockResolvedValueOnce({ ...page(), next_cursor: id(30) });
    const { result } = mount();
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    act(() => result.current.nextPage());
    expect(service.list.mock.calls[1][2]?.after).toBe(id(30));
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    act(() => result.current.nextPage());
    expect(service.list).toHaveBeenCalledTimes(2);
  });
});

describe("document preparation followed by item creation", () => {
  function draft() {
    const { scope_body: _scope, ...value } = payload();
    return value;
  }
  it("prepares the draft scope before creating with two independent retained keys", async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    await act(async () => result.current.createDraft(draft()));
    expect(service.prepareScope).toHaveBeenCalledTimes(1);
    expect(service.prepareScope.mock.calls[0][2]).toEqual({ body: "Example" });
    expect(service.create.mock.calls[0][2]).toEqual(payload());
    expect(service.prepareScope.mock.calls[0][3].idempotencyKey).not.toBe(
      service.create.mock.calls[0][3].idempotencyKey
    );
    expect(result.current.command.status).toBe("CREATED");
  });
  it("recovers uncertain preparation with the same body and key before creating once", async () => {
    service.prepareScope.mockRejectedValueOnce(new CurveExistingWorkError("MUTATION_OUTCOME_UNKNOWN"));
    const { result } = mount();
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    const body = draft();
    await act(async () => result.current.createDraft(body));
    body.initiative.description.body = "Changed";
    expect(result.current.command.status).toBe("UNKNOWN");
    expect(service.create).not.toHaveBeenCalled();
    await act(async () => result.current.retry());
    expect(service.prepareScope.mock.calls[1][2]).toEqual({ body: "Example" });
    expect(service.prepareScope.mock.calls[1][3].idempotencyKey).toBe(
      service.prepareScope.mock.calls[0][3].idempotencyKey
    );
    expect(service.create).toHaveBeenCalledTimes(1);
  });
  it("does not prepare a second document when item creation has an uncertain result", async () => {
    service.create.mockRejectedValueOnce(new CurveExistingWorkError("MUTATION_OUTCOME_UNKNOWN"));
    const { result } = mount();
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    await act(async () => result.current.createDraft(draft()));
    expect(result.current.command.status).toBe("UNKNOWN");
    await act(async () => result.current.retry());
    expect(service.prepareScope).toHaveBeenCalledTimes(1);
    expect(service.create.mock.calls[1][2]).toEqual(service.create.mock.calls[0][2]);
    expect(service.create.mock.calls[1][3].idempotencyKey).toBe(service.create.mock.calls[0][3].idempotencyKey);
  });
  it("does not continue creation when authority disappears during preparation", async () => {
    const pending = deferred<Awaited<ReturnType<typeof items.prepareScope>>>();
    service.prepareScope.mockReturnValue(pending.promise);
    const { result } = mount();
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    act(() => {
      void result.current.createDraft(draft());
    });
    service.list.mockResolvedValue({ ...page(), can_create: false });
    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    await act(async () =>
      pending.resolve({
        resource_ref: {
          resource_type: "PREPARED_ITEM_SCOPE",
          resource_id: id(7),
          resource_version: 1,
          scope_body: payload().scope_body,
        },
        replayed: false,
      })
    );
    expect(service.create).not.toHaveBeenCalled();
    expect(result.current.command.status).toBe("UNKNOWN");
    await act(async () => result.current.retry());
    expect(service.create).not.toHaveBeenCalled();
    service.list.mockResolvedValue(page());
    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    await act(async () => result.current.retry());
    expect(service.create).toHaveBeenCalledTimes(1);
    expect(service.prepareScope).toHaveBeenCalledTimes(1);
  });
  it("ignores duplicate activation while document preparation is pending", async () => {
    const pending = deferred<Awaited<ReturnType<typeof items.prepareScope>>>();
    service.prepareScope.mockReturnValue(pending.promise);
    const { result } = mount();
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    act(() => {
      void result.current.createDraft(draft());
      void result.current.createDraft(draft());
    });
    expect(service.prepareScope).toHaveBeenCalledTimes(1);
    expect(service.create).not.toHaveBeenCalled();
    await act(async () =>
      pending.resolve({
        resource_ref: {
          resource_type: "PREPARED_ITEM_SCOPE",
          resource_id: id(7),
          resource_version: 1,
          scope_body: payload().scope_body,
        },
        replayed: false,
      })
    );
    expect(service.create).toHaveBeenCalledTimes(1);
  });
  it("does not continue another actor's preparation after a session switch", async () => {
    const pending = deferred<Awaited<ReturnType<typeof items.prepareScope>>>();
    service.prepareScope.mockReturnValue(pending.promise);
    const { result, rerender } = renderHook(({ actor }) => useCurveRoadmapItems("example", actor, scope), {
      initialProps: { actor: id(10) },
    });
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    act(() => {
      void result.current.createDraft(draft());
    });
    rerender({ actor: id(11) });
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    await act(async () =>
      pending.resolve({
        resource_ref: {
          resource_type: "PREPARED_ITEM_SCOPE",
          resource_id: id(7),
          resource_version: 1,
          scope_body: payload().scope_body,
        },
        replayed: false,
      })
    );
    expect(service.create).not.toHaveBeenCalled();
    expect(result.current.command.status).toBe("IDLE");
    expect(service.prepareScope.mock.calls[0][3].signal?.aborted).toBe(true);
  });
});

describe("durable creation recovery", () => {
  const journal = () => itemCreationRecovery(sessionStorage, { workspaceSlug: "example", actorId: id(10), ...scope });
  it("retains a lost response across remount and recovers by read without another write", async () => {
    service.create.mockRejectedValueOnce(new CurveExistingWorkError("MUTATION_OUTCOME_UNKNOWN"));
    const first = mount();
    await waitFor(() => expect(first.result.current.page.status).toBe("READY"));
    await act(() => first.result.current.create(payload()));
    const retained = journal().read();
    expect(retained?.commandKey).toBe(service.create.mock.calls[0][3].idempotencyKey);
    first.unmount();
    service.reconcileCreation.mockResolvedValue({ state: "COMPLETED", resource_ref: created.resource_ref });
    const next = mount();
    await waitFor(() => expect(next.result.current.command.status).toBe("UNKNOWN"));
    await act(() => next.result.current.create(payload()));
    expect(service.create).toHaveBeenCalledTimes(1);
    await act(() => next.result.current.retry());
    expect(next.result.current.command).toEqual({
      status: "RECOVERED",
      result: { state: "COMPLETED", resource_ref: created.resource_ref },
    });
    expect(service.reconcileCreation).toHaveBeenCalledWith(
      "example",
      scope,
      retained?.commandKey,
      expect.any(AbortSignal)
    );
    expect(service.create).toHaveBeenCalledTimes(1);
    expect(journal().read()).toBeNull();
  });
  it("keeps unresolved or denied recovery locked without losing its locator", async () => {
    journal().retain(id(30));
    service.reconcileCreation
      .mockResolvedValueOnce({ state: "UNRESOLVED" })
      .mockRejectedValueOnce(new CurveExistingWorkError("UNAVAILABLE"));
    const { result } = mount();
    await waitFor(() => expect(result.current.command.status).toBe("UNKNOWN"));
    await act(() => result.current.retry());
    await act(() => result.current.retry());
    await act(() => result.current.create(payload()));
    expect(result.current.command.status).toBe("UNKNOWN");
    expect(journal().read()?.commandKey).toBe(id(30));
    expect(service.create).not.toHaveBeenCalled();
  });
  it("allows current-authorized receipt reads after creation ownership changes", async () => {
    journal().retain(id(30));
    service.list.mockResolvedValue({ ...page(), can_create: false });
    service.reconcileCreation.mockResolvedValue({ state: "COMPLETED", resource_ref: created.resource_ref });
    const { result } = mount();
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    expect(result.current.canRecover).toBe(true);
    await act(() => result.current.retry());
    expect(result.current.command.status).toBe("RECOVERED");
    expect(service.create).not.toHaveBeenCalled();
  });
  it("prevents a creation if the locator cannot be durably written", async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    const write = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("synthetic quota");
    });
    try {
      await act(() => result.current.create(payload()));
      expect(service.create).not.toHaveBeenCalled();
      expect(result.current.command.status).toBe("UNKNOWN");
    } finally {
      write.mockRestore();
    }
    await act(() => result.current.retry());
    expect(result.current.command.status).toBe("FAILED");
  });
  it("discards an old actor recovery response and retains that actor's locator", async () => {
    journal().retain(id(30));
    const waiting = deferred<{ state: "COMPLETED"; resource_ref: typeof created.resource_ref }>();
    service.reconcileCreation.mockReturnValue(waiting.promise);
    const { result, rerender } = renderHook(({ actor }) => useCurveRoadmapItems("example", actor, scope), {
      initialProps: { actor: id(10) },
    });
    await waitFor(() => expect(result.current.command.status).toBe("UNKNOWN"));
    let work!: Promise<void>;
    act(() => {
      work = result.current.retry();
    });
    rerender({ actor: id(11) });
    await act(async () => {
      waiting.resolve({ state: "COMPLETED", resource_ref: created.resource_ref });
      await work;
    });
    expect(result.current.command.status).toBe("IDLE");
    expect(journal().read()?.commandKey).toBe(id(30));
  });
});

it("keeps the in-memory command identity when ownership changes during an uncertain creation", async () => {
  service.create.mockRejectedValueOnce(new CurveExistingWorkError("MUTATION_OUTCOME_UNKNOWN"));
  const { result } = mount();
  await waitFor(() => expect(result.current.page.status).toBe("READY"));
  await act(() => result.current.create(payload()));
  const originalKey = service.create.mock.calls[0][3].idempotencyKey;
  sessionStorage.setItem(sessionStorage.key(0)!, JSON.stringify({ version: 1, commandKey: id(40) }));
  service.list.mockResolvedValue({ ...page(), can_create: false });
  act(() => result.current.refresh());
  await waitFor(() => expect(result.current.page.status).toBe("READY"));
  service.reconcileCreation.mockResolvedValue({ state: "COMPLETED", resource_ref: created.resource_ref });
  expect(result.current.canRecover).toBe(true);
  await act(() => result.current.retry());
  expect(service.reconcileCreation).toHaveBeenCalledWith("example", scope, originalKey, expect.any(AbortSignal));
  expect(service.create).toHaveBeenCalledTimes(1);
  expect(result.current.command.status).toBe("RECOVERED");
  expect(JSON.parse(sessionStorage.getItem(sessionStorage.key(0)!)!).commandKey).toBe(id(40));
});

describe("explicit creation cancellation", () => {
  const journal = () => itemCreationRecovery(sessionStorage, { workspaceSlug: "example", actorId: id(10), ...scope });
  it("unlocks a new command only after cancellation is confirmed", async () => {
    journal().retain(id(30));
    service.cancelCreation.mockResolvedValue({ state: "CANCELLED" });
    const { result } = mount();
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    expect(result.current.canCancel).toBe(true);
    await act(() => result.current.create(payload()));
    expect(service.create).not.toHaveBeenCalled();
    await act(() => result.current.cancel());
    expect(result.current.command.status).toBe("CANCELLED");
    expect(journal().read()).toBeNull();
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    await act(() => result.current.create(payload()));
    expect(service.create).toHaveBeenCalledTimes(1);
    expect(service.create.mock.calls[0][3].idempotencyKey).not.toBe(id(30));
  });
  it("opens an existing item when creation won", async () => {
    journal().retain(id(30));
    service.cancelCreation.mockResolvedValue({ state: "COMPLETED", resource_ref: created.resource_ref });
    const { result } = mount();
    await waitFor(() => expect(result.current.command.status).toBe("UNKNOWN"));
    await act(() => result.current.cancel());
    expect(result.current.command).toEqual({
      status: "RECOVERED",
      result: { state: "COMPLETED", resource_ref: created.resource_ref },
    });
    expect(service.create).not.toHaveBeenCalled();
  });
  it.each(["unknown", "unresolved", "denied"])(
    "retains the original identity after %s cancellation",
    async (outcome) => {
      service.create.mockRejectedValueOnce(new CurveExistingWorkError("MUTATION_OUTCOME_UNKNOWN"));
      const { result } = mount();
      await waitFor(() => expect(result.current.page.status).toBe("READY"));
      await act(() => result.current.create(payload()));
      const key = journal().read()?.commandKey;
      if (outcome === "unresolved") service.cancelCreation.mockResolvedValueOnce({ state: "UNRESOLVED" });
      else
        service.cancelCreation.mockRejectedValueOnce(
          new CurveExistingWorkError(outcome === "unknown" ? "MUTATION_OUTCOME_UNKNOWN" : "UNAVAILABLE")
        );
      await act(() => result.current.cancel());
      expect(result.current.command.status).toBe("UNKNOWN");
      expect(journal().read()?.commandKey).toBe(key);
      service.cancelCreation.mockResolvedValueOnce({ state: "CANCELLED" });
      await act(() => result.current.retry());
      expect(service.cancelCreation).toHaveBeenNthCalledWith(2, "example", scope, key, expect.any(AbortSignal));
      expect(service.create).toHaveBeenCalledTimes(1);
    }
  );
  it("keeps creation locked when storage cleanup fails", async () => {
    journal().retain(id(30));
    service.cancelCreation.mockResolvedValue({ state: "CANCELLED" });
    const { result } = mount();
    await waitFor(() => expect(result.current.page.status).toBe("READY"));
    const remove = vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("synthetic storage failure");
    });
    await act(() => result.current.cancel());
    await act(() => result.current.create(payload()));
    expect(result.current.command.status).toBe("UNKNOWN");
    expect(service.create).not.toHaveBeenCalled();
    remove.mockRestore();
    await act(() => result.current.retry());
    expect(result.current.command.status).toBe("CANCELLED");
  });
  it("preserves a replacement locator and rejects stale actor responses", async () => {
    journal().retain(id(30));
    const pending = deferred<{ state: "CANCELLED" }>();
    service.cancelCreation.mockReturnValue(pending.promise);
    const { result, rerender } = renderHook(({ actor }) => useCurveRoadmapItems("example", actor, scope), {
      initialProps: { actor: id(10) },
    });
    await waitFor(() => expect(result.current.command.status).toBe("UNKNOWN"));
    let work!: Promise<void>;
    act(() => {
      work = result.current.cancel();
    });
    rerender({ actor: id(11) });
    await act(async () => {
      pending.resolve({ state: "CANCELLED" });
      await work;
    });
    expect(journal().read()?.commandKey).toBe(id(30));
    expect(result.current.command.status).toBe("IDLE");
  });
});

it("does not erase a replacement locator after the original cancellation completes", async () => {
  const journal = itemCreationRecovery(sessionStorage, { workspaceSlug: "example", actorId: id(10), ...scope });
  journal.retain(id(30));
  const pending = deferred<{ state: "CANCELLED" }>();
  service.cancelCreation.mockReturnValue(pending.promise);
  const { result } = mount();
  await waitFor(() => expect(result.current.page.status).toBe("READY"));
  let work!: Promise<void>;
  act(() => {
    work = result.current.cancel();
  });
  sessionStorage.setItem(sessionStorage.key(0)!, JSON.stringify({ version: 1, commandKey: id(40) }));
  await act(async () => {
    pending.resolve({ state: "CANCELLED" });
    await work;
  });
  expect(journal.read()?.commandKey).toBe(id(40));
  expect(result.current.command.status).toBe("UNKNOWN");
  await act(() => result.current.create(payload()));
  expect(service.create).not.toHaveBeenCalled();
});

it("labels an explicit original-payload retry as recovery until it settles", async () => {
  service.create.mockRejectedValueOnce(new CurveExistingWorkError("MUTATION_OUTCOME_UNKNOWN"));
  const { result } = mount();
  await waitFor(() => expect(result.current.page.status).toBe("READY"));
  await act(() => result.current.create(payload()));
  const pending = deferred<CurveItemCreationResult>();
  service.create.mockReturnValueOnce(pending.promise);
  let work!: Promise<void>;
  act(() => {
    work = result.current.retry();
  });
  expect(result.current.command.status).toBe("RECOVERING");
  await act(async () => {
    pending.resolve(created);
    await work;
  });
  expect(result.current.command.status).toBe("CREATED");
  expect(service.create.mock.calls[1][3].idempotencyKey).toBe(service.create.mock.calls[0][3].idempotencyKey);
});
