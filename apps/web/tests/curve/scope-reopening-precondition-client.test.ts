/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import type { AxiosResponse } from "axios";
import { AxiosHeaders } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CurveScopeReopeningPreconditionsV1 } from "../../../../packages/types/src/curve-scope-reopening-preconditions";
import {
  CurveScopeReopeningPreconditionsService,
  decodeCurveScopeReopeningPreconditionsV1,
} from "../../../../packages/services/src/curve/scope-reopening-preconditions.service";
import { CurveExistingWorkReadSlot } from "../../../../packages/services/src/curve/existing-work-read-state";
import { CurveExistingWorkError } from "../../../../packages/services/src/curve/existing-work-validation";

const target = {
  workspaceId: "00000000-0000-0000-0000-000000000001",
  initiativeId: "00000000-0000-0000-0000-000000000003",
};
const otherId = "ffffffff-ffff-ffff-ffff-ffffffffffff";
const fixture = (): CurveScopeReopeningPreconditionsV1 => ({
  schema_version: "curve.scope-reopening-precondition/v1-candidate",
  policy_edition: "EXPLICIT_SCOPE_REOPENING_PRECONDITION_READ_V1",
  workspace_id: target.workspaceId,
  initiative_id: target.initiativeId,
  initiative_version: 7,
  expected_scope_revision: 2,
  eligibility: "REOPENABLE",
  pending_reopening: false,
});
const response = (data: unknown, etag = '"7"'): AxiosResponse => ({
  status: 200,
  statusText: "",
  config: { headers: new AxiosHeaders() },
  data,
  headers: { etag },
});
afterEach(() => vi.restoreAllMocks());

describe("minimal scope-reopening precondition read", () => {
  it("reads only the exact protected route with cancellation, without old-source reads or CSRF/mutations", async () => {
    const service = new CurveScopeReopeningPreconditionsService();
    const get = vi.spyOn(service, "get").mockResolvedValue(response(fixture()));
    const post = vi.spyOn(service, "post");
    const patch = vi.spyOn(service, "patch");
    const remove = vi.spyOn(service, "delete");
    const signal = new AbortController().signal;
    await expect(service.retrieve("example/workspace", target, signal)).resolves.toEqual({
      data: fixture(),
      etag: '"7"',
    });
    expect(get).toHaveBeenCalledExactlyOnceWith(
      `/api/v1/workspaces/example%2Fworkspace/curve/initiatives/${target.initiativeId}/scope-reopening/v1/preconditions/`,
      { signal, headers: { "Cache-Control": "no-store" } }
    );
    expect(post).not.toHaveBeenCalled();
    expect(patch).not.toHaveBeenCalled();
    expect(remove).not.toHaveBeenCalled();
  });
  it.each(["workspace_id", "initiative_id"])("rejects a swapped target %s", async (field) => {
    const service = new CurveScopeReopeningPreconditionsService();
    vi.spyOn(service, "get").mockResolvedValue(response({ ...fixture(), [field]: otherId }));
    await expect(service.retrieve("example", target)).rejects.toMatchObject({ code: "INVALID" });
  });
  it.each([undefined, '"6"', 'W/"7"', `"curve-initiative:${target.initiativeId}:v7"`])(
    "rejects missing, swapped, weak or wrong-family version headers %#",
    async (etag) => {
      const service = new CurveScopeReopeningPreconditionsService();
      const returned = response(fixture());
      returned.headers.etag = etag;
      vi.spyOn(service, "get").mockResolvedValue(returned);
      await expect(service.retrieve("example", target)).rejects.toMatchObject({ code: "INVALID" });
    }
  );
  it("rejects a stale known Initiative version and validates version expectations before network access", async () => {
    const service = new CurveScopeReopeningPreconditionsService();
    const get = vi.spyOn(service, "get").mockResolvedValue(response(fixture()));
    await expect(service.retrieve("example", { ...target, expectedInitiativeVersion: 8 })).rejects.toMatchObject({
      code: "INVALID",
    });
    await expect(
      service.retrieve("example", { ...target, expectedInitiativeVersion: true } as never)
    ).rejects.toMatchObject({ code: "INVALID" });
    expect(get).toHaveBeenCalledTimes(1);
  });
  it.each(["source_issue_id", "product_id", "members", "item_count", "checkpoint_id", "title", "rationale"])(
    "rejects added private/source field %s",
    (field) => {
      expect(() => decodeCurveScopeReopeningPreconditionsV1({ ...fixture(), [field]: "private" }, target)).toThrow(
        CurveExistingWorkError
      );
    }
  );
  it.each([
    { schema_version: "1.0" },
    { policy_edition: "EXACT_EXISTING_WORK_SCOPED_PRD_V1" },
    { initiative_version: true },
    { expected_scope_revision: 0 },
    { expected_scope_revision: Number.MAX_SAFE_INTEGER + 1 },
    { pending_reopening: "false" },
    { eligibility: "APPROVED" },
  ])("rejects malformed or wrong-edition metadata %#", (changed) => {
    expect(() => decodeCurveScopeReopeningPreconditionsV1({ ...fixture(), ...changed }, target)).toThrow(
      CurveExistingWorkError
    );
  });
  it("preserves advisory blocked/pending state without deriving a capability or consulting old scope", async () => {
    const service = new CurveScopeReopeningPreconditionsService();
    const data = { ...fixture(), eligibility: "STATE_BLOCKED", pending_reopening: true };
    const get = vi.spyOn(service, "get").mockResolvedValue(response(data));
    const result = await service.retrieve("example", target);
    expect(result.data).toEqual(data);
    expect(Object.keys(result.data)).toHaveLength(8);
    expect(result.data).not.toHaveProperty("can_reopen");
    expect(get).toHaveBeenCalledTimes(1);
  });
  it.each([401, 403, 404, 503])(
    "keeps a %s unavailable response distinct from absent scope and never writes a recovery command",
    async (status) => {
      const service = new CurveScopeReopeningPreconditionsService();
      vi.spyOn(service, "get").mockRejectedValue({ response: { status, data: { detail: "hidden old source" } } });
      const post = vi.spyOn(service, "post");
      const slot = new CurveExistingWorkReadSlot<{ data: CurveScopeReopeningPreconditionsV1; etag: string }>();
      await slot.load((signal) => service.retrieve("example", target, signal));
      expect(slot.snapshot).toEqual({ status: "UNAVAILABLE", data: null, code: "UNAVAILABLE" });
      expect(JSON.stringify(slot.snapshot)).not.toContain("hidden old source");
      expect(post).not.toHaveBeenCalled();
    }
  );
  it("snapshots the requested target and rejects a late read after cancellation", async () => {
    const service = new CurveScopeReopeningPreconditionsService();
    let resolve!: (value: AxiosResponse) => void;
    vi.spyOn(service, "get").mockImplementation(
      () =>
        new Promise((yes) => {
          resolve = yes;
        })
    );
    const mutable = { ...target };
    const request = service.retrieve("example", mutable);
    mutable.initiativeId = otherId;
    resolve(response(fixture()));
    await expect(request).resolves.toEqual({ data: fixture(), etag: '"7"' });
    const controller = new AbortController();
    const cancelled = service.retrieve("example", target, controller.signal);
    controller.abort();
    resolve(response(fixture()));
    await expect(cancelled).rejects.toMatchObject({ code: "CANCELLED" });
  });
});
