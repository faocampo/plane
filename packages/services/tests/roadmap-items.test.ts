/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import type { AxiosResponse } from "axios";
import { AxiosHeaders } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CurveItemCreate, CurveItemPage } from "../../types/src/curve-roadmap-items";
import { CurveExistingWorkError } from "../src/curve/existing-work-validation";
import { CurveRoadmapItemService } from "../src/curve/roadmap-items.service";
import { decodeItemCreate, decodeItemPage } from "../src/curve/roadmap-items.validation";

const id = (n: number) => `95000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope = { productId: id(1), roadmapId: id(2) };
const path = `/api/v1/workspaces/example%2Fworkspace/curve/products/${scope.productId}/roadmaps/${scope.roadmapId}/items/`;
function payload(): CurveItemCreate {
  return {
    initiative: {
      keyword: "DEMO",
      title: "Café launch",
      description: { schema_version: "1.0", format: "MARKDOWN", body: "Synthetic scope" },
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
  };
}
function page(): CurveItemPage {
  return {
    results: [
      {
        id: id(8),
        version: 1,
        roadmap_id: scope.roadmapId,
        milestone_id: id(3),
        feature_id: id(4),
        owner_user_id: id(5),
        status: "PROPOSED",
        priority: "MEDIUM",
        confidence: "HIGH",
        health: "UNKNOWN",
        planned_start: null,
        planned_end: null,
        declared_progress: 0,
        initiative: { id: id(9), version: 1, keyword: "DEMO", title: "Café launch", state: "DRAFT" },
        approval_stages: [
          { role: "PRODUCT", gate_type: "PRD_APPROVAL", approver_user_id: id(5) },
          { role: "TECHNICAL", gate_type: "PLAN_APPROVAL", approver_user_id: id(6) },
        ],
      },
    ],
    next_cursor: null,
    roadmap_version: 2,
    can_create: true,
  };
}
function response(data: unknown, status = 200, headers: Record<string, string> = {}): AxiosResponse {
  return { data, status, headers, statusText: "", config: { headers: new AxiosHeaders() } };
}
function created() {
  return response(
    {
      resource_ref: {
        resource_type: "ROADMAP_ITEM",
        resource_id: id(8),
        resource_version: 1,
        initiative_ref: { resource_type: "INITIATIVE", resource_id: id(9), resource_version: 1 },
      },
    },
    201,
    { etag: `"curve-roadmap-item:${id(8)}:v1"`, "idempotent-replay": "false" }
  );
}
afterEach(() => vi.restoreAllMocks());

describe("Roadmap item client", () => {
  it("reads only its exact scope with bounded cancellation and no mutation", async () => {
    const service = new CurveRoadmapItemService();
    const get = vi.spyOn(service, "get").mockResolvedValue(response(page()));
    const post = vi.spyOn(service, "post");
    const signal = new AbortController().signal;
    await expect(service.list("example/workspace", scope, { pageSize: 25, signal })).resolves.toEqual(page());
    expect(get).toHaveBeenCalledExactlyOnceWith(path + "?page_size=25", {
      signal,
      timeout: 60000,
      headers: { "Cache-Control": "no-store" },
    });
    expect(post).not.toHaveBeenCalled();
  });
  it("sends exactly the two stages with the parent version and retained retry key", async () => {
    const service = new CurveRoadmapItemService();
    const get = vi.spyOn(service, "get").mockResolvedValue(response({ csrf_token: "synthetic-csrf" }));
    const post = vi.spyOn(service, "post").mockResolvedValue(created());
    const signal = new AbortController().signal;
    const result = await service.create("example/workspace", scope, payload(), {
      expectedVersion: 2,
      idempotencyKey: "same-key",
      signal,
    });
    expect(get).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledExactlyOnceWith(path, payload(), {
      signal,
      timeout: 60000,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
        "X-CSRFTOKEN": "synthetic-csrf",
        "If-Match": `"curve-roadmap:${scope.roadmapId}:v2"`,
        "Idempotency-Key": "same-key",
      },
    });
    expect(result.replayed).toBe(false);
    expect(result.resource_ref.initiative_ref.resource_id).toBe(id(9));
  });
  it("detaches the command before CSRF completes", async () => {
    const service = new CurveRoadmapItemService();
    let complete!: (value: AxiosResponse) => void;
    vi.spyOn(service, "get").mockReturnValue(
      new Promise((resolve) => {
        complete = resolve;
      })
    );
    const post = vi.spyOn(service, "post").mockResolvedValue(created());
    const body = payload();
    const pending = service.create("example/workspace", scope, body, {
      expectedVersion: 2,
      idempotencyKey: "same-key",
    });
    body.initiative.gate_assignments[0].approver_user_id = id(99);
    complete(response({ csrf_token: "synthetic" }));
    await pending;
    expect(post.mock.calls[0]?.[1]).toEqual(payload());
  });
  it.each(["timeout", "bad-response", "weak-etag", "missing-replay", "wrong-stage"])(
    "keeps %s write outcomes unknown without retry",
    async (failure) => {
      const service = new CurveRoadmapItemService();
      vi.spyOn(service, "get").mockResolvedValue(response({ csrf_token: "synthetic" }));
      const value = created();
      if (failure === "bad-response") value.data = { approved: true };
      if (failure === "weak-etag") value.headers.etag = "W/" + value.headers.etag;
      if (failure === "missing-replay") delete value.headers["idempotent-replay"];
      if (failure === "wrong-stage") value.data.resource_ref.initiative_ref.resource_type = "CODE_READINESS";
      const post = vi.spyOn(service, "post");
      if (failure === "timeout") post.mockRejectedValue(new Error("private raw request"));
      else post.mockResolvedValue(value);
      await expect(
        service.create("example/workspace", scope, payload(), { expectedVersion: 2, idempotencyKey: "same-key" })
      ).rejects.toMatchObject({ code: "MUTATION_OUTCOME_UNKNOWN" });
      expect(post).toHaveBeenCalledTimes(1);
    }
  );
  it("preserves successful replay and distinguishes rejected conflicts", async () => {
    const service = new CurveRoadmapItemService();
    vi.spyOn(service, "get").mockResolvedValue(response({ csrf_token: "synthetic" }));
    const value = created();
    value.headers["idempotent-replay"] = "true";
    const post = vi
      .spyOn(service, "post")
      .mockResolvedValueOnce(value)
      .mockRejectedValueOnce({ response: { status: 412 } });
    const options = { expectedVersion: 2, idempotencyKey: "same-key" };
    expect((await service.create("example/workspace", scope, payload(), options)).replayed).toBe(true);
    await expect(service.create("example/workspace", scope, payload(), options)).rejects.toMatchObject({
      code: "CONFLICT",
      status: 412,
    });
    expect(post).toHaveBeenCalledTimes(2);
  });
  it("rejects cancelled and invalid commands before any request", async () => {
    const service = new CurveRoadmapItemService();
    const get = vi.spyOn(service, "get");
    const post = vi.spyOn(service, "post");
    const controller = new AbortController();
    controller.abort();
    await expect(
      service.create("example/workspace", scope, payload(), {
        expectedVersion: 2,
        idempotencyKey: "same-key",
        signal: controller.signal,
      })
    ).rejects.toMatchObject({ code: "CANCELLED" });
    await expect(
      service.create("example/workspace", scope, payload(), {
        expectedVersion: Number.MAX_SAFE_INTEGER + 1,
        idempotencyKey: "same-key",
      })
    ).rejects.toMatchObject({ code: "INVALID" });
    expect(get).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
  });
});

describe("closed item projections", () => {
  it.each(["extra-authority", "code-role", "same-reviewer", "invalid-calendar", "unpaired-date", "nul-text"])(
    "rejects invalid creation %s",
    (damage) => {
      const value = payload();
      if (damage === "extra-authority") Object.assign(value, { owner_id: id(5) });
      if (damage === "code-role") Object.assign(value.initiative.gate_assignments[0], { gate_type: "CODE_READINESS" });
      if (damage === "same-reviewer") value.initiative.gate_assignments[1].approver_user_id = id(5);
      if (damage === "invalid-calendar") {
        value.planned_start = "2026-02-30";
        value.planned_end = "2026-03-01";
      }
      if (damage === "unpaired-date") value.planned_start = "2026-01-01";
      if (damage === "nul-text") value.initiative.title = "bad\0text";
      expect(() => decodeItemCreate(value)).toThrow();
    }
  );
  it("allows a shared reviewer for LOW risk and returns detached metadata", () => {
    const value = payload();
    value.initiative.risk_tier = "LOW";
    value.initiative.gate_assignments[1].approver_user_id = id(5);
    expect(decodeItemCreate(value)).toEqual(value);
    const original = page();
    const result = decodeItemPage(original, scope, 50);
    original.results[0]!.initiative.title = "Changed";
    expect(result.results[0]!.initiative.title).toBe("Café launch");
  });
  it.each([
    "foreign-roadmap",
    "protected-field",
    "approval-result",
    "code-role",
    "duplicate-id",
    "invalid-cursor",
    "unsafe-version",
  ])("rejects unverified read %s", (damage) => {
    const value = page();
    const item = value.results[0]!;
    if (damage === "foreign-roadmap") item.roadmap_id = id(99);
    if (damage === "protected-field") Object.assign(item, { scope_body: payload().scope_body });
    if (damage === "approval-result") Object.assign(item.approval_stages[0], { approved: true });
    if (damage === "code-role") Object.assign(item.approval_stages[1], { gate_type: "CODE_READINESS" });
    if (damage === "duplicate-id") value.results.push(structuredClone(item));
    if (damage === "invalid-cursor") value.next_cursor = id(99);
    if (damage === "unsafe-version") value.roadmap_version = Number.MAX_SAFE_INTEGER + 1;
    expect(() => decodeItemPage(value, scope, 50)).toThrow();
  });
});

describe("protected Item scope preparation", () => {
  const options = { expectedVersion: 2, idempotencyKey: "synthetic-scope-key" };
  function prepared() {
    return response(
      {
        resource_ref: {
          resource_type: "PREPARED_ITEM_SCOPE",
          resource_id: id(7),
          resource_version: 1,
          scope_body: {
            object_id: id(7),
            digest: "sha256:" + "a".repeat(64),
            size_bytes: 80,
            media_type: "application/json",
            editor_schema_version: "curve.item-scope-markdown/v1-candidate",
          },
        },
      },
      201,
      { "idempotent-replay": "false" }
    );
  }
  it("prepares once with CSRF, the exact Roadmap version and caller-owned recovery key", async () => {
    const service = new CurveRoadmapItemService();
    vi.spyOn(service, "get").mockResolvedValue(response({ csrf_token: "synthetic-csrf" }));
    const post = vi.spyOn(service, "post").mockResolvedValue(prepared());
    const result = await service.prepareScope("example/workspace", scope, { body: "Café outcome" }, options);
    expect(result.resource_ref.scope_body.object_id).toBe(id(7));
    expect(result.replayed).toBe(false);
    expect(post).toHaveBeenCalledTimes(1);
    expect(post.mock.calls[0]?.slice(0, 2)).toEqual([
      path.replace("/items/", "/item-scopes/"),
      { body: "Café outcome" },
    ]);
    expect(post.mock.calls[0]?.[2]).toMatchObject({
      headers: {
        "X-CSRFTOKEN": "synthetic-csrf",
        "If-Match": `"curve-roadmap:${scope.roadmapId}:v2"`,
        "Idempotency-Key": options.idempotencyKey,
      },
    });
  });
  it.each(["", "   ", "\0", "\ud800", "a".repeat(20001)])(
    "rejects invalid body before network access",
    async (body) => {
      const service = new CurveRoadmapItemService();
      const get = vi.spyOn(service, "get");
      const post = vi.spyOn(service, "post");
      await expect(service.prepareScope("example/workspace", scope, { body }, options)).rejects.toBeDefined();
      expect(get).not.toHaveBeenCalled();
      expect(post).not.toHaveBeenCalled();
    }
  );
  it.each(["identity", "schema", "replay", "extra"])(
    "treats malformed success as unknown without automatic retry: %s",
    async (variant) => {
      const service = new CurveRoadmapItemService();
      vi.spyOn(service, "get").mockResolvedValue(response({ csrf_token: "synthetic-csrf" }));
      const reply = prepared();
      if (variant === "identity") reply.data.resource_ref.scope_body.object_id = id(9);
      if (variant === "schema") reply.data.resource_ref.scope_body.editor_schema_version = "unknown";
      if (variant === "replay") delete reply.headers["idempotent-replay"];
      if (variant === "extra") reply.data.resource_ref.approved = true;
      const post = vi.spyOn(service, "post").mockResolvedValue(reply);
      await expect(
        service.prepareScope("example/workspace", scope, { body: "Outcome" }, options)
      ).rejects.toMatchObject({ code: "MUTATION_OUTCOME_UNKNOWN" });
      expect(post).toHaveBeenCalledTimes(1);
    }
  );
});

describe("Item creation receipt reconciliation", () => {
  it("reads a closed completed receipt with the command key in a header", async () => {
    const service = new CurveRoadmapItemService();
    const ref = created().data.resource_ref;
    const get = vi.spyOn(service, "get").mockResolvedValue(response({ state: "COMPLETED", resource_ref: ref }));
    const post = vi.spyOn(service, "post");
    await expect(service.reconcileCreation("example", scope, id(22))).resolves.toEqual({
      state: "COMPLETED",
      resource_ref: ref,
    });
    expect(get).toHaveBeenCalledWith(
      expect.stringContaining("/item-creation-receipts/"),
      expect.objectContaining({ headers: { "Idempotency-Key": id(22), "Cache-Control": "no-store" }, timeout: 60000 })
    );
    expect(get.mock.calls[0][0]).not.toContain(id(22));
    expect(post).not.toHaveBeenCalled();
  });
  it("keeps an absent receipt unresolved and does not create", async () => {
    const service = new CurveRoadmapItemService();
    vi.spyOn(service, "get").mockResolvedValue(response({ state: "UNRESOLVED" }));
    const post = vi.spyOn(service, "post");
    await expect(service.reconcileCreation("example", scope, id(22))).resolves.toEqual({ state: "UNRESOLVED" });
    expect(post).not.toHaveBeenCalled();
  });
  it.each([
    null,
    { state: "NOT_CREATED" },
    { state: "UNRESOLVED", resource_ref: {} },
    { state: "COMPLETED", resource_ref: {} },
    { state: "COMPLETED", resource_ref: { ...created().data.resource_ref, body: "synthetic" } },
  ])("rejects malformed or expanded recovery results", async (body) => {
    const service = new CurveRoadmapItemService();
    vi.spyOn(service, "get").mockResolvedValue(response(body));
    await expect(service.reconcileCreation("example", scope, id(22))).rejects.toBeInstanceOf(CurveExistingWorkError);
  });
  it("does not send an invalid locator or a cancelled read", async () => {
    const service = new CurveRoadmapItemService();
    const get = vi.spyOn(service, "get");
    await expect(service.reconcileCreation("example", scope, "invalid")).rejects.toBeInstanceOf(CurveExistingWorkError);
    const controller = new AbortController();
    controller.abort();
    await expect(service.reconcileCreation("example", scope, id(22), controller.signal)).rejects.toBeInstanceOf(
      CurveExistingWorkError
    );
    expect(get).not.toHaveBeenCalled();
  });
});

describe("Item creation cancellation", () => {
  it.each(["CANCELLED", "UNRESOLVED", "COMPLETED"])(
    "accepts the closed %s outcome with CSRF and the original key",
    async (state) => {
      const service = new CurveRoadmapItemService();
      vi.spyOn(service, "get").mockResolvedValue(response({ csrf_token: "synthetic-csrf" }));
      const body = state === "COMPLETED" ? { state, resource_ref: created().data.resource_ref } : { state };
      const post = vi.spyOn(service, "post").mockResolvedValue(response(body));
      await expect(service.cancelCreation("example", scope, id(22))).resolves.toEqual(body);
      expect(post).toHaveBeenCalledTimes(1);
      expect(post.mock.calls[0]?.slice(0, 2)).toEqual([expect.stringContaining("/item-creation-receipts/cancel/"), {}]);
      const headers = post.mock.calls[0]?.[2]?.headers;
      expect(headers).toMatchObject({
        "Idempotency-Key": id(22),
        "X-CSRFTOKEN": "synthetic-csrf",
        "Cache-Control": "no-store",
      });
      expect(headers).not.toHaveProperty("If-Match");
    }
  );
  it.each([
    null,
    { state: "CANCELLED", extra: true },
    { state: "NOT_CREATED" },
    { state: "COMPLETED", resource_ref: {} },
  ])("preserves uncertainty on malformed responses", async (body) => {
    const service = new CurveRoadmapItemService();
    vi.spyOn(service, "get").mockResolvedValue(response({ csrf_token: "synthetic-csrf" }));
    const post = vi.spyOn(service, "post").mockResolvedValue(response(body));
    await expect(service.cancelCreation("example", scope, id(22))).rejects.toMatchObject({
      code: "MUTATION_OUTCOME_UNKNOWN",
    });
    expect(post).toHaveBeenCalledTimes(1);
  });
  it("does not send invalid or already-aborted requests", async () => {
    const service = new CurveRoadmapItemService();
    const get = vi.spyOn(service, "get");
    const post = vi.spyOn(service, "post");
    await expect(service.cancelCreation("example", scope, "invalid")).rejects.toBeDefined();
    const controller = new AbortController();
    controller.abort();
    await expect(service.cancelCreation("example", scope, id(22), controller.signal)).rejects.toMatchObject({
      code: "CANCELLED",
    });
    expect(get).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
  });
  it("does not retry a lost cancellation response automatically", async () => {
    const service = new CurveRoadmapItemService();
    vi.spyOn(service, "get").mockResolvedValue(response({ csrf_token: "synthetic-csrf" }));
    const post = vi.spyOn(service, "post").mockRejectedValue(new Error("synthetic network loss"));
    await expect(service.cancelCreation("example", scope, id(22))).rejects.toMatchObject({
      code: "MUTATION_OUTCOME_UNKNOWN",
    });
    expect(post).toHaveBeenCalledTimes(1);
  });
});
