/// <reference types="node" />
/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { webcrypto, createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath, URL as NodeURL } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AxiosResponse } from "axios";
// Direct source imports ensure this worktree is exercised even with linked sibling node_modules.
import { CurveProjectAssociationService } from "../../../../packages/services/src/curve/project-association.service";
import { CurveScopeProposalService } from "../../../../packages/services/src/curve/scope-proposal.service";
import { CurveScopedPrdV1Service } from "../../../../packages/services/src/curve/scoped-prd-v1.service";
import {
  CurveExistingWorkError,
  decodeCurveProjectAssociation,
  decodeCurveScopeProposal,
  decodeCurveScopedPrdObservationV1,
  decodeCurveScopedPrdSubjectV1,
} from "../../../../packages/services/src/curve/existing-work-validation";
import { CurveExistingWorkReadSlot } from "../../../../packages/services/src/curve/existing-work-read-state";
import * as validators from "../../../../packages/services/src/curve/existing-work-contracts/validators.mjs";
import type {
  CurveProjectAssociation,
  CurveProjectAssociationCreate,
  CurveProjectAssociationEnd,
  CurveScopeProposalReplace,
  CurveScopeProposalRevision,
  CurveScopedPrdObserveV1,
  CurveScopedPrdObservationV1,
  CurveScopedPrdSubmitV1,
  CurveScopedPrdSubjectV1,
  CurveScopedPrdApproveV1,
  CurveScopedPrdReturnV1,
} from "../../../../packages/types/src/curve-existing-work";
import fixtureData from "./fixtures/existing-work-v1.json";
import unicodeFixture from "./fixtures/existing-work-utf8.json";

const fixture = () =>
  structuredClone(fixtureData) as {
    association: CurveProjectAssociation;
    associationCreate: CurveProjectAssociationCreate;
    associationEnd: CurveProjectAssociationEnd;
    revision: CurveScopeProposalRevision;
    replace: CurveScopeProposalReplace;
    observe: CurveScopedPrdObserveV1;
    observation: CurveScopedPrdObservationV1;
    submit: CurveScopedPrdSubmitV1;
    subject: CurveScopedPrdSubjectV1;
    approve: CurveScopedPrdApproveV1;
    returnForRevision: CurveScopedPrdReturnV1;
    operation: typeof fixtureData.operation;
  };
const productScope = {
  workspaceId: fixtureData.association.workspace_id,
  productId: fixtureData.association.product_id,
};
const scope = { ...productScope, initiativeId: fixtureData.revision.initiative_id };
const otherId = "ffffffff-ffff-ffff-ffff-ffffffffffff";
const options = { expectedVersion: 3, idempotencyKey: "exact-command-key" };
function scopeExpectation() {
  const { proposal_id, scope_revision_id, scope_revision, membership_digest } = fixture().observe;
  return { proposal_id, scope_revision_id, scope_revision, membership_digest };
}
function subjectExpectation() {
  const { checkpoint_id, artifact_version_id, content_digest, provider_version, evidence_snapshot_id } =
    fixture().subject;
  return {
    ...scopeExpectation(),
    checkpoint_id,
    artifact_version_id,
    content_digest,
    provider_version,
    evidence_snapshot_id,
  };
}
function response(data: unknown, status = 200, headers: Record<string, string> = {}): AxiosResponse {
  return { data, status, headers, statusText: "", config: {} } as AxiosResponse;
}
function acceptance() {
  return response(fixture().operation, 202, {
    etag: '"3"',
    location: `/api/v1/workspaces/example/curve/operations/${fixture().operation.id}/`,
  });
}
function mockCSRF(service: CurveProjectAssociationService | CurveScopeProposalService | CurveScopedPrdV1Service) {
  return vi.spyOn(service, "get").mockResolvedValue(response({ csrf_token: "synthetic-csrf" }));
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  vi.stubGlobal("crypto", webcrypto);
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("existing-work closed contracts", () => {
  it("mirrors every canonical backend schema byte and verifies deterministic static generation", () => {
    const repository = fileURLToPath(new NodeURL("../../../../", import.meta.url));
    const directory = new NodeURL("../../../../packages/services/src/curve/existing-work-contracts/", import.meta.url);
    const manifest = JSON.parse(readFileSync(new NodeURL("manifest.json", directory), "utf8")) as Array<{
      name: string;
      source: string;
      sha256: string;
    }>;
    for (const entry of manifest) {
      const bytes = readFileSync(new NodeURL(`${entry.name}.schema.json`, directory));
      expect(bytes.equals(readFileSync(`${repository}/${entry.source}`))).toBe(true);
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(entry.sha256);
    }
    execFileSync(process.execPath, [
      `${repository}/packages/services/generate-existing-work-validators.mjs`,
      "--check",
    ]);
    const generated = readFileSync(new NodeURL("validators.mjs", directory), "utf8");
    expect(generated).not.toMatch(/new Function|eval\(|require\(/);
  });
  it("accepts the independent synthetic wire fixture for each mirrored request and response", () => {
    const f = fixture();
    const cases = [
      [validators.validateCurveProjectAssociation, f.association],
      [validators.validateCurveProjectAssociationCreate, f.associationCreate],
      [validators.validateCurveProjectAssociationEnd, f.associationEnd],
      [validators.validateCurveScopeProposalReplace, f.replace],
      [validators.validateCurveScopeProposalRevision, f.revision],
      [validators.validateCurveScopedPrdObserveV1, f.observe],
      [validators.validateCurveScopedPrdObservationV1, f.observation],
      [validators.validateCurveScopedPrdSubjectV1, f.subject],
      [validators.validateCurveScopedPrdSubmitV1, f.submit],
      [validators.validateCurveScopedPrdApproveV1, f.approve],
      [validators.validateCurveScopedPrdReturnV1, f.returnForRevision],
    ] as const;
    for (const [validate, input] of cases) expect(validate(input)).toBe(true);
  });
  it("verifies canonical metadata digests, returns detached objects and rejects source body injection", async () => {
    const f = fixture();
    const revision = await decodeCurveScopeProposal(f.revision, scope);
    const observation = await decodeCurveScopedPrdObservationV1(f.observation, scope, scopeExpectation());
    const subject = await decodeCurveScopedPrdSubjectV1(f.subject, scope, subjectExpectation());
    expect(revision).toEqual(f.revision);
    expect(observation).toEqual(f.observation);
    expect(subject).toEqual(f.subject);
    revision.items[0]!.purpose = "CONTEXT_EVIDENCE";
    expect(f.revision.items[0]!.purpose).toBe("PROPOSED_DELIVERY");
    await expect(
      decodeCurveScopedPrdObservationV1(
        { ...f.observation, members: [{ ...f.observation.members[0], name: "private title" }] },
        scope,
        scopeExpectation()
      )
    ).rejects.toBeInstanceOf(CurveExistingWorkError);
    await expect(
      decodeCurveScopedPrdSubjectV1({ ...f.subject, created_by: otherId }, scope, subjectExpectation())
    ).rejects.toBeInstanceOf(CurveExistingWorkError);
    await expect(
      decodeCurveScopeProposal({ ...f.revision, membership_digest: `sha256:${"0".repeat(64)}` }, scope)
    ).rejects.toBeInstanceOf(CurveExistingWorkError);
  });
  it("matches independently Python-computed canonical UTF-8 digests for accented, astral and CJK strings", async () => {
    await expect(decodeCurveScopeProposal(unicodeFixture.revision, scope)).resolves.toEqual(unicodeFixture.revision);
    await expect(
      decodeCurveScopedPrdObservationV1(unicodeFixture.observation, scope, {
        ...scopeExpectation(),
        membership_digest: unicodeFixture.revision.membership_digest,
      })
    ).resolves.toEqual(unicodeFixture.observation);
  });
  it("fails closed when Web Crypto is unavailable", async () => {
    vi.stubGlobal("crypto", {});
    await expect(decodeCurveScopeProposal(fixture().revision, scope)).rejects.toBeInstanceOf(CurveExistingWorkError);
  });
  it.each([
    "workspace_id",
    "product_id",
    "initiative_id",
    "scope_revision_id",
    "proposal_id",
    "schema_version",
    "policy_edition",
  ])("rejects the wrong observation %s", async (field) => {
    const f = fixture();
    await expect(
      decodeCurveScopedPrdObservationV1({ ...f.observation, [field]: otherId }, scope, scopeExpectation())
    ).rejects.toBeInstanceOf(CurveExistingWorkError);
  });
  it.each(["checkpoint_id", "artifact_version_id", "evidence_snapshot_id", "content_digest", "provider_version"])(
    "rejects the wrong checkpoint %s",
    async (field) => {
      await expect(
        decodeCurveScopedPrdSubjectV1({ ...fixture().subject, [field]: otherId }, scope, subjectExpectation())
      ).rejects.toBeInstanceOf(CurveExistingWorkError);
    }
  );
  it("fails closed on missing runtime expectation coordinates, repeated reviewers and unsorted/duplicate members", async () => {
    const f = fixture();
    await expect(decodeCurveScopedPrdObservationV1(f.observation, scope, {} as never)).rejects.toBeInstanceOf(
      CurveExistingWorkError
    );
    await expect(decodeCurveScopedPrdSubjectV1(f.subject, scope, {} as never)).rejects.toBeInstanceOf(
      CurveExistingWorkError
    );
    await expect(
      decodeCurveScopedPrdObservationV1(
        {
          ...f.observation,
          reviewers: [f.observation.reviewers[0], f.observation.reviewers[0], f.observation.reviewers[0]],
        },
        scope,
        scopeExpectation()
      )
    ).rejects.toBeInstanceOf(CurveExistingWorkError);
    await expect(
      decodeCurveScopeProposal(
        { ...f.revision, items: [f.revision.items[0], f.revision.items[0]], item_count: 2, delivery_count: 2 },
        scope
      )
    ).rejects.toBeInstanceOf(CurveExistingWorkError);
    await expect(decodeCurveScopeProposal({ ...f.revision, item_count: 0 }, scope)).rejects.toBeInstanceOf(
      CurveExistingWorkError
    );
  });
  it.each([
    null,
    [],
    {},
    { ...fixtureData.association, state: "ENDED" },
    { ...fixtureData.association, version: true },
    { ...fixtureData.association, title: "private" },
    { ...fixtureData.association, schema_version: "2.0" },
  ])("rejects malformed or widened association records %#", (invalid) => {
    expect(() => decodeCurveProjectAssociation(invalid, productScope)).toThrow(CurveExistingWorkError);
  });
});

describe("project-association transport", () => {
  it("creates using Product version and returns the exact association ETag without native writes", async () => {
    const service = new CurveProjectAssociationService();
    mockCSRF(service);
    const f = fixture();
    const post = vi
      .spyOn(service, "post")
      .mockResolvedValue(response(f.association, 201, { etag: `"curve-project-association:${f.association.id}:v1"` }));
    await expect(
      service.create("example/route", productScope, f.associationCreate, { ...options, expectedVersion: 6 })
    ).resolves.toEqual({ data: f.association, etag: `"curve-project-association:${f.association.id}:v1"` });
    expect(post).toHaveBeenCalledWith(
      `/api/v1/workspaces/example%2Froute/curve/products/${productScope.productId}/project-associations/`,
      f.associationCreate,
      expect.objectContaining({
        headers: expect.objectContaining({
          "If-Match": `"curve-product:${productScope.productId}:v6"`,
          "Idempotency-Key": options.idempotencyKey,
          "X-CSRFTOKEN": "synthetic-csrf",
        }),
      })
    );
  });
  it.each(["workspace_id", "product_id", "id"])("rejects wrong %s in a fetched association", async (field) => {
    const service = new CurveProjectAssociationService();
    const f = fixture();
    vi.spyOn(service, "get").mockResolvedValue(
      response({ ...f.association, [field]: otherId }, 200, {
        etag: `"curve-project-association:${f.association.id}:v1"`,
      })
    );
    await expect(service.retrieve("example", productScope, f.association.id)).rejects.toBeInstanceOf(
      CurveExistingWorkError
    );
  });
  it.each([
    undefined,
    '"1"',
    `W/"curve-project-association:${fixtureData.association.id}:v1"`,
    `"curve-product:${fixtureData.association.id}:v1"`,
    `"curve-project-association:${fixtureData.association.id}:v2"`,
  ])("rejects a missing, weak, stale or wrong-family ETag %#", async (etag) => {
    const service = new CurveProjectAssociationService();
    const f = fixture();
    vi.spyOn(service, "get").mockResolvedValue(response(f.association, 200, { etag } as never));
    await expect(service.retrieve("example", productScope, f.association.id)).rejects.toBeInstanceOf(
      CurveExistingWorkError
    );
  });
  it("keeps END unavailable and does not reinterpret a server 503 as success", async () => {
    const service = new CurveProjectAssociationService();
    mockCSRF(service);
    const f = fixture();
    const post = vi
      .spyOn(service, "post")
      .mockRejectedValue({ response: { status: 503, data: { detail: "dependency guard unavailable" } } });
    await expect(
      service.end("example", productScope, f.association.id, f.associationEnd, { ...options, expectedVersion: 1 })
    ).rejects.toMatchObject({ code: "MUTATION_OUTCOME_UNKNOWN", status: 503 });
    expect(post).toHaveBeenCalledTimes(1);
    expect(post.mock.calls[0]?.[2]?.headers).toMatchObject({
      "If-Match": `"curve-project-association:${f.association.id}:v1"`,
    });
  });
});

describe("C1 proposal transport", () => {
  it("posts finite explicit membership, binds the returned revision, and reads only exact routes", async () => {
    const service = new CurveScopeProposalService();
    const get = mockCSRF(service);
    const f = fixture();
    const etag = `"curve-initiative:${scope.initiativeId}:v2"`;
    const post = vi.spyOn(service, "post").mockResolvedValue(response(f.revision, 201, { etag }));
    await expect(service.replace("example", scope, f.replace, { ...options, expectedVersion: 1 })).resolves.toEqual({
      data: f.revision,
      etag,
    });
    expect(post.mock.calls[0]?.[2]?.headers).toMatchObject({
      "If-Match": `"curve-initiative:${scope.initiativeId}:v1"`,
    });
    get.mockResolvedValue(response(f.revision, 200, { etag }));
    await service.retrieveCurrent("example", scope, { version: 1 });
    await service.retrieveRevision("example", scope, f.revision.id);
    expect(get.mock.calls.slice(1).map((call) => call[0])).toEqual([
      `/api/v1/workspaces/example/curve/initiatives/${scope.initiativeId}/scope-proposal/`,
      `/api/v1/workspaces/example/curve/initiatives/${scope.initiativeId}/scope-proposal/revisions/${f.revision.id}/`,
    ]);
  });
  it("rejects a wrong historical revision identity and stale exact version", async () => {
    const service = new CurveScopeProposalService();
    const f = fixture();
    vi.spyOn(service, "get").mockResolvedValue(
      response(f.revision, 200, { etag: `"curve-initiative:${scope.initiativeId}:v2"` })
    );
    await expect(service.retrieveRevision("example", scope, otherId)).rejects.toBeInstanceOf(CurveExistingWorkError);
    await expect(service.retrieveCurrent("example", scope, { version: 2 })).rejects.toBeInstanceOf(
      CurveExistingWorkError
    );
  });
  it("rejects duplicate issue selection across purposes before CSRF or network access", async () => {
    const service = new CurveScopeProposalService();
    const f = fixture();
    const get = mockCSRF(service);
    const post = vi.spyOn(service, "post");
    await expect(
      service.replace(
        "example",
        scope,
        { ...f.replace, items: [f.replace.items[0]!, { ...f.replace.items[0]!, purpose: "CONTEXT_EVIDENCE" }] },
        options
      )
    ).rejects.toBeInstanceOf(CurveExistingWorkError);
    expect(get).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
  });
});

describe("explicit scoped PRD V1 transport", () => {
  it("captures only through an explicit POST with the numeric Initiative version", async () => {
    const service = new CurveScopedPrdV1Service();
    const f = fixture();
    mockCSRF(service);
    const post = vi.spyOn(service, "post").mockResolvedValue(response(f.observation, 201, { etag: '"3"' }));
    await expect(service.captureObservation("example", scope, f.observe, options)).resolves.toEqual({
      data: f.observation,
      etag: '"3"',
    });
    expect(post).toHaveBeenCalledWith(
      `/api/v1/workspaces/example/curve/initiatives/${scope.initiativeId}/scoped-prd/v1/observations/`,
      f.observe,
      expect.objectContaining({ headers: expect.objectContaining({ "If-Match": '"3"' }) })
    );
  });
  it("uses protected observation/current/exact-subject reads with cancellation and no mutation", async () => {
    const service = new CurveScopedPrdV1Service();
    const f = fixture();
    const signal = new AbortController().signal;
    const get = vi
      .spyOn(service, "get")
      .mockResolvedValueOnce(response(f.observation))
      .mockResolvedValueOnce(response(f.subject))
      .mockResolvedValueOnce(response(f.subject));
    const post = vi.spyOn(service, "post");
    await service.retrieveObservation("example", scope, f.observation.id, scopeExpectation(), signal);
    await service.retrieveCurrentSubject("example", scope, subjectExpectation(), signal);
    await service.retrieveSubject("example", scope, f.subject.id, subjectExpectation(), signal);
    expect(get.mock.calls.map((call) => call[0])).toEqual([
      `/api/v1/workspaces/example/curve/initiatives/${scope.initiativeId}/scoped-prd/v1/observations/${f.observation.id}/`,
      `/api/v1/workspaces/example/curve/initiatives/${scope.initiativeId}/scoped-prd/v1/subjects/current/`,
      `/api/v1/workspaces/example/curve/initiatives/${scope.initiativeId}/scoped-prd/v1/subjects/${f.subject.id}/`,
    ]);
    for (const call of get.mock.calls) expect(call[1]).toEqual({ signal, headers: { "Cache-Control": "no-store" } });
    expect(post).not.toHaveBeenCalled();
  });
  it("rejects swapped observation and subject IDs without treating them as absent", async () => {
    const service = new CurveScopedPrdV1Service();
    const f = fixture();
    vi.spyOn(service, "get").mockResolvedValueOnce(response(f.observation)).mockResolvedValueOnce(response(f.subject));
    await expect(service.retrieveObservation("example", scope, otherId, scopeExpectation())).rejects.toBeInstanceOf(
      CurveExistingWorkError
    );
    await expect(service.retrieveSubject("example", scope, otherId, subjectExpectation())).rejects.toBeInstanceOf(
      CurveExistingWorkError
    );
  });
  it("returns only a validated Operation acceptance for submit, approve, and return", async () => {
    const service = new CurveScopedPrdV1Service();
    const f = fixture();
    mockCSRF(service);
    const post = vi.spyOn(service, "post").mockResolvedValue(acceptance());
    await service.submit("example", scope, f.submit, options);
    await service.approve("example", scope, f.approve, options);
    await service.returnForRevision("example", scope, f.returnForRevision, options);
    expect(post.mock.calls.map((call) => call[0])).toEqual(
      ["submit", "approve", "return-for-revision"].map(
        (action) => `/api/v1/workspaces/example/curve/initiatives/${scope.initiativeId}/scoped-prd/v1/${action}/`
      )
    );
    for (const call of post.mock.calls)
      expect(call[2]?.headers).toMatchObject({ "Idempotency-Key": options.idempotencyKey, "If-Match": '"3"' });
  });
  it.each(["schema_version", "policy_edition"])("never fills in a missing edition field: %s", async (field) => {
    const service = new CurveScopedPrdV1Service();
    const f = fixture();
    const get = mockCSRF(service);
    const post = vi.spyOn(service, "post");
    const invalid = { ...f.approve } as Record<string, unknown>;
    delete invalid[field];
    await expect(service.approve("example", scope, invalid as never, options)).rejects.toBeInstanceOf(
      CurveExistingWorkError
    );
    expect(get).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
  });
  it.each([0, -1, true, 1.1, Number.MAX_SAFE_INTEGER + 1, NaN, Infinity, "3"])(
    "rejects invalid numeric command versions before CSRF: %s",
    async (version) => {
      const service = new CurveScopedPrdV1Service();
      const get = mockCSRF(service);
      const post = vi.spyOn(service, "post");
      await expect(
        service.submit("example", scope, fixture().submit, { ...options, expectedVersion: version } as never)
      ).rejects.toBeInstanceOf(CurveExistingWorkError);
      expect(get).not.toHaveBeenCalled();
      expect(post).not.toHaveBeenCalled();
    }
  );
  it.each(["", " ", "x\ny", "x\u007f", "x".repeat(256), "\ud800"])(
    "rejects unsafe or missing idempotency keys before CSRF %#",
    async (key) => {
      const service = new CurveScopedPrdV1Service();
      const get = mockCSRF(service);
      await expect(
        service.submit("example", scope, fixture().submit, { ...options, idempotencyKey: key })
      ).rejects.toBeInstanceOf(CurveExistingWorkError);
      expect(get).not.toHaveBeenCalled();
    }
  );
  it("does not retain protected rationale through Axios errors, validators, state, logs or automatic retries", async () => {
    const service = new CurveScopedPrdV1Service();
    const f = fixture();
    mockCSRF(service);
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    const post = vi.spyOn(service, "post").mockRejectedValue({
      message: f.approve.rationale,
      config: { data: JSON.stringify(f.approve) },
      request: { body: f.approve },
      response: { status: 503, data: { detail: f.approve.rationale }, config: { data: f.approve } },
    });
    const error = await service.approve("example", scope, f.approve, options).catch((caught) => caught);
    expect(error).toMatchObject({ code: "MUTATION_OUTCOME_UNKNOWN", status: 503 });
    // oxlint-disable-next-line unicorn/no-array-sort -- The property-name array is freshly allocated.
    expect(Object.getOwnPropertyNames(error).sort()).toEqual(["code", "message", "name", "stack", "status"]);
    expect(JSON.stringify(error)).not.toContain(f.approve.rationale);
    expect(String(error)).not.toContain(f.approve.rationale);
    expect(JSON.stringify(service)).not.toContain(f.approve.rationale);
    expect(log).not.toHaveBeenCalled();
    expect(post).toHaveBeenCalledTimes(1);
    // A caller's explicit retry sends the same caller-provided key/body. No hidden new key is minted.
    await expect(service.approve("example", scope, f.approve, options)).rejects.toBeInstanceOf(CurveExistingWorkError);
    expect(post).toHaveBeenCalledTimes(2);
    expect(post.mock.calls[0]?.[1]).toEqual(post.mock.calls[1]?.[1]);
    expect(post.mock.calls[0]?.[2]?.headers?.["Idempotency-Key"]).toBe(
      post.mock.calls[1]?.[2]?.headers?.["Idempotency-Key"]
    );
    await expect(
      service.approve("example", scope, { ...f.approve, secret: f.approve.rationale } as never, options)
    ).rejects.toBeInstanceOf(CurveExistingWorkError);
    expect(validators.validateCurveScopedPrdApproveV1.errors).toBeNull();
  });
  it.each(["workspace", "edition", "extra", "status", "version", "etag", "location", "http-status"])(
    "rejects a malformed acceptance %s",
    async (kind) => {
      const service = new CurveScopedPrdV1Service();
      mockCSRF(service);
      const returned = acceptance();
      if (kind === "workspace") returned.data.workspace_id = otherId;
      if (kind === "edition") returned.data.schema_version = "2.0";
      if (kind === "extra") returned.data.rationale = "private";
      if (kind === "status") returned.data.status = "APPROVED";
      if (kind === "version") returned.data.version = true;
      if (kind === "etag") returned.headers.etag = `"curve-initiative:${scope.initiativeId}:v3"`;
      if (kind === "location") returned.headers.location = `https://other.invalid/operations/${otherId}/`;
      if (kind === "http-status") returned.status = 200;
      vi.spyOn(service, "post").mockResolvedValue(returned);
      await expect(service.submit("example", scope, fixture().submit, options)).rejects.toBeInstanceOf(
        CurveExistingWorkError
      );
    }
  );
  it("snapshots exact input and scope before awaiting CSRF and refuses a cancelled mutation", async () => {
    const service = new CurveScopedPrdV1Service();
    const csrf = deferred<AxiosResponse>();
    vi.spyOn(service, "get").mockReturnValue(csrf.promise);
    const post = vi.spyOn(service, "post").mockResolvedValue(acceptance());
    const f = fixture();
    const mutableScope = { ...scope };
    const mutableOptions = { ...options };
    const result = service.approve("example", mutableScope, f.approve, mutableOptions);
    f.approve.rationale = "later input";
    mutableScope.workspaceId = otherId;
    mutableOptions.idempotencyKey = "later-key";
    csrf.resolve(response({ csrf_token: "synthetic-csrf" }));
    await result;
    expect(post.mock.calls[0]?.[1]).toEqual(fixture().approve);
    expect(post.mock.calls[0]?.[2]?.headers).toMatchObject({ "Idempotency-Key": options.idempotencyKey });
    const controller = new AbortController();
    controller.abort();
    await expect(
      service.approve("example", scope, fixture().approve, { ...options, signal: controller.signal })
    ).rejects.toMatchObject({ code: "CANCELLED" });
    expect(post).toHaveBeenCalledTimes(1);
  });
  it("rejects inherited request fields lost by snapshotting before CSRF", async () => {
    const service = new CurveScopedPrdV1Service();
    const get = mockCSRF(service);
    await expect(service.approve("example", scope, Object.create(fixture().approve), options)).rejects.toMatchObject({
      code: "INVALID",
    });
    expect(get).not.toHaveBeenCalled();
  });
  it("rejects malformed Unicode rationale before requesting CSRF", async () => {
    const service = new CurveScopedPrdV1Service();
    const get = mockCSRF(service);
    await expect(
      service.approve("example", scope, { ...fixture().approve, rationale: "invalid-\ud800" }, options)
    ).rejects.toMatchObject({ code: "INVALID" });
    expect(get).not.toHaveBeenCalled();
  });
  it.each(["network-loss", "aborted-after-success"])(
    "marks %s after mutation dispatch as outcome unknown, never domain cancellation",
    async (kind) => {
      const service = new CurveScopedPrdV1Service();
      mockCSRF(service);
      const controller = new AbortController();
      const post = vi.spyOn(service, "post").mockImplementation(async () => {
        if (kind === "network-loss") throw { code: "ERR_NETWORK", config: { data: fixture().approve } };
        controller.abort();
        return acceptance();
      });
      await expect(
        service.approve("example", scope, fixture().approve, { ...options, signal: controller.signal })
      ).rejects.toMatchObject({ code: "MUTATION_OUTCOME_UNKNOWN" });
      expect(post).toHaveBeenCalledTimes(1);
    }
  );
  it("keeps a pre-dispatch CSRF transport failure distinct from an uncertain mutation", async () => {
    const service = new CurveScopedPrdV1Service();
    vi.spyOn(service, "get").mockRejectedValue({ code: "ERR_NETWORK" });
    const post = vi.spyOn(service, "post");
    await expect(service.approve("example", scope, fixture().approve, options)).rejects.toMatchObject({
      code: "TRANSPORT",
    });
    expect(post).not.toHaveBeenCalled();
  });
  it("marks an invalid successful response as outcome unknown and never retries it", async () => {
    const service = new CurveScopedPrdV1Service();
    mockCSRF(service);
    const post = vi.spyOn(service, "post").mockResolvedValue(response({ leaked: "private rationale" }, 202));
    await expect(service.approve("example", scope, fixture().approve, options)).rejects.toMatchObject({
      code: "MUTATION_OUTCOME_UNKNOWN",
    });
    expect(post).toHaveBeenCalledTimes(1);
  });
  it("distinguishes abort during a successful mutation digest check from a cancelled read", async () => {
    const service = new CurveScopedPrdV1Service();
    mockCSRF(service);
    const controller = new AbortController();
    vi.stubGlobal("crypto", {
      subtle: {
        digest: async (algorithm: string, bytes: BufferSource) => {
          controller.abort();
          return webcrypto.subtle.digest(algorithm, bytes);
        },
      },
    });
    vi.spyOn(service, "post").mockResolvedValue(response(fixture().observation, 201, { etag: '"3"' }));
    await expect(
      service.captureObservation("example", scope, fixture().observe, { ...options, signal: controller.signal })
    ).rejects.toMatchObject({ code: "MUTATION_OUTCOME_UNKNOWN" });
    const readController = new AbortController();
    vi.stubGlobal("crypto", {
      subtle: {
        digest: async (algorithm: string, bytes: BufferSource) => {
          readController.abort();
          return webcrypto.subtle.digest(algorithm, bytes);
        },
      },
    });
    vi.spyOn(service, "get").mockResolvedValue(response(fixture().subject));
    await expect(
      service.retrieveCurrentSubject("example", scope, subjectExpectation(), readController.signal)
    ).rejects.toMatchObject({ code: "CANCELLED" });
  });
  it("does not recapture or silently submit when a protected GET becomes unavailable", async () => {
    const service = new CurveScopedPrdV1Service();
    const post = vi.spyOn(service, "post");
    const get = vi.spyOn(service, "get").mockRejectedValue({ response: { status: 404, data: { detail: "private" } } });
    const slot = new CurveExistingWorkReadSlot<CurveScopedPrdSubjectV1>();
    await slot.load((signal) => service.retrieveCurrentSubject("example", scope, subjectExpectation(), signal));
    expect(slot.snapshot).toEqual({ status: "UNAVAILABLE", data: null, code: "UNAVAILABLE" });
    expect(get).toHaveBeenCalledTimes(1);
    expect(post).not.toHaveBeenCalled();
  });
});

describe("ephemeral latest-read state", () => {
  it("discards stale responses after newer navigation, even when the transport ignores abort", async () => {
    const slot = new CurveExistingWorkReadSlot<{ id: string }>();
    const first = deferred<{ id: string }>();
    let firstSignal!: AbortSignal;
    const old = slot.load((signal) => {
      firstSignal = signal;
      return first.promise;
    });
    expect(slot.snapshot).toEqual({ status: "LOADING", data: null });
    await slot.load(async () => ({ id: "new" }));
    expect(firstSignal.aborted).toBe(true);
    first.resolve({ id: "old" });
    await expect(old).resolves.toBeNull();
    expect(slot.snapshot).toEqual({ status: "READY", data: { id: "new" } });
  });
  it("drops prior protected data during refresh, on logout, and on errors without retaining raw failures", async () => {
    const slot = new CurveExistingWorkReadSlot<{ id: string }>();
    await slot.load(async () => ({ id: "old" }));
    const next = deferred<{ id: string }>();
    const pending = slot.load(() => next.promise);
    expect(slot.snapshot).toEqual({ status: "LOADING", data: null });
    slot.clear();
    next.reject({ response: { data: "protected rationale" } });
    await expect(pending).resolves.toBeNull();
    expect(slot.snapshot).toEqual({ status: "IDLE", data: null });
    await slot.load(async () => {
      throw { response: { data: "protected rationale" } };
    });
    expect(slot.snapshot).toEqual({ status: "UNAVAILABLE", data: null, code: "TRANSPORT" });
    expect(JSON.stringify(slot)).not.toContain("protected rationale");
  });
});
