/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import type { AxiosResponse } from "axios";
import { AxiosHeaders } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CurveProjectAssociationPreconditionsV1 } from "../../types/src/curve-project-association-preconditions";
import {
  CurveProjectAssociationPreconditionsService,
  decodeCurveProjectAssociationPreconditionsV1,
} from "../src/curve/project-association-preconditions.service";
import { CurveExistingWorkReadSlot } from "../src/curve/existing-work-read-state";
import { CurveExistingWorkError } from "../src/curve/existing-work-validation";

const scope = {
  workspaceId: "00000000-0000-0000-0000-000000000001",
  productId: "00000000-0000-0000-0000-000000000002",
};
const sourceId = "00000000-0000-0000-0000-000000000003";
const otherId = "ffffffff-ffff-ffff-ffff-ffffffffffff";
const etag = `"curve-product:${scope.productId}:v7"`;
const fixture = (): CurveProjectAssociationPreconditionsV1 => ({
  schema_version: "curve.project-association-precondition/v1-candidate",
  policy_edition: "LOCAL_NATIVE_PROJECT_ASSOCIATION_PRECONDITION_READ_V1",
  workspace_id: scope.workspaceId,
  product_id: scope.productId,
  product_version: 7,
  provider_installation_id: "00000000-0000-0000-0000-000000000004",
  source_project_id: sourceId,
  availability: "AVAILABLE",
  association_id: null,
  observed_at: "2026-10-04T12:00:00.123Z",
});
const response = (data: unknown): AxiosResponse => ({
  status: 200,
  statusText: "",
  config: { headers: new AxiosHeaders() },
  data,
  headers: { etag },
});
afterEach(() => vi.restoreAllMocks());

describe("closed native association prerequisite read", () => {
  it("pins the separately mirrored backend schema", () => {
    const manifest = JSON.parse(
      readFileSync(new URL("../src/curve/existing-work-contracts/manifest.json", import.meta.url), "utf8")
    );
    const entry = manifest.find((item: { name: string }) => item.name === "project-association-precondition-v1");
    const mirror = readFileSync(
      new URL("../src/curve/existing-work-contracts/project-association-precondition-v1.schema.json", import.meta.url)
    );
    const source = readFileSync(new URL(`../../../${entry.source}`, import.meta.url));
    expect(mirror).toEqual(source);
    expect(createHash("sha256").update(mirror).digest("hex")).toBe(entry.sha256);
  });
  it("uses only exact GET, no-store and cancellation, without CSRF or mutation", async () => {
    const service = new CurveProjectAssociationPreconditionsService();
    const get = vi.spyOn(service, "get").mockResolvedValue(response(fixture()));
    const post = vi.spyOn(service, "post");
    const patch = vi.spyOn(service, "patch");
    const remove = vi.spyOn(service, "delete");
    const signal = new AbortController().signal;
    await expect(service.retrieve("example/workspace", scope, sourceId, signal)).resolves.toEqual({
      data: fixture(),
      etag,
    });
    expect(get).toHaveBeenCalledExactlyOnceWith(
      `/api/v1/workspaces/example%2Fworkspace/curve/products/${scope.productId}/project-association-preconditions/?source_project_id=${sourceId}`,
      { signal, headers: { "Cache-Control": "no-store" } }
    );
    expect(post).not.toHaveBeenCalled();
    expect(patch).not.toHaveBeenCalled();
    expect(remove).not.toHaveBeenCalled();
  });
  it.each(["workspace_id", "product_id", "source_project_id"])("rejects swapped exact target %s", async (field) => {
    const service = new CurveProjectAssociationPreconditionsService();
    vi.spyOn(service, "get").mockResolvedValue(response({ ...fixture(), [field]: otherId }));
    await expect(service.retrieve("example", scope, sourceId)).rejects.toMatchObject({ code: "INVALID" });
  });
  it.each([
    undefined,
    '"7"',
    `"curve-product:${scope.productId}:v6"`,
    `"curve-product:${otherId}:v7"`,
    `W/${etag}`,
    `"curve-project-association:${sourceId}:v7"`,
  ])("rejects invalid Product ETag %#", async (value) => {
    const service = new CurveProjectAssociationPreconditionsService();
    const returned = response(fixture());
    returned.headers.etag = value;
    vi.spyOn(service, "get").mockResolvedValue(returned);
    await expect(service.retrieve("example", scope, sourceId)).rejects.toMatchObject({ code: "INVALID" });
  });
  it.each(["can_associate", "name", "description", "source_body", "other_product_id", "other_association_id", "role"])(
    "rejects expanded field %s",
    (field) => {
      expect(() =>
        decodeCurveProjectAssociationPreconditionsV1({ ...fixture(), [field]: "private" }, scope, sourceId)
      ).toThrow(CurveExistingWorkError);
    }
  );
  it.each([
    { schema_version: "1.0" },
    { policy_edition: "OTHER" },
    { provider_installation_id: "invalid" },
    { product_version: true },
    { product_version: 0 },
    { product_version: 1.2 },
    { product_version: Number.MAX_SAFE_INTEGER + 1 },
    { availability: "HIDDEN" },
    { availability: "ASSOCIATED_WITH_SELECTED_PRODUCT", association_id: null },
    { availability: "ASSOCIATED_ELSEWHERE", association_id: otherId },
    { availability: "AVAILABLE", association_id: otherId },
    { observed_at: "invalid" },
    { observed_at: "2026-10-04T12:00:00+00:00" },
  ])("rejects malformed and contradictory metadata %#", (change) => {
    expect(() => decodeCurveProjectAssociationPreconditionsV1({ ...fixture(), ...change }, scope, sourceId)).toThrow(
      CurveExistingWorkError
    );
  });
  it.each([
    { availability: "AVAILABLE", association_id: null },
    { availability: "ASSOCIATED_ELSEWHERE", association_id: null },
    { availability: "ASSOCIATED_WITH_SELECTED_PRODUCT", association_id: otherId },
  ])("preserves each advisory availability without deriving authority %#", (change) => {
    const result = decodeCurveProjectAssociationPreconditionsV1({ ...fixture(), ...change }, scope, sourceId);
    expect(result).toEqual({ ...fixture(), ...change });
    expect(Object.keys(result)).toHaveLength(10);
  });
  it.each([401, 403, 404, 503])(
    "keeps %s unavailable distinct from available and redacts error content",
    async (status) => {
      const service = new CurveProjectAssociationPreconditionsService();
      const get = vi
        .spyOn(service, "get")
        .mockRejectedValue({ response: { status, data: { private: "hidden source" } }, config: { secret: "secret" } });
      const post = vi.spyOn(service, "post");
      const slot = new CurveExistingWorkReadSlot<unknown>();
      await slot.load((signal) => service.retrieve("example", scope, sourceId, signal));
      expect(slot.snapshot).toEqual({ status: "UNAVAILABLE", data: null, code: "UNAVAILABLE" });
      expect(get).toHaveBeenCalledTimes(1);
      expect(post).not.toHaveBeenCalled();
    }
  );
  it.each(["", "../bad", "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF"])(
    "rejects invalid source before network access %#",
    async (id) => {
      const service = new CurveProjectAssociationPreconditionsService();
      const get = vi.spyOn(service, "get");
      await expect(service.retrieve("example", scope, id)).rejects.toMatchObject({ code: "INVALID" });
      expect(get).not.toHaveBeenCalled();
    }
  );
  it("snapshots inputs before waiting and rejects abort even if transport ignores it", async () => {
    const service = new CurveProjectAssociationPreconditionsService();
    let resolve!: (value: AxiosResponse) => void;
    vi.spyOn(service, "get").mockImplementation(
      () =>
        new Promise((yes) => {
          resolve = yes;
        })
    );
    const mutable = { ...scope };
    const result = service.retrieve("example", mutable, sourceId);
    mutable.productId = otherId;
    resolve(response(fixture()));
    await expect(result).resolves.toEqual({ data: fixture(), etag });
    const controller = new AbortController();
    const late = service.retrieve("example", scope, sourceId, controller.signal);
    controller.abort();
    resolve(response(fixture()));
    await expect(late).rejects.toMatchObject({ code: "CANCELLED" });
  });
  it("never retries failed requests", async () => {
    const service = new CurveProjectAssociationPreconditionsService();
    const get = vi.spyOn(service, "get").mockRejectedValue(new Error("network"));
    await expect(service.retrieve("example", scope, sourceId)).rejects.toMatchObject({ code: "TRANSPORT" });
    expect(get).toHaveBeenCalledTimes(1);
  });
});
