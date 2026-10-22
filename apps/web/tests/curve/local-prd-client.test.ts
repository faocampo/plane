// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import { createHash, webcrypto } from "node:crypto";
import type { AxiosResponse } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  CurveLocalPrdService,
  decodeCurveLocalPrdSource,
} from "../../../../packages/services/src/curve/local-prd.service";
const id = (n: number) => `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const scope = { workspaceId: id(1), productId: id(2), initiativeId: id(3) };
const root = `/api/v1/workspaces/example/curve/initiatives/${scope.initiativeId}/local-prd/v1/sources/`;
const bytes = Uint8Array.from(new TextEncoder().encode("A synthetic PRD"));
const hash = (value: string | Uint8Array) => "sha256:" + createHash("sha256").update(value).digest("hex");
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object")
    return `{${Object.keys(value)
      // oxlint-disable-next-line unicorn/no-array-sort -- Sort a fresh key array under the ES2022 test target.
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical((value as Record<string, unknown>)[key])}`)
      .join(",")}}`;
  return JSON.stringify(value);
}
function source() {
  const data = {
    schema_version: "curve.local-prd-source/v1-candidate",
    source_kind: "LOCAL_UPLOAD",
    id: id(4),
    workspace_id: scope.workspaceId,
    initiative_id: scope.initiativeId,
    version: 1,
    predecessor_id: null,
    uploaded_by: id(5),
    uploaded_at: "2026-10-21T12:00:00Z",
    original: { object_id: id(6), digest: hash(bytes), size_bytes: bytes.length, media_type: "text/plain" },
    snapshot: { object_id: id(7), digest: hash("snapshot"), size_bytes: 100, media_type: "application/json" },
    normalization_schema_version: "curve.local-upload.normalized/v1-candidate",
  };
  return { ...data, digest: hash(canonical(data)) };
}
const response = (data: unknown, status = 200, headers: Record<string, string> = {}) =>
  ({ data, status, headers }) as AxiosResponse;
const options = { expectedVersion: 2, idempotencyKey: "synthetic-upload-1" };
const file = () => new File([bytes], "prd.txt", { type: "text/plain" });
function setup() {
  const service = new CurveLocalPrdService();
  const get = vi.spyOn(service, "get").mockResolvedValue(response({ csrf_token: "synthetic-csrf" }));
  const post = vi
    .spyOn(service, "post")
    .mockResolvedValue(
      response(source(), 201, { etag: '"2"', location: `${root}${id(4)}/`, "idempotency-replayed": "false" })
    );
  return { service, get, post };
}
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
describe("local document browser client", () => {
  it("checks source scope and canonical fingerprint", async () => {
    expect((await decodeCurveLocalPrdSource(source(), scope)).id).toBe(id(4));
    await expect(decodeCurveLocalPrdSource({ ...source(), workspace_id: id(9) }, scope)).rejects.toThrow();
    await expect(decodeCurveLocalPrdSource({ ...source(), uploaded_by: id(9) }, scope)).rejects.toThrow();
    await expect(decodeCurveLocalPrdSource({ ...source(), extra: "hidden" }, scope)).rejects.toThrow();
  });
  it("reads an authorized empty state", async () => {
    const { service, get } = setup();
    get.mockResolvedValue(
      response(
        {
          schema_version: "curve.local-prd-current/v1-candidate",
          source: null,
          initiative_version: 2,
          upload_available: true,
        },
        200,
        { etag: '"2"' }
      )
    );
    expect((await service.retrieveCurrent("example", scope)).source).toBeNull();
  });
  it("sends raw bytes with CSRF and both version preconditions", async () => {
    const { service, post } = setup();
    const upload = file();
    const result = await service.upload("example", scope, upload, 0, options);
    expect(result.data.version).toBe(1);
    expect(post).toHaveBeenCalledWith(
      root,
      upload,
      expect.objectContaining({
        headers: expect.objectContaining({
          "Content-Type": "text/plain",
          "X-CSRFTOKEN": "synthetic-csrf",
          "If-Match": '"2"',
          "X-Curve-Source-Version": "0",
          "Idempotency-Key": options.idempotencyKey,
        }),
      })
    );
  });
  it.each(["draft.docx", "draft.exe", "draft"])("rejects unsupported %s before network", async (name) => {
    const { service, get, post } = setup();
    await expect(service.upload("example", scope, new File([bytes], name), 0, options)).rejects.toThrow();
    expect(get).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
  });
  it("rejects an oversized file before network", async () => {
    const { service, post } = setup();
    await expect(
      service.upload("example", scope, new File([new Uint8Array(10 * 1024 * 1024 + 1)], "prd.pdf"), 0, options)
    ).rejects.toThrow();
    expect(post).not.toHaveBeenCalled();
  });
  it("retains uncertainty on network loss without retry", async () => {
    const { service, post } = setup();
    post.mockRejectedValue(new Error("offline"));
    await expect(service.upload("example", scope, file(), 0, options)).rejects.toMatchObject({
      code: "MUTATION_OUTCOME_UNKNOWN",
    });
    expect(post).toHaveBeenCalledTimes(1);
  });
  it("retains uncertainty when a committed response has the wrong location", async () => {
    const { service, post } = setup();
    post.mockResolvedValue(
      response(source(), 201, { etag: '"2"', location: "/wrong/", "idempotency-replayed": "false" })
    );
    await expect(service.upload("example", scope, file(), 0, options)).rejects.toMatchObject({
      code: "MUTATION_OUTCOME_UNKNOWN",
    });
  });
  it("recognizes an exact explicit retry", async () => {
    const { service, post } = setup();
    post.mockResolvedValue(
      response(source(), 200, { etag: '"2"', location: `${root}${id(4)}/`, "idempotency-replayed": "true" })
    );
    expect((await service.upload("example", scope, file(), 0, options)).replayed).toBe(true);
  });
  it("validates protected bytes before exposing a plain-text blob", async () => {
    const { service, get } = setup();
    get.mockResolvedValue(response(bytes.buffer));
    const record = await decodeCurveLocalPrdSource(source(), scope);
    expect((await service.retrieveContent("example", scope, record)).type).toBe("text/plain;charset=utf-8");
    get.mockResolvedValue(response(new Uint8Array(bytes.length).buffer));
    await expect(service.retrieveContent("example", scope, record)).rejects.toThrow();
  });
  it("cancels before sending a mutation", async () => {
    const { service, post } = setup();
    const controller = new AbortController();
    controller.abort();
    await expect(
      service.upload("example", scope, file(), 0, { ...options, signal: controller.signal })
    ).rejects.toMatchObject({ code: "CANCELLED" });
    expect(post).not.toHaveBeenCalled();
  });
});

function subject() {
  const data = {
    schema_version: "curve.local-prd-submission/v1-candidate",
    id: id(10),
    workspace_id: scope.workspaceId,
    initiative_id: scope.initiativeId,
    initiative_version: 2,
    source_id: id(4),
    source_version: 1,
    source_digest: source().digest,
    content_digest: source().snapshot.digest,
    scope_revision_id: id(11),
    scope_revision: 1,
    membership_digest: hash("members"),
    reviewers: [
      { gate_type: "PLAN_APPROVAL", gate_assignment_id: id(12), approver_user_id: id(13) },
      { gate_type: "PRD_APPROVAL", gate_assignment_id: id(14), approver_user_id: id(5) },
    ],
    risk_tier: "STANDARD",
    submitted_by: id(5),
    submitted_at: "2026-10-21T12:01:00Z",
  };
  return { ...data, digest: hash(canonical(data)) };
}
const reviewRoot = root.replace(/sources\/$/, "review/");
describe("local Product review client", () => {
  it("reads a current submission and rejects forged metadata", async () => {
    const { service, get } = setup();
    const data = {
      schema_version: "curve.local-prd-review-current/v1-candidate",
      initiative_version: 3,
      initiative_state: "PRD_REVIEW",
      source: source(),
      submission: subject(),
      decision: null,
      submission_is_current: true,
      available_actions: ["APPROVE", "REQUEST_CHANGES"],
    };
    get.mockResolvedValue(response(data, 200, { etag: '"3"' }));
    expect((await service.retrieveReview("example", scope)).available_actions).toEqual(["APPROVE", "REQUEST_CHANGES"]);
    get.mockResolvedValue(response({ ...data, submission: { ...subject(), source_id: id(99) } }, 200, { etag: '"3"' }));
    await expect(service.retrieveReview("example", scope)).rejects.toThrow();
  });
  it("submits an exact source and accepts a retained historical replay", async () => {
    const { service, post } = setup();
    const record = await decodeCurveLocalPrdSource(source(), scope);
    post.mockResolvedValue(
      response(subject(), 201, {
        etag: '"3"',
        location: `${reviewRoot}submissions/${id(10)}/`,
        "idempotency-replayed": "false",
      })
    );
    expect((await service.review("example", scope, record, "SUBMIT", null, null, options)).initiativeVersion).toBe(3);
    expect(post).toHaveBeenCalledWith(
      `${reviewRoot}commands/`,
      { action: "SUBMIT", source_id: record.id, source_digest: record.digest },
      expect.objectContaining({
        headers: expect.objectContaining({ "If-Match": '"2"', "X-CSRFTOKEN": "synthetic-csrf" }),
      })
    );
    post.mockResolvedValue(
      response(subject(), 200, {
        etag: '"4"',
        location: `${reviewRoot}submissions/${id(10)}/`,
        "idempotency-replayed": "true",
      })
    );
    expect((await service.review("example", scope, record, "SUBMIT", null, null, options)).replayed).toBe(true);
  });
  it("rejects an unverified success as an uncertain mutation", async () => {
    const { service, post } = setup();
    post.mockResolvedValue(
      response(subject(), 201, {
        etag: '"2"',
        location: `${reviewRoot}submissions/${id(10)}/`,
        "idempotency-replayed": "false",
      })
    );
    await expect(
      service.review("example", scope, await decodeCurveLocalPrdSource(source(), scope), "SUBMIT", null, null, options)
    ).rejects.toMatchObject({ code: "MUTATION_OUTCOME_UNKNOWN" });
  });
  it("never retries an interrupted command automatically", async () => {
    const { service, post } = setup();
    post.mockRejectedValue(new Error("offline"));
    await expect(
      service.review("example", scope, await decodeCurveLocalPrdSource(source(), scope), "SUBMIT", null, null, options)
    ).rejects.toMatchObject({ code: "MUTATION_OUTCOME_UNKNOWN" });
    expect(post).toHaveBeenCalledTimes(1);
  });
  it("checks decision identity and private feedback bytes", async () => {
    const { service, get, post } = setup();
    const { decodeLocalSubmission, decodeLocalDecision } =
      await import("../../../../packages/services/src/curve/local-prd-review.validation");
    const submission = await decodeLocalSubmission(subject(), scope);
    const note = "<script>Clarify the outcome.</script>";
    const data = {
      schema_version: "curve.local-prd-decision/v1-candidate",
      id: id(15),
      workspace_id: scope.workspaceId,
      initiative_id: scope.initiativeId,
      initiative_version: 3,
      submission_id: submission.id,
      submission_digest: submission.digest,
      source_id: submission.source_id,
      source_digest: submission.source_digest,
      gate_assignment_id: id(14),
      state: "CHANGES_REQUESTED",
      decided_by: id(5),
      decided_at: "2026-10-21T12:02:00Z",
      feedback: {
        object_id: id(16),
        digest: hash(note),
        size_bytes: new TextEncoder().encode(note).length,
        media_type: "text/plain",
      },
    };
    const decision = await decodeLocalDecision({ ...data, digest: hash(canonical(data)) }, scope, submission);
    get.mockResolvedValue(response(Uint8Array.from(new TextEncoder().encode(note)).buffer));
    expect(await service.retrieveFeedback("example", scope, decision, submission)).toBe(note);
    get.mockResolvedValue(response(new Uint8Array(note.length).buffer));
    await expect(service.retrieveFeedback("example", scope, decision, submission)).rejects.toThrow();
    await expect(
      service.review(
        "example",
        scope,
        await decodeCurveLocalPrdSource(source(), scope),
        "REQUEST_CHANGES",
        submission,
        "   ",
        { ...options, expectedVersion: 3 }
      )
    ).rejects.toThrow();
    expect(post).not.toHaveBeenCalled();
  });
});

async function approvedCurrent() {
  const { decodeLocalSubmission, decodeLocalDecision } =
    await import("../../../../packages/services/src/curve/local-prd-review.validation");
  const submission = await decodeLocalSubmission(subject(), scope);
  const value = {
    schema_version: "curve.local-prd-decision/v1-candidate",
    id: id(15),
    workspace_id: scope.workspaceId,
    initiative_id: scope.initiativeId,
    initiative_version: 3,
    submission_id: submission.id,
    submission_digest: submission.digest,
    source_id: submission.source_id,
    source_digest: submission.source_digest,
    gate_assignment_id: id(14),
    state: "APPROVED",
    decided_by: id(5),
    decided_at: "2026-10-21T12:02:00Z",
    feedback: null,
  };
  const decision = await decodeLocalDecision({ ...value, digest: hash(canonical(value)) }, scope, submission);
  return {
    schema_version: "curve.local-prd-review-current/v1-candidate" as const,
    initiative_version: 4,
    initiative_state: "PLANNING",
    source: await decodeCurveLocalPrdSource(source(), scope),
    submission,
    decision,
    submission_is_current: true,
    available_actions: [],
  };
}
async function reopeningRecord() {
  const review = await approvedCurrent();
  const value = {
    schema_version: "curve.local-prd-reopening/v1-candidate",
    id: id(17),
    workspace_id: scope.workspaceId,
    initiative_id: scope.initiativeId,
    initiative_version: 4,
    source_id: review.source.id,
    source_digest: review.source.digest,
    submission_id: review.submission.id,
    submission_digest: review.submission.digest,
    decision_id: review.decision.id,
    decision_digest: review.decision.digest,
    reopened_by: id(5),
    reopened_at: "2026-10-21T12:03:00Z",
  };
  return { ...value, digest: hash(canonical(value)) };
}
describe("approved PRD reopening client", () => {
  it("checks the exact approved subject and immutable reopening fingerprint", async () => {
    const { decodeLocalPrdReopening } =
      await import("../../../../packages/services/src/curve/local-prd-reopening.validation");
    const review = await approvedCurrent();
    const record = await reopeningRecord();
    expect((await decodeLocalPrdReopening(record, scope, review.submission, review.decision)).id).toBe(id(17));
    const { digest: _digest, ...body } = record;
    for (const change of [
      { source_id: id(99) },
      { decision_digest: hash("wrong") },
      { reopened_at: "2026-10-21T12:01:00Z" },
      { extra: true },
    ]) {
      const wrong = { ...body, ...change };
      // eslint-disable-next-line no-await-in-loop -- Keep each mutated identity assertion independent and ordered.
      await expect(
        decodeLocalPrdReopening({ ...wrong, digest: hash(canonical(wrong)) }, scope, review.submission, review.decision)
      ).rejects.toThrow();
    }
  });
  it("reads availability and a pending replacement with exact version checks", async () => {
    const { service, get } = setup();
    const review = await approvedCurrent();
    const current = {
      schema_version: "curve.local-prd-reopening-current/v1-candidate",
      initiative_version: 4,
      initiative_state: "PLANNING",
      can_reopen: true,
      reopening: null,
    };
    get.mockResolvedValue(response(current, 200, { etag: '"4"' }));
    expect((await service.retrieveReopening("example", scope, review)).can_reopen).toBe(true);
    const pending = { ...review, initiative_version: 5, initiative_state: "ALIGNING", submission_is_current: false };
    const updated = {
      ...current,
      initiative_version: 5,
      initiative_state: "ALIGNING",
      can_reopen: false,
      reopening: await reopeningRecord(),
    };
    get.mockResolvedValue(response(updated, 200, { etag: '"5"' }));
    expect((await service.retrieveReopening("example", scope, pending)).reopening?.id).toBe(id(17));
    get.mockResolvedValue(response({ ...updated, can_reopen: true }, 200, { etag: '"5"' }));
    await expect(service.retrieveReopening("example", scope, pending)).rejects.toThrow();
    get.mockResolvedValue(response(current, 200, { etag: '"5"' }));
    await expect(service.retrieveReopening("example", scope, review)).rejects.toThrow();
  });
  it("sends the exact source, submission and approval and validates the new state version", async () => {
    const { service, post } = setup();
    const review = await approvedCurrent();
    const record = await reopeningRecord();
    const base = root.replace(/sources\/$/, "");
    post.mockResolvedValue(
      response(record, 201, {
        etag: '"5"',
        location: `${base}reopenings/${record.id}/`,
        "idempotency-replayed": "false",
      })
    );
    const result = await service.reopen("example", scope, review, { ...options, expectedVersion: 4 });
    expect(result.initiativeVersion).toBe(5);
    expect(post).toHaveBeenCalledWith(
      `${base}reopening/`,
      {
        action: "REOPEN",
        source_id: review.source.id,
        source_digest: review.source.digest,
        submission_id: review.submission.id,
        submission_digest: review.submission.digest,
        decision_id: review.decision.id,
        decision_digest: review.decision.digest,
      },
      expect.objectContaining({
        headers: expect.objectContaining({ "If-Match": '"4"', "Idempotency-Key": options.idempotencyKey }),
      })
    );
    post.mockResolvedValue(
      response(record, 200, {
        etag: '"8"',
        location: `${base}reopenings/${record.id}/`,
        "idempotency-replayed": "true",
      })
    );
    expect((await service.reopen("example", scope, review, { ...options, expectedVersion: 4 })).replayed).toBe(true);
  });
  it("treats an unverifiable committed response as an unknown outcome", async () => {
    const { service, post } = setup();
    const review = await approvedCurrent();
    const record = await reopeningRecord();
    const base = root.replace(/sources\/$/, "");
    post.mockResolvedValue(
      response({ ...record, decision_id: id(99) }, 201, {
        etag: '"5"',
        location: `${base}reopenings/${record.id}/`,
        "idempotency-replayed": "false",
      })
    );
    await expect(service.reopen("example", scope, review, { ...options, expectedVersion: 4 })).rejects.toMatchObject({
      code: "MUTATION_OUTCOME_UNKNOWN",
    });
  });
});

describe("new Initiative Product submission", () => {
  async function decode(overrides: Record<string, unknown> = {}) {
    const { decodeLocalSubmission } =
      await import("../../../../packages/services/src/curve/local-prd-review.validation");
    const data: Record<string, unknown> = { ...subject() };
    for (const key of ["digest", "scope_revision_id", "scope_revision", "membership_digest"]) delete data[key];
    Object.assign(
      data,
      {
        schema_version: "curve.local-prd-submission/v2-candidate",
        product_id: scope.productId,
        product_version: 1,
        business_intent: "STRATEGIC",
      },
      overrides
    );
    return decodeLocalSubmission({ ...data, digest: hash(canonical(data)) }, scope);
  }
  it("accepts a Product-pinned submission without existing work", async () => {
    expect(await decode()).toMatchObject({ product_id: scope.productId, product_version: 1 });
  });
  it.each([
    { product_id: id(99) },
    { product_version: 0 },
    { business_intent: "UNKNOWN" },
    { scope_revision_id: id(11) },
    { schema_version: null },
  ])("rejects mismatched or mixed context %j", async (overrides) => {
    await expect(decode(overrides)).rejects.toThrow();
  });
});
