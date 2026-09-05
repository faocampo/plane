/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ICurveInitiative, ICurveInitiativeCreateRequest } from "@plane/types";
import { CurveService } from "@plane/services";

const initiative: ICurveInitiative = {
  schema_version: "1.1",
  id: "initiative-1",
  workspace_id: "workspace-1",
  product_id: "product-1",
  mode: "STANDALONE",
  roadmap_item_id: null,
  keyword: "capability-overview",
  title: "Example capability overview",
  description: { schema_version: "1.0", format: "MARKDOWN", body: "Show compatibility state." },
  risk_tier: "STANDARD",
  business_intent: "STRATEGIC",
  state: "DRAFT",
  paused_from_state: null,
  workflow_version_id: null,
  creator: { actor_type: "HUMAN", actor_id: "user-1" },
  gate_assignments: [],
  first_external_resource_at: null,
  version: 1,
  created_at: "2026-09-01T12:00:00Z",
  updated_at: "2026-09-01T12:00:00Z",
  updated_by: { actor_type: "HUMAN", actor_id: "user-1" },
};

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
    { gate_type: "PRD_APPROVAL", approver_user_id: "user-1" },
    { gate_type: "PLAN_APPROVAL", approver_user_id: "user-2" },
    { gate_type: "CODE_READINESS", approver_user_id: "user-3" },
  ],
};

describe("Curve Initiative service", () => {
  let service: CurveService;

  beforeEach(() => {
    service = new CurveService("http://curve.test");
    vi.restoreAllMocks();
  });

  it("uses the governed Product and Initiative list filters", async () => {
    const get = vi.spyOn(service, "get");
    get.mockResolvedValueOnce({ data: { results: [], next_cursor: "product-next" } } as never);
    get.mockResolvedValueOnce({ data: { results: [initiative], next_cursor: "initiative-next" } } as never);

    await expect(service.listProducts("example-workspace", { cursor: "product-cursor" })).resolves.toEqual({
      results: [],
      next_cursor: "product-next",
    });
    await expect(
      service.listInitiatives("example-workspace", {
        state: "DRAFT",
        productId: "product-1",
        cursor: "initiative-cursor",
      })
    ).resolves.toEqual({ results: [initiative], next_cursor: "initiative-next" });

    expect(get).toHaveBeenNthCalledWith(1, "/api/v1/workspaces/example-workspace/curve/products/", {
      params: { state: "ACTIVE", page_size: 100, cursor: "product-cursor" },
    });
    expect(get).toHaveBeenNthCalledWith(2, "/api/v1/workspaces/example-workspace/curve/initiatives/", {
      params: {
        page_size: 100,
        cursor: "initiative-cursor",
        state: "DRAFT",
        product_id: "product-1",
      },
    });
  });

  it("returns the commit-bound Initiative representation and ETag", async () => {
    vi.spyOn(service, "get").mockResolvedValue({
      data: initiative,
      headers: { etag: 'W/"curve-initiative:initiative-1:v1"' },
    } as never);

    await expect(service.retrieveInitiative("example-workspace", initiative.id)).resolves.toEqual({
      initiative,
      etag: '"curve-initiative:initiative-1:v1"',
    });
  });

  it("rejects with the normalized HTTP response for fail-closed UI handling", async () => {
    const response = { status: 403, data: { detail: "private server diagnostic" } };
    vi.spyOn(service, "get").mockRejectedValue({ response });

    await expect(service.listInitiatives("example-workspace")).rejects.toEqual(response);
  });

  it("creates an Initiative with CSRF and one caller-provided idempotency key", async () => {
    vi.spyOn(service, "get").mockResolvedValue({ data: { csrf_token: "csrf-token" } } as never);
    const post = vi.spyOn(service, "post").mockResolvedValue({
      data: initiative,
      headers: {
        etag: '"curve-initiative:initiative-1:v1"',
        location: "/api/v1/workspaces/example-workspace/curve/initiatives/initiative-1/",
      },
    } as never);

    await expect(service.createInitiative("example-workspace", createPayload, "command-1")).resolves.toEqual({
      initiative,
      etag: '"curve-initiative:initiative-1:v1"',
      location: "/api/v1/workspaces/example-workspace/curve/initiatives/initiative-1/",
    });
    expect(post).toHaveBeenCalledWith("/api/v1/workspaces/example-workspace/curve/initiatives/", createPayload, {
      headers: {
        "Idempotency-Key": "command-1",
        "X-CSRFTOKEN": "csrf-token",
      },
    });
  });

  it("updates Draft business intent with optimistic concurrency", async () => {
    vi.spyOn(service, "get").mockResolvedValue({ data: { csrf_token: "csrf-token" } } as never);
    const patch = vi.spyOn(service, "patch").mockResolvedValue({
      data: { ...initiative, business_intent: "CUSTOMER_COMMITMENT", version: 2 },
      headers: { etag: '"curve-initiative:initiative-1:v2"' },
    } as never);

    await service.updateInitiativeDraft(
      "example-workspace",
      initiative.id,
      { business_intent: "CUSTOMER_COMMITMENT" },
      'W/"v1"',
      "command-update"
    );

    expect(patch).toHaveBeenCalledWith(
      `/api/v1/workspaces/example-workspace/curve/initiatives/${initiative.id}/`,
      { business_intent: "CUSTOMER_COMMITMENT" },
      {
        headers: {
          "Idempotency-Key": "command-update",
          "If-Match": '"v1"',
          "X-CSRFTOKEN": "csrf-token",
        },
      }
    );
  });

  it.each([
    ["accept", "accept-refinement", {}, "acceptInitiativeRefinement"],
    ["pause", "pause", { reason: "Dependency unavailable" }, "pauseInitiative"],
    ["resume", "resume", { reason: "Dependency restored" }, "resumeInitiative"],
    ["cancel", "cancel", { reason: "Outcome no longer needed" }, "cancelInitiative"],
  ] as const)("sends the %s transition with optimistic concurrency", async (_label, action, payload, method) => {
    vi.spyOn(service, "get").mockResolvedValue({ data: { csrf_token: "csrf-token" } } as never);
    const post = vi.spyOn(service, "post").mockResolvedValue({
      data: { ...initiative, version: 2 },
      headers: { etag: '"curve-initiative:initiative-1:v2"' },
    } as never);

    if (method === "acceptInitiativeRefinement") {
      await service.acceptInitiativeRefinement("example-workspace", initiative.id, '"v1"', "command-2");
    } else {
      await service[method]("example-workspace", initiative.id, payload, '"v1"', "command-2");
    }

    expect(post).toHaveBeenCalledWith(
      `/api/v1/workspaces/example-workspace/curve/initiatives/${initiative.id}/${action}/`,
      payload,
      {
        headers: {
          "Idempotency-Key": "command-2",
          "If-Match": '"v1"',
          "X-CSRFTOKEN": "csrf-token",
        },
      }
    );
  });
});
