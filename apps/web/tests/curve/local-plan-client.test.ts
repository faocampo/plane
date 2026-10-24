// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import { createHash, webcrypto } from "node:crypto";
import type { AxiosResponse } from "axios";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import {
  CurveLocalPlanService,
  decodeLocalPlanApproval,
  decodeLocalPlanRevision,
  decodeLocalPlanSubmission,
  decodeLocalPlanDecision,
} from "../../../../packages/services/src/curve/local-plan.service";
import type {
  LocalPlanApproval,
  LocalPlanReviewCurrent,
} from "../../../../packages/services/src/curve/local-plan.service";
const id = (n: number) => `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const scope = { workspaceId: id(1), productId: id(2), initiativeId: id(3) };
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
const pin = (data: Record<string, unknown>) => {
  const { digest: _, ...metadata } = data;
  return { ...metadata, digest: hash(canonical(metadata)) };
};
const approval = () =>
  ({
    prd_submission: subject(),
    prd_approval: pin({
      schema_version: "curve.local-prd-decision/v1-candidate",
      id: id(20),
      workspace_id: scope.workspaceId,
      initiative_id: scope.initiativeId,
      initiative_version: 3,
      submission_id: subject().id,
      submission_digest: subject().digest,
      source_id: id(4),
      source_digest: source().digest,
      gate_assignment_id: id(14),
      state: "APPROVED",
      decided_by: id(5),
      decided_at: "2026-10-21T12:02:00Z",
      feedback: null,
    }),
  }) as unknown as LocalPlanApproval;
const plan = () =>
  pin({
    schema_version: "curve.local-plan-revision/v1-candidate",
    id: id(21),
    workspace_id: scope.workspaceId,
    initiative_id: scope.initiativeId,
    initiative_version: 4,
    version: 1,
    predecessor_id: null,
    prd_submission_id: subject().id,
    prd_submission_digest: subject().digest,
    prd_decision_id: approval().prd_approval.id,
    prd_decision_digest: approval().prd_approval.digest,
    original: source().original,
    snapshot: source().snapshot,
    normalization_schema_version: "curve.local-upload.normalized/v1-candidate",
    uploaded_by: id(5),
    uploaded_at: "2026-10-21T12:03:00Z",
  });
const submission = () =>
  pin({
    schema_version: "curve.local-plan-submission/v1-candidate",
    id: id(22),
    workspace_id: scope.workspaceId,
    initiative_id: scope.initiativeId,
    initiative_version: 4,
    plan_revision_id: id(21),
    plan_revision_digest: plan().digest,
    plan_version: 1,
    content_digest: source().snapshot.digest,
    prd_submission_id: subject().id,
    prd_submission_digest: subject().digest,
    prd_decision_id: approval().prd_approval.id,
    prd_decision_digest: approval().prd_approval.digest,
    technical_gate_assignment_id: id(12),
    technical_approver_id: id(13),
    submitted_by: id(5),
    submitted_at: "2026-10-21T12:04:00Z",
  });
const decision = () =>
  pin({
    schema_version: "curve.local-plan-decision/v1-candidate",
    id: id(23),
    workspace_id: scope.workspaceId,
    initiative_id: scope.initiativeId,
    initiative_version: 4,
    plan_submission_id: id(22),
    plan_submission_digest: submission().digest,
    plan_revision_id: id(21),
    plan_revision_digest: plan().digest,
    technical_gate_assignment_id: id(12),
    state: "APPROVED",
    decided_by: id(13),
    decided_at: "2026-10-21T12:05:00Z",
    feedback: null,
  });
const root = `/api/v1/workspaces/example/curve/initiatives/${scope.initiativeId}/local-plan/v1/`;
const response = (data: unknown, status = 200, headers: Record<string, string> = {}) =>
  ({ data, status, headers }) as AxiosResponse;
const options = { expectedVersion: 4, idempotencyKey: "synthetic-plan-command" };
const current = () =>
  ({
    ...approval(),
    schema_version: "curve.local-plan-review-current/v1-candidate",
    revision: plan(),
    submission: submission(),
    decision: null,
    initiative_version: 4,
    initiative_state: "PLANNING",
    revision_is_current: true,
    available_actions: ["APPROVE", "REQUEST_CHANGES"],
  }) as unknown as LocalPlanReviewCurrent;
function planFile() {
  const file = new File([bytes], "plan.txt");
  // jsdom does not expose Blob.arrayBuffer; supply the browser method for this fixture.
  Object.defineProperty(file, "arrayBuffer", { value: async () => bytes.buffer });
  return file;
}
function setup() {
  const service = new CurveLocalPlanService();
  const get = vi.spyOn(service, "get").mockResolvedValue(response({ csrf_token: "synthetic-csrf" }));
  const post = vi.spyOn(service, "post");
  return { service, get, post };
}
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("validates the exact Product approval, plan and Technical decision chain", async () => {
  const accepted = await decodeLocalPlanApproval(approval(), scope);
  const revision = await decodeLocalPlanRevision(plan(), scope, accepted);
  const planSubject = await decodeLocalPlanSubmission(submission(), scope, revision, accepted);
  expect((await decodeLocalPlanDecision(decision(), scope, revision, planSubject, accepted)).state).toBe("APPROVED");
  await expect(
    decodeLocalPlanRevision(pin({ ...plan(), prd_decision_digest: hash("wrong") }), scope, accepted)
  ).rejects.toThrow();
  await expect(
    decodeLocalPlanDecision(pin({ ...decision(), decided_by: id(99) }), scope, revision, planSubject, accepted)
  ).rejects.toThrow();
});
it("sends exact Product pins on upload", async () => {
  const { service, post } = setup();
  post.mockResolvedValue(
    response(plan(), 201, { etag: '"4"', location: `${root}revisions/${id(21)}/`, "idempotency-replayed": "false" })
  );
  expect((await service.upload("example", scope, planFile(), 0, approval(), options)).data.id).toBe(id(21));
  expect(post).toHaveBeenCalledWith(
    `${root}revisions/`,
    expect.any(File),
    expect.objectContaining({
      headers: expect.objectContaining({
        "X-Curve-Plan-Version": "0",
        "X-Curve-Prd-Submission-Id": id(10),
        "X-Curve-Prd-Decision-Digest": approval().prd_approval.digest,
      }),
    })
  );
});
it("reads current Technical actions and rejects a mismatched submission", async () => {
  const { service, get } = setup();
  get.mockResolvedValue(response(current(), 200, { etag: '"4"' }));
  expect((await service.retrieveReview("example", scope)).available_actions).toEqual(["APPROVE", "REQUEST_CHANGES"]);
  get.mockResolvedValue(
    response({ ...current(), submission: pin({ ...submission(), plan_revision_digest: hash("wrong") }) }, 200, {
      etag: '"4"',
    })
  );
  await expect(service.retrieveReview("example", scope)).rejects.toThrow();
});
it("approves and accepts exact retained retries without advancing Initiative version", async () => {
  const { service, post } = setup();
  post.mockResolvedValue(
    response(decision(), 201, {
      etag: '"4"',
      location: `${root}review/decisions/${id(23)}/`,
      "idempotency-replayed": "false",
    })
  );
  expect((await service.review("example", scope, current(), "APPROVE", null, options)).initiativeVersion).toBe(4);
  post.mockResolvedValue(
    response(decision(), 200, {
      etag: '"4"',
      location: `${root}review/decisions/${id(23)}/`,
      "idempotency-replayed": "true",
    })
  );
  expect((await service.review("example", scope, current(), "APPROVE", null, options)).replayed).toBe(true);
});
it("keeps unverified mutation responses uncertain", async () => {
  const { service, post } = setup();
  post.mockResolvedValue(
    response(decision(), 201, { etag: '"4"', location: "wrong", "idempotency-replayed": "false" })
  );
  await expect(service.review("example", scope, current(), "APPROVE", null, options)).rejects.toMatchObject({
    code: "MUTATION_OUTCOME_UNKNOWN",
  });
  expect(post).toHaveBeenCalledTimes(1);
});
it("checks document bytes before preview", async () => {
  const { service, get } = setup();
  const revision = await decodeLocalPlanRevision(plan(), scope, approval());
  get.mockResolvedValue(response(bytes.buffer));
  expect((await service.retrieveContent("example", scope, revision, approval())).size).toBe(bytes.length);
  expect(get.mock.calls.at(-1)?.[1]).toEqual(expect.objectContaining({ timeout: 60_000, responseType: "arraybuffer" }));
  get.mockResolvedValue(response(new Uint8Array(bytes.length).buffer));
  await expect(service.retrieveContent("example", scope, revision, approval())).rejects.toThrow();
});

it("keeps a different upload content fingerprint uncertain", async () => {
  const { service, post } = setup();
  post.mockResolvedValue(
    response(pin({ ...plan(), original: { ...source().original, digest: hash("different") } }), 201, {
      etag: '"4"',
      location: `${root}revisions/${id(21)}/`,
      "idempotency-replayed": "false",
    })
  );
  await expect(service.upload("example", scope, planFile(), 0, approval(), options)).rejects.toMatchObject({
    code: "MUTATION_OUTCOME_UNKNOWN",
  });
});

function renewedApproval(): LocalPlanApproval {
  const next = pin({
    ...subject(),
    id: id(40),
    initiative_version: 6,
    source_id: id(41),
    source_version: 2,
    source_digest: hash("new source"),
    content_digest: hash("new snapshot"),
    submitted_at: "2026-10-21T12:05:00Z",
  });
  return {
    prd_submission: next,
    prd_approval: pin({
      ...approval().prd_approval,
      id: id(42),
      initiative_version: 7,
      submission_id: id(40),
      submission_digest: next.digest,
      source_id: id(41),
      source_digest: hash("new source"),
      decided_at: "2026-10-21T12:06:00Z",
    }),
  } as unknown as LocalPlanApproval;
}
function historicalSetup() {
  const result = setup();
  const next = renewedApproval();
  const reviewState = {
    ...current(),
    ...next,
    decision: decision(),
    initiative_version: 8,
    revision_is_current: false,
    available_actions: [],
  };
  const documentState = {
    schema_version: "curve.local-plan-current/v1-candidate",
    ...next,
    revision: plan(),
    initiative_version: 8,
    upload_available: true,
  };
  const prdRoot = root.replace(/local-plan\/v1\/$/, "local-prd/v1/review/");
  const read = async (url: string) => {
    if (url === `${root}review/current/`) return response(reviewState, 200, { etag: '"8"' });
    if (url === `${root}revisions/current/`) return response(documentState, 200, { etag: '"8"' });
    if (url === `${prdRoot}submissions/${id(10)}/`) return response(approval().prd_submission, 200, { etag: '"8"' });
    if (url === `${prdRoot}decisions/${id(20)}/`) return response(approval().prd_approval, 200, { etag: '"8"' });
    if (url.endsWith(`/revisions/${id(21)}/content/`)) return response(bytes.buffer);
    return response({ csrf_token: "synthetic-csrf" });
  };
  result.get.mockImplementation(read);
  return { ...result, next, reviewState, documentState, prdRoot, read };
}
it("reads a retained plan with its original approval while keeping the new Product approval current", async () => {
  const { service, next, post } = historicalSetup();
  const document = await service.retrieveCurrent("example", scope);
  expect(document.prd_approval.id).toBe(next.prd_approval.id);
  expect(document.revision_approval?.prd_approval.id).toBe(approval().prd_approval.id);
  expect(document.revision?.version).toBe(1);
  expect((await service.retrieveContent("example", scope, document.revision!, document.revision_approval!)).size).toBe(
    bytes.length
  );
  const reviewState = await service.retrieveReview("example", scope);
  expect(reviewState.revision_is_current).toBe(false);
  expect(reviewState.decision?.state).toBe("APPROVED");
  expect(reviewState.available_actions).toEqual([]);
  await expect(
    service.review("example", scope, reviewState, "APPROVE", null, { ...options, expectedVersion: 8 })
  ).rejects.toThrow();
  expect(post).not.toHaveBeenCalled();
});
it("uploads the next plan version against the renewed Product approval", async () => {
  const { service, next, post } = historicalSetup();
  const document = await service.retrieveCurrent("example", scope);
  const replacement = pin({
    ...plan(),
    id: id(43),
    version: 2,
    predecessor_id: id(21),
    initiative_version: 8,
    prd_submission_id: next.prd_submission.id,
    prd_submission_digest: next.prd_submission.digest,
    prd_decision_id: next.prd_approval.id,
    prd_decision_digest: next.prd_approval.digest,
    uploaded_at: "2026-10-21T12:07:00Z",
  });
  post.mockResolvedValue(
    response(replacement, 201, {
      etag: '"8"',
      location: `${root}revisions/${id(43)}/`,
      "idempotency-replayed": "false",
    })
  );
  expect(
    (
      await service.upload("example", scope, planFile(), document.revision!.version, document, {
        ...options,
        expectedVersion: 8,
      })
    ).data.version
  ).toBe(2);
  expect(post).toHaveBeenCalledWith(
    `${root}revisions/`,
    expect.any(File),
    expect.objectContaining({
      headers: expect.objectContaining({
        "X-Curve-Plan-Version": "1",
        "X-Curve-Prd-Decision-Id": next.prd_approval.id,
      }),
    })
  );
});
it("rejects changed historical context, inconsistent reads, and false current-plan claims", async () => {
  const { service, get, prdRoot, read, reviewState } = historicalSetup();
  get.mockImplementation(async (url: string) =>
    url === `${prdRoot}decisions/${id(20)}/` ? response(approval().prd_approval, 200, { etag: '"9"' }) : read(url)
  );
  await expect(service.retrieveReview("example", scope)).rejects.toThrow();
  get.mockImplementation(async (url: string) =>
    url === `${prdRoot}decisions/${id(20)}/`
      ? response(pin({ ...approval().prd_approval, id: id(99) }), 200, { etag: '"8"' })
      : read(url)
  );
  await expect(service.retrieveReview("example", scope)).rejects.toThrow();
  get.mockImplementation(async (url: string) =>
    url === `${root}review/current/`
      ? response({ ...reviewState, revision_is_current: true, available_actions: ["APPROVE"] }, 200, { etag: '"8"' })
      : read(url)
  );
  await expect(service.retrieveReview("example", scope)).rejects.toThrow();
});
