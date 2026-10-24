/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useCurveProjectAssociation } from "@/hooks/use-curve-project-association";
import type { AssociationDiscovery, AssociationProduct } from "@/components/curve/projects/project-association-model";
import {
  ASSOCIATION,
  INSTALLATION,
  PRODUCT,
  PROJECT,
  WORKSPACE,
  deferred,
  discovery,
  makePort,
  projectRead,
  products,
  receipt,
  sourceProject,
} from "./project-association-fixtures";

function harness(port = makePort()) {
  const onAccessUnavailable = vi.fn();
  const rendered = renderHook((props) => useCurveProjectAssociation(props), {
    initialProps: {
      workspaceSlug: "example",
      workspaceId: WORKSPACE,
      actorId: "actor-a",
      projects: projectRead,
      port,
      onAccessUnavailable,
    },
  });
  return { ...rendered, port, onAccessUnavailable };
}
async function select(result: ReturnType<typeof harness>["result"]) {
  await waitFor(() => expect(result.current.productsState).toBe("ready"));
  act(() => {
    result.current.choose("projectId", PROJECT);
    result.current.choose("productId", PRODUCT);
  });
}
async function review(result: ReturnType<typeof harness>["result"]) {
  await select(result);
  await act(async () => result.current.check());
}

describe("native association intent and recovery", () => {
  it("reads real Product discovery without selecting or writing automatically", async () => {
    const { result, port } = harness();
    await waitFor(() => expect(result.current.productsState).toBe("ready"));
    expect(result.current.productId).toBe("");
    expect(result.current.projectId).toBe("");
    expect(port.discover).not.toHaveBeenCalled();
    expect(port.create).not.toHaveBeenCalled();
  });

  it("allows source selection while Products load without invalidating the pending Product read", async () => {
    const port = makePort();
    const delayed = deferred<AssociationProduct[]>();
    port.listProducts.mockReturnValue(delayed.promise);
    const { result } = harness(port);
    expect(result.current.productsState).toBe("loading");
    act(() => result.current.choose("projectId", PROJECT));
    await act(async () => delayed.resolve(products));
    expect(result.current.productsState).toBe("ready");
    expect(result.current.projectId).toBe(PROJECT);
    expect(result.current.products).toEqual(products);
  });

  it("uses the fresh precondition version and trusted installation for a closed explicit command", async () => {
    const { result, port } = harness();
    await review(result);
    expect(port.discover).toHaveBeenCalledWith(
      "example",
      { workspaceId: WORKSPACE, productId: PRODUCT },
      PROJECT,
      expect.any(AbortSignal)
    );
    expect(port.create).not.toHaveBeenCalled();
    await act(async () => result.current.send());
    expect(port.create).toHaveBeenCalledWith(
      "example",
      { workspaceId: WORKSPACE, productId: PRODUCT },
      {
        provider_installation_id: INSTALLATION,
        source_project_id: PROJECT,
      },
      { expectedVersion: 3, idempotencyKey: expect.any(String), signal: expect.any(AbortSignal) }
    );
    expect(result.current.step).toBe("confirmed");
    expect(result.current.receipt?.data.id).toBe(ASSOCIATION);
  });

  it.each(["ASSOCIATED_WITH_SELECTED_PRODUCT", "ASSOCIATED_ELSEWHERE"] as const)(
    "never submits %s availability",
    async (availability) => {
      const port = makePort();
      port.discover.mockResolvedValue(
        availability === "ASSOCIATED_WITH_SELECTED_PRODUCT"
          ? { ...discovery, availability, association_id: ASSOCIATION }
          : { ...discovery, availability, association_id: null }
      );
      const { result } = harness(port);
      await review(result);
      await act(async () => result.current.send());
      expect(result.current.step).toBe("review");
      expect(port.create).not.toHaveBeenCalled();
    }
  );

  it("never treats unavailable or denied discovery as an empty relationship", async () => {
    const port = makePort();
    port.discover.mockRejectedValue({ code: "UNAVAILABLE", status: 503 });
    const { result } = harness(port);
    await review(result);
    expect(result.current.issue).toBe("unavailable");
    expect(result.current.discovery).toBeUndefined();
    await act(async () => result.current.send());
    expect(port.create).not.toHaveBeenCalled();
  });

  it("blocks repeated clicks while a command is in flight", async () => {
    const port = makePort();
    const delayed = deferred<{ data: typeof receipt; etag: string }>();
    port.create.mockReturnValue(delayed.promise);
    const { result } = harness(port);
    await review(result);
    act(() => {
      void result.current.send();
      void result.current.send();
    });
    expect(port.create).toHaveBeenCalledTimes(1);
    expect(result.current.step).toBe("sending");
    await act(async () => delayed.resolve({ data: receipt, etag: "exact" }));
    expect(result.current.step).toBe("confirmed");
  });

  it("retains exact command identity and version through uncertain outcome retry", async () => {
    const port = makePort();
    port.create.mockRejectedValueOnce({ code: "MUTATION_OUTCOME_UNKNOWN" });
    const { result } = harness(port);
    await review(result);
    await act(async () => result.current.send());
    expect(result.current.step).toBe("unknown");
    const first = port.create.mock.calls[0];
    act(() => {
      result.current.choose("productId", "different");
      result.current.back();
      result.current.refreshProducts();
    });
    expect(result.current.productId).toBe(PRODUCT);
    expect(result.current.step).toBe("unknown");
    await act(async () => result.current.send());
    const second = port.create.mock.calls[1];
    expect(second.slice(0, 3)).toEqual(first.slice(0, 3));
    expect(second[3].idempotencyKey).toBe(first[3].idempotencyKey);
    expect(second[3].expectedVersion).toBe(first[3].expectedVersion);
    expect(result.current.step).toBe("confirmed");
  });

  it("stopping waiting is uncertain and ignores a late success instead of pretending cancellation", async () => {
    const port = makePort();
    const delayed = deferred<{ data: typeof receipt; etag: string }>();
    port.create.mockReturnValueOnce(delayed.promise);
    const { result } = harness(port);
    await review(result);
    act(() => {
      void result.current.send();
    });
    act(() => result.current.stopWaiting());
    expect(result.current.step).toBe("unknown");
    expect(port.create.mock.calls[0][3].signal?.aborted).toBe(true);
    await act(async () => delayed.resolve({ data: receipt, etag: "exact" }));
    expect(result.current.step).toBe("unknown");
    expect(result.current.receipt).toBeUndefined();
    await act(async () => result.current.send());
    expect(port.create.mock.calls[1][3].idempotencyKey).toBe(port.create.mock.calls[0][3].idempotencyKey);
  });

  it.each([409, 412, 400, 428])(
    "preserves inputs after definitive %s rejection and requires fresh review",
    async (status) => {
      const port = makePort();
      port.create.mockRejectedValueOnce({ status });
      const { result } = harness(port);
      await review(result);
      await act(async () => result.current.send());
      expect(result.current.step).toBe("choose");
      expect(result.current.projectId).toBe(PROJECT);
      expect(result.current.productId).toBe(PRODUCT);
      await act(async () => result.current.send());
      expect(port.create).toHaveBeenCalledTimes(1);
      await act(async () => result.current.check());
      await act(async () => result.current.send());
      expect(port.create.mock.calls[1][3].idempotencyKey).not.toBe(port.create.mock.calls[0][3].idempotencyKey);
    }
  );

  it.each([401, 403, 404])("redacts details and refreshes native access after command %s", async (status) => {
    const port = makePort();
    port.create.mockRejectedValue({ status });
    const { result, onAccessUnavailable } = harness(port);
    await review(result);
    await act(async () => result.current.send());
    expect(result.current.issue).toBe("denied");
    expect(result.current.products).toEqual([]);
    expect(result.current.visibleProjects).toEqual([]);
    expect(result.current.productId).toBe("");
    expect(result.current.projectId).toBe("");
    expect(result.current.receipt).toBeUndefined();
    expect(onAccessUnavailable).toHaveBeenCalledTimes(1);
  });

  it("cancel/back aborts discovery and preserves choices, ignoring late discovery", async () => {
    const port = makePort();
    const delayed = deferred<AssociationDiscovery>();
    port.discover.mockReturnValue(delayed.promise);
    const { result } = harness(port);
    await select(result);
    act(() => {
      void result.current.check();
    });
    act(() => result.current.back());
    expect(port.discover.mock.calls[0][3].aborted).toBe(true);
    await act(async () => delayed.resolve(discovery));
    expect(result.current.step).toBe("choose");
    expect(result.current.discovery).toBeUndefined();
    expect(result.current.projectId).toBe(PROJECT);
  });

  it.each(["actor", "workspace"])(
    "clears data synchronously and aborts a pending command when %s changes",
    async (kind) => {
      const port = makePort();
      const delayed = deferred<{ data: typeof receipt; etag: string }>();
      port.create.mockReturnValue(delayed.promise);
      const { result, rerender, onAccessUnavailable } = harness(port);
      await review(result);
      act(() => {
        void result.current.send();
      });
      const next = deferred<AssociationProduct[]>();
      port.listProducts.mockReturnValue(next.promise);
      rerender({
        workspaceSlug: kind === "workspace" ? "other" : "example",
        workspaceId: WORKSPACE,
        actorId: kind === "actor" ? "actor-b" : "actor-a",
        projects: projectRead,
        port,
        onAccessUnavailable,
      });
      expect(result.current.products).toEqual([]);
      expect(result.current.projectId).toBe("");
      expect(port.create.mock.calls[0][3].signal?.aborted).toBe(true);
      await act(async () => delayed.resolve({ data: receipt, etag: "exact" }));
      expect(result.current.receipt).toBeUndefined();
    }
  );

  it("rejects foreign-workspace or archived native candidates without inventing authority", async () => {
    const { result, rerender, port, onAccessUnavailable } = harness();
    await select(result);
    rerender({
      workspaceSlug: "example",
      workspaceId: WORKSPACE,
      actorId: "actor-a",
      projects: {
        status: "ready",
        data: [
          { ...sourceProject, workspace: "other" },
          { ...sourceProject, archived_at: "2026-10-01" },
        ],
      },
      port,
      onAccessUnavailable,
    });
    expect(result.current.visibleProjects).toEqual([]);
    await act(async () => result.current.check());
    expect(port.discover).not.toHaveBeenCalled();
  });

  it("discards a delayed Product read after native source access is denied", async () => {
    const port = makePort();
    const delayed = deferred<AssociationProduct[]>();
    port.listProducts.mockReturnValue(delayed.promise);
    const { result, rerender, onAccessUnavailable } = harness(port);
    rerender({
      workspaceSlug: "example",
      workspaceId: WORKSPACE,
      actorId: "actor-a",
      projects: { status: "denied", data: [] },
      port,
      onAccessUnavailable,
    });
    await act(async () => delayed.resolve(products));
    expect(result.current.issue).toBe("denied");
    expect(result.current.products).toEqual([]);
    expect(result.current.visibleProjects).toEqual([]);
  });

  it("invalidates review on window focus, refreshes Products, and preserves chosen IDs", async () => {
    const { result, port } = harness();
    await review(result);
    const next = deferred<AssociationProduct[]>();
    port.listProducts.mockReturnValueOnce(next.promise);
    act(() => window.dispatchEvent(new Event("focus")));
    expect(result.current.products).toEqual([]);
    expect(result.current.step).toBe("choose");
    expect(result.current.discovery).toBeUndefined();
    expect(result.current.productId).toBe(PRODUCT);
    await act(async () => next.resolve(products));
    expect(result.current.product?.id).toBe(PRODUCT);
  });

  it("does not discard uncertain request on focus or online revalidation", async () => {
    const port = makePort();
    port.create.mockRejectedValue({ code: "MUTATION_OUTCOME_UNKNOWN" });
    const { result } = harness(port);
    await review(result);
    await act(async () => result.current.send());
    act(() => {
      window.dispatchEvent(new Event("focus"));
      window.dispatchEvent(new Event("online"));
    });
    expect(result.current.step).toBe("unknown");
    expect(port.listProducts).toHaveBeenCalledTimes(1);
  });

  it("performs no Product reads without an authenticated actor", async () => {
    const port = makePort();
    const { result } = renderHook(() =>
      useCurveProjectAssociation({
        workspaceSlug: "example",
        workspaceId: WORKSPACE,
        projects: projectRead,
        port,
        onAccessUnavailable: vi.fn(),
      })
    );
    expect(result.current.validSession).toBe(false);
    expect(port.listProducts).not.toHaveBeenCalled();
  });
});
