/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
const { list, read, create } = vi.hoisted(() => ({ list: vi.fn(), read: vi.fn(), create: vi.fn() }));
vi.mock("@/services/curve.service", () => ({ default: { listProducts: list } }));
vi.mock("@plane/services", () => ({
  CurveExistingWorkError: class extends Error {
    constructor(readonly code: string) {
      super("Safe failure");
    }
  },
  CurveProjectAssociationPreconditionsService: class {
    retrieve = read;
  },
  CurveProjectAssociationService: class {
    create = create;
  },
  isCurveUuid: (value: unknown) =>
    typeof value === "string" && /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value),
  isCurveVersion: (value: unknown) => typeof value === "number" && Number.isSafeInteger(value) && value > 0,
}));
import { curveProjectAssociationPort as port } from "@/services/curve-project-association.service";
import { PRODUCT, PROJECT, WORKSPACE, deferred, discovery, products } from "./project-association-fixtures";

beforeEach(() => {
  vi.clearAllMocks();
});
describe("authenticated association adapter", () => {
  it("loads complete cursor-ordered Product list, keeping no owner/role fields", async () => {
    list
      .mockResolvedValueOnce({
        results: [{ ...products[0], owner: { actor_id: "never authority" } }],
        next_cursor: "next",
      })
      .mockResolvedValueOnce({ results: [], next_cursor: null });
    const result = await port.listProducts("example", WORKSPACE, new AbortController().signal);
    expect(result).toEqual(products);
    expect(list).toHaveBeenNthCalledWith(2, "example", { state: "ACTIVE", pageSize: 100, cursor: "next" });
    expect(create).not.toHaveBeenCalled();
  });

  it.each([
    { ...products[0], workspace_id: "foreign" },
    { ...products[0], version: 0 },
    { ...products[0], state: "ARCHIVED" },
    { ...products[0], id: "invented-id" },
  ])("fails closed for malformed/wrong-scope Product projection: %o", async (product) => {
    list.mockResolvedValue({ results: [product] });
    await expect(port.listProducts("example", WORKSPACE, new AbortController().signal)).rejects.toMatchObject({
      code: "INVALID",
    });
  });

  it("rejects incomplete pagination instead of returning a partial list", async () => {
    list.mockResolvedValueOnce({ results: products, next_cursor: "next" }).mockRejectedValueOnce({ status: 403 });
    await expect(port.listProducts("example", WORKSPACE, new AbortController().signal)).rejects.toMatchObject({
      status: 403,
    });
  });

  it("rejects repeated cursors and duplicate Product IDs", async () => {
    list
      .mockResolvedValueOnce({ results: products, next_cursor: "repeat" })
      .mockResolvedValueOnce({ results: [], next_cursor: "repeat" });
    await expect(port.listProducts("example", WORKSPACE, new AbortController().signal)).rejects.toMatchObject({
      code: "INVALID",
    });
    list.mockResolvedValueOnce({ results: [...products, ...products] });
    await expect(port.listProducts("example", WORKSPACE, new AbortController().signal)).rejects.toMatchObject({
      code: "INVALID",
    });
  });

  it("ignores an aborted Product response and does not advance its next cursor", async () => {
    const request = deferred<{ results: typeof products; next_cursor: string }>();
    list.mockReturnValue(request.promise);
    const controller = new AbortController();
    const result = port.listProducts("example", WORKSPACE, controller.signal);
    controller.abort();
    request.resolve({ results: products, next_cursor: "next" });
    await expect(result).rejects.toMatchObject({ code: "CANCELLED" });
    expect(list).toHaveBeenCalledTimes(1);
  });

  it("bounds unique pagination and fails explicitly without returning a partial directory", async () => {
    let page = 0;
    list.mockImplementation(async () => ({ results: [], next_cursor: `page-${++page}` }));
    await expect(port.listProducts("example", WORKSPACE, new AbortController().signal)).rejects.toMatchObject({
      code: "UNAVAILABLE",
    });
    expect(list).toHaveBeenCalledTimes(100);
  });

  it("uses the typed precondition read unchanged, with exact IDs and cancellation", async () => {
    read.mockResolvedValue({ data: discovery, etag: "exact" });
    const scope = { workspaceId: WORKSPACE, productId: PRODUCT };
    const signal = new AbortController().signal;
    expect(await port.discover("example", scope, PROJECT, signal)).toEqual(discovery);
    expect(read).toHaveBeenCalledWith("example", scope, PROJECT, signal);
    expect(create).not.toHaveBeenCalled();
  });
});
