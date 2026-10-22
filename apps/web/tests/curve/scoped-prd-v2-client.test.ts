// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import { createHash, webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AxiosResponse } from "axios";
import type {
  CurveScopedPrdApproveV2,
  CurveScopedPrdObserveV2,
  CurveScopedPrdSubmitV2,
  CurveScopedPrdReturnV2,
} from "../../../../packages/types/src/curve-scoped-prd-v2";
import { CurveScopedPrdV2Service } from "../../../../packages/services/src/curve/scoped-prd-v2.service";
import { CurveScopedPrdV1Service } from "../../../../packages/services/src/curve/scoped-prd-v1.service";
import {
  decodeCurveScopedPrdObservationV2,
  decodeCurveScopedPrdSubjectV2,
} from "../../../../packages/services/src/curve/scoped-prd-v2.validation";
import {
  decodeCurveScopedPrdObservationV1,
  decodeCurveScopedPrdSubjectV1,
} from "../../../../packages/services/src/curve/existing-work-validation";
import * as validators from "../../../../packages/services/src/curve/existing-work-contracts/validators.mjs";
import data from "./fixtures/scoped-prd-v2.json";
import legacy from "./fixtures/existing-work-v1.json";

const scope = {
  workspaceId: data.subject.workspace_id,
  productId: data.subject.product_id,
  initiativeId: data.subject.initiative_id,
};
const options = { expectedVersion: data.observation.initiative_version, idempotencyKey: "synthetic-exact-review" };
const root = `/api/v1/workspaces/example/curve/initiatives/${scope.initiativeId}/scoped-prd/v2/`;
const expectation = () => {
  const { proposal_id, scope_revision_id, scope_revision, membership_digest } = data.observe;
  return { proposal_id, scope_revision_id, scope_revision, membership_digest };
};
const subjectExpectation = () => {
  const { checkpoint_id, artifact_version_id, content_digest, provider_version, evidence_snapshot_id } = data.subject;
  return {
    ...expectation(),
    checkpoint_id,
    artifact_version_id,
    content_digest,
    provider_version,
    evidence_snapshot_id,
  };
};
const response = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  ({ data: body, status, headers, statusText: "", config: {} }) as AxiosResponse;
const acceptance = () =>
  response(data.operation, 202, {
    etag: `"${options.expectedVersion}"`,
    location: `/api/v1/workspaces/example/curve/operations/${data.operation.id}/`,
  });
const csrf = (service: CurveScopedPrdV2Service | CurveScopedPrdV1Service) =>
  vi.spyOn(service, "get").mockResolvedValue(response({ csrf_token: "synthetic-csrf" }));
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object")
    return `{${Object.entries(value)
      // oxlint-disable-next-line unicorn/no-array-sort -- Sort a fresh array for ES2022 compatibility.
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`)
      .join(",")}}`;
  return JSON.stringify(value);
}
function repin<T extends { digest: string }>(value: T): T {
  const { digest: _digest, ...metadata } = value;
  return { ...value, digest: "sha256:" + createHash("sha256").update(canonical(metadata)).digest("hex") };
}
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("two-stage Product review client", () => {
  it("accepts exact two-reviewer metadata and the bound current document", async () => {
    expect(await decodeCurveScopedPrdObservationV2(data.observation, scope, expectation())).toEqual(data.observation);
    expect(await decodeCurveScopedPrdSubjectV2(data.subject, scope, subjectExpectation())).toEqual(data.subject);
  });
  it("rejects both directions of cross-edition metadata", async () => {
    await expect(decodeCurveScopedPrdObservationV2(legacy.observation, scope, expectation())).rejects.toMatchObject({
      code: "INVALID",
    });
    await expect(decodeCurveScopedPrdSubjectV2(legacy.subject, scope, subjectExpectation())).rejects.toMatchObject({
      code: "INVALID",
    });
    await expect(decodeCurveScopedPrdObservationV1(data.observation, scope, expectation())).rejects.toMatchObject({
      code: "INVALID",
    });
    await expect(decodeCurveScopedPrdSubjectV1(data.subject, scope, subjectExpectation())).rejects.toMatchObject({
      code: "INVALID",
    });
  });
  it.each(["code", "missing", "duplicate", "order", "primitive"])(
    "rejects invalid reviewer structure: %s",
    async (kind) => {
      const copy = structuredClone(data.observation);
      if (kind === "code") copy.reviewers[0].gate_type = "CODE_READINESS";
      if (kind === "missing") copy.reviewers.pop();
      if (kind === "duplicate") copy.reviewers[1].gate_assignment_id = copy.reviewers[0].gate_assignment_id;
      if (kind === "order") copy.reviewers.reverse();
      const candidate = kind === "primitive" ? { ...copy, reviewers: [null, "PRD_APPROVAL"] } : copy;
      await expect(decodeCurveScopedPrdObservationV2(repin(candidate), scope, expectation())).rejects.toMatchObject({
        code: "INVALID",
      });
    }
  );
  it("rejects document substitution, added fields and metadata tampering", async () => {
    for (const copy of [
      { ...data.subject, content_digest: "sha256:" + "b".repeat(64) },
      { ...data.subject, extra: true },
      { ...data.subject, created_by: "ffffffff-ffff-ffff-ffff-ffffffffffff" },
    ]) {
      // eslint-disable-next-line no-await-in-loop -- Validate cases serially because the shared validator owns transient errors.
      await expect(decodeCurveScopedPrdSubjectV2(copy, scope, subjectExpectation())).rejects.toMatchObject({
        code: "INVALID",
      });
    }
    await expect(
      decodeCurveScopedPrdSubjectV2(
        data.subject,
        { ...scope, productId: "ffffffff-ffff-ffff-ffff-ffffffffffff" },
        subjectExpectation()
      )
    ).rejects.toMatchObject({ code: "INVALID" });
  });
  it("uses only v2 observation/current/exact subject routes", async () => {
    const service = new CurveScopedPrdV2Service();
    const get = vi
      .spyOn(service, "get")
      .mockResolvedValueOnce(response(data.observation))
      .mockResolvedValue(response(data.subject));
    await service.retrieveObservation("example", scope, data.observation.id, expectation());
    await service.retrieveCurrentSubject("example", scope, subjectExpectation());
    await service.retrieveSubject("example", scope, data.subject.id, subjectExpectation());
    expect(get.mock.calls.map((call) => call[0])).toEqual([
      `${root}observations/${data.observation.id}/`,
      `${root}subjects/current/`,
      `${root}subjects/${data.subject.id}/`,
    ]);
  });
  it("captures the exact two-stage observation with fresh CSRF and strong precondition", async () => {
    const service = new CurveScopedPrdV2Service();
    csrf(service);
    const post = vi
      .spyOn(service, "post")
      .mockResolvedValue(response(data.observation, 201, { etag: `"${options.expectedVersion}"` }));
    const result = await service.captureObservation("example", scope, data.observe as CurveScopedPrdObserveV2, options);
    expect(result.data).toEqual(data.observation);
    expect(post).toHaveBeenCalledWith(
      `${root}observations/`,
      data.observe,
      expect.objectContaining({
        headers: expect.objectContaining({
          "If-Match": `"${options.expectedVersion}"`,
          "Idempotency-Key": options.idempotencyKey,
          "X-CSRFTOKEN": "synthetic-csrf",
        }),
      })
    );
  });
  it.each(["submit", "approve", "returnForRevision"] as const)(
    "sends %s through the exact current route",
    async (method) => {
      const service = new CurveScopedPrdV2Service();
      csrf(service);
      const post = vi.spyOn(service, "post").mockResolvedValue(acceptance());
      if (method === "submit") await service.submit("example", scope, data.submit as CurveScopedPrdSubmitV2, options);
      if (method === "approve")
        await service.approve("example", scope, data.approve as CurveScopedPrdApproveV2, options);
      if (method === "returnForRevision")
        await service.returnForRevision("example", scope, data.returnForRevision as CurveScopedPrdReturnV2, options);
      expect(post.mock.calls[0][0]).toBe(
        root + (method === "returnForRevision" ? "return-for-revision" : method) + "/"
      );
      expect(post.mock.calls[0][1]).toEqual(data[method]);
    }
  );
  it("rejects old commands before any transport, and new commands on the old client", async () => {
    const service = new CurveScopedPrdV2Service();
    const get = csrf(service);
    const post = vi.spyOn(service, "post");
    await expect(
      service.approve("example", scope, legacy.approve as unknown as CurveScopedPrdApproveV2, options)
    ).rejects.toMatchObject({ code: "INVALID" });
    expect(get).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
    const old = new CurveScopedPrdV1Service();
    const oldGet = csrf(old);
    await expect(
      old.approve("example", scope, data.approve as unknown as Parameters<typeof old.approve>[2], options)
    ).rejects.toMatchObject({ code: "INVALID" });
    expect(oldGet).not.toHaveBeenCalled();
  });
  it("requires feedback and rejects oversized or malformed text before sending", async () => {
    const service = new CurveScopedPrdV2Service();
    const get = csrf(service);
    for (const rationale of ["", "x".repeat(65537), "\ud800"]) {
      // eslint-disable-next-line no-await-in-loop -- Validate cases serially because the shared validator owns transient errors.
      await expect(
        service.returnForRevision(
          "example",
          scope,
          { ...data.returnForRevision, rationale } as CurveScopedPrdReturnV2,
          options
        )
      ).rejects.toMatchObject({ code: "INVALID" });
    }
    expect(get).not.toHaveBeenCalled();
    expect(validators.validateCurveScopedPrdReturnV2.errors).toBeNull();
  });
  it("treats a successful but mismatched acceptance as an unknown mutation outcome", async () => {
    const service = new CurveScopedPrdV2Service();
    csrf(service);
    vi.spyOn(service, "post").mockResolvedValue(
      response(data.operation, 202, { etag: 'W/"3"', location: "https://example.invalid/elsewhere" })
    );
    await expect(
      service.approve("example", scope, data.approve as CurveScopedPrdApproveV2, options)
    ).rejects.toMatchObject({ code: "MUTATION_OUTCOME_UNKNOWN" });
  });
  it("does not automatically replay an uncertain write or expose its rationale", async () => {
    const service = new CurveScopedPrdV2Service();
    csrf(service);
    const post = vi
      .spyOn(service, "post")
      .mockRejectedValue({ message: data.approve.rationale, config: { data: data.approve } });
    const error = await service
      .approve("example", scope, data.approve as CurveScopedPrdApproveV2, options)
      .catch((failure) => failure);
    expect(error.code).toBe("MUTATION_OUTCOME_UNKNOWN");
    expect(JSON.stringify(error)).not.toContain(data.approve.rationale);
    expect(post).toHaveBeenCalledTimes(1);
  });
});
