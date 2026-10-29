/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { AxiosHeaders } from "axios";
import type { AxiosResponse } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CurveRoadmapHierarchyService } from "../src/curve/roadmap-hierarchy.service";
const id = (n: number) => `94000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope = { workspaceId: id(1), productId: id(2), roadmapId: id(3) };
const common = () => ({
  id: id(4),
  version: 1,
  name: "Example milestone",
  created_at: "2026-10-28T10:00:00+00:00",
  updated_at: "2026-10-28T10:00:00.123456+00:00",
});
const hierarchy = () => ({
  ...common(),
  schema_version: "1.0",
  workspace_id: scope.workspaceId,
  product_id: scope.productId,
});
const roadmap = () => ({ ...hierarchy(), owner_user_id: id(5), horizon_start: null, horizon_end: null });
const milestone = () => ({
  ...hierarchy(),
  roadmap_id: scope.roadmapId,
  type: "PRODUCT_OUTCOME",
  position: 0,
  target_start: null,
  target_end: "2026-11-01",
});
const response = (data: unknown, headers: Record<string, string> = {}): AxiosResponse => ({
  data,
  status: 200,
  headers,
  statusText: "",
  config: { headers: new AxiosHeaders() },
});
const etag = `"curve-roadmap:${scope.roadmapId}:v2"`;
afterEach(() => vi.restoreAllMocks());
describe("bounded Roadmap choices", () => {
  it("reads Roadmaps with exact encoded scope, bounded timeout and no-store without writes", async () => {
    const client = new CurveRoadmapHierarchyService();
    const payload = { results: [roadmap()], next_cursor: null };
    const get = vi.spyOn(client, "get").mockResolvedValue(response(payload));
    const post = vi.spyOn(client, "post");
    const signal = new AbortController().signal;
    const result = await client.listRoadmaps("example/workspace", scope, { pageSize: 1, signal });
    expect(get).toHaveBeenCalledExactlyOnceWith(
      `/api/v1/workspaces/example%2Fworkspace/curve/products/${scope.productId}/roadmaps/?page_size=1`,
      { signal, timeout: 60000, headers: { "Cache-Control": "no-store" } }
    );
    expect(result).toEqual(payload);
    expect(post).not.toHaveBeenCalled();
    payload.results[0].name = "Changed";
    expect(result.results[0].name).toBe("Example milestone");
  });
  it("checks the milestone ordering cursor against its parent version and ETag", async () => {
    const client = new CurveRoadmapHierarchyService();
    const cursor = `2:0:${id(4)}`;
    const get = vi
      .spyOn(client, "get")
      .mockResolvedValue(
        response(
          { results: [{ ...milestone(), id: id(6), position: 1 }], next_cursor: `2:1:${id(6)}`, roadmap_version: 2 },
          { etag }
        )
      );
    const result = await client.listMilestones("example", scope, { pageSize: 1, cursor });
    expect(get.mock.calls[0][0]).toContain(`cursor=${encodeURIComponent(cursor)}`);
    expect(result.next_cursor).toBe(`2:1:${id(6)}`);
  });
  it("reads metadata-only Features with the endpoint's after cursor", async () => {
    const client = new CurveRoadmapHierarchyService();
    const get = vi
      .spyOn(client, "get")
      .mockResolvedValue(response({ results: [common()], next_cursor: id(4), is_editor: false }));
    const result = await client.listFeatures("example", scope, { pageSize: 1, cursor: id(3) });
    expect(get.mock.calls[0][0]).toContain(`features/?page_size=1&after=${id(3)}`);
    expect(result.is_editor).toBe(false);
  });
  it.each(["workspace_id", "product_id"])("rejects hierarchy from a different %s", async (field) => {
    const client = new CurveRoadmapHierarchyService();
    vi.spyOn(client, "get").mockResolvedValue(
      response({ results: [{ ...roadmap(), [field]: id(99) }], next_cursor: null })
    );
    await expect(client.listRoadmaps("example", scope)).rejects.toMatchObject({ code: "INVALID" });
  });
  it.each(["description", "scope_body", "approval_stages"])(
    "rejects unexpected protected or derived Feature field %s",
    async (field) => {
      const client = new CurveRoadmapHierarchyService();
      vi.spyOn(client, "get").mockResolvedValue(
        response({ results: [{ ...common(), [field]: "Unexpected" }], next_cursor: null, is_editor: true })
      );
      await expect(client.listFeatures("example", scope)).rejects.toMatchObject({ code: "INVALID" });
    }
  );
  it.each([
    { version: 3 },
    { etag: "W/" + etag },
    { roadmap: id(99) },
    { position: -1 },
    { type: "UNKNOWN" },
    { date: "2026-02-30" },
    { next: `2:5:${id(9)}` },
  ])("rejects malformed or stale milestone metadata %o", async (change) => {
    const client = new CurveRoadmapHierarchyService();
    vi.spyOn(client, "get").mockResolvedValue(
      response(
        {
          results: [
            {
              ...milestone(),
              roadmap_id: change.roadmap ?? scope.roadmapId,
              position: change.position ?? 0,
              type: change.type ?? "PRODUCT_OUTCOME",
              target_end: change.date ?? null,
            },
          ],
          next_cursor: change.next ?? null,
          roadmap_version: change.version ?? 2,
        },
        { etag: change.etag ?? etag }
      )
    );
    await expect(client.listMilestones("example", scope, { pageSize: 1 })).rejects.toMatchObject({ code: "INVALID" });
  });
  it("rejects a continuation after the parent version changed even with a matching new ETag", async () => {
    const client = new CurveRoadmapHierarchyService();
    vi.spyOn(client, "get").mockResolvedValue(
      response(
        { results: [], next_cursor: null, roadmap_version: 3 },
        { etag: `"curve-roadmap:${scope.roadmapId}:v3"` }
      )
    );
    await expect(client.listMilestones("example", scope, { cursor: `2:0:${id(4)}` })).rejects.toMatchObject({
      code: "INVALID",
    });
  });
  it("rejects duplicate or backwards list rows", async () => {
    const client = new CurveRoadmapHierarchyService();
    vi.spyOn(client, "get").mockResolvedValue(response({ results: [roadmap(), roadmap()], next_cursor: null }));
    await expect(client.listRoadmaps("example", scope)).rejects.toMatchObject({ code: "INVALID" });
  });
  it("rejects invalid scope and pagination before transport", async () => {
    const client = new CurveRoadmapHierarchyService();
    const get = vi.spyOn(client, "get");
    await expect(client.listRoadmaps("example", { ...scope, workspaceId: "bad" })).rejects.toMatchObject({
      code: "INVALID",
    });
    await expect(client.listFeatures("example", scope, { pageSize: 101 })).rejects.toMatchObject({ code: "INVALID" });
    await expect(
      client.listMilestones("example", scope, { cursor: `1:9007199254740992:${id(4)}` })
    ).rejects.toMatchObject({ code: "INVALID" });
    expect(get).not.toHaveBeenCalled();
  });
  it("retains access and stale-order errors as sanitized errors", async () => {
    const client = new CurveRoadmapHierarchyService();
    const get = vi.spyOn(client, "get");
    get
      .mockRejectedValueOnce({ response: { status: 403, data: "Private detail" } })
      .mockRejectedValueOnce({ response: { status: 412 } });
    await expect(client.listFeatures("example", scope)).rejects.toMatchObject({ code: "UNAVAILABLE", status: 403 });
    await expect(client.listMilestones("example", scope)).rejects.toMatchObject({ code: "CONFLICT", status: 412 });
  });
  it("does not read after cancellation", async () => {
    const client = new CurveRoadmapHierarchyService();
    const get = vi.spyOn(client, "get");
    const controller = new AbortController();
    controller.abort();
    await expect(client.listRoadmaps("example", scope, { signal: controller.signal })).rejects.toMatchObject({
      code: "CANCELLED",
    });
    expect(get).not.toHaveBeenCalled();
  });
});
