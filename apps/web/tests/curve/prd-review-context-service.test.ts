/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import { describe, it, expect, vi } from "vitest";
import { CurveService, decodeCurvePrdReviewContext } from "@plane/services";
import fixture from "./fixtures/prd-review-context.json";
const sourceText = (relativePath: string) => readFileSync(new URL(relativePath, import.meta.url), "utf8");
const scope = {
  workspaceId: fixture.workspace_id,
  initiativeId: fixture.initiative_id,
  initiativeVersion: fixture.initiative_version,
};

describe("PRD metadata read decoding", () => {
  it("mirrors the exact closed backend schema", () => {
    const read = (path: string) => JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));
    expect(read("../../../../packages/services/src/curve/prd-review-context.schema.json")).toEqual(
      read("../../../../apps/api/plane/curve/prd_read_schemas/prd-review-context-v1.schema.json")
    );
  });
  it("uses a build-time validator with no runtime code generation", () => {
    const generated = sourceText("../../../../packages/services/src/curve/prd-review-context.validator.mjs");
    const hash = createHash("sha256")
      .update(sourceText("../../../../packages/services/src/curve/prd-review-context.schema.json"))
      .digest("hex");
    expect(generated).toContain(`Schema SHA-256: ${hash}`);
    expect(generated).not.toMatch(/new Function|eval\(/);
    expect(generated).toContain("Schema SHA-256:");
  });
  it("decodes valid metadata through native Node ESM outside Vite transforms", () => {
    const script = `import { readFileSync } from 'node:fs';
      import { decodeCurvePrdReviewContext } from './packages/services/src/curve/prd-review-context.ts';
      const data = JSON.parse(readFileSync('apps/web/tests/curve/fixtures/prd-review-context.json', 'utf8'));
      const result = decodeCurvePrdReviewContext(data, { workspaceId: data.workspace_id, initiativeId: data.initiative_id, initiativeVersion: data.initiative_version });
      if (result.schema_version !== 'curve.prd-review-context/v1-candidate') process.exit(1);`;
    const relativeRoot = "../../../../";
    expect(() =>
      execFileSync(process.execPath, ["--experimental-strip-types", "--input-type=module", "-e", script], {
        cwd: fileURLToPath(new URL(relativeRoot, import.meta.url)),
        stdio: "pipe",
      })
    ).not.toThrow();
  });
  it("returns a detached validated exact-scope record", () => {
    const source = structuredClone(fixture);
    const parsed = decodeCurvePrdReviewContext(source, scope);
    source.reviewer.display_name = "Changed source";
    expect(parsed.reviewer.display_name).toBe("Fictional Reviewer 1");
    expect(parsed.command_preconditions.commandETag).toBe('"7"');
  });
  it.each(["body", "rationale", "storage_url", "raw_error"])("rejects forbidden top-level %s", (key) => {
    expect(() => decodeCurvePrdReviewContext({ ...fixture, [key]: "not displayable" }, scope)).toThrow(
      /could not be verified/
    );
  });
  it("rejects forbidden nested metadata", () => {
    const record = structuredClone(fixture);
    Object.assign(record.checkpoint.metadata!, { body: "not displayable" });
    expect(() => decodeCurvePrdReviewContext(record, scope)).toThrow();
  });
  it("rejects foreign workspace, initiative and version", () => {
    for (const field of ["workspaceId", "initiativeId", "initiativeVersion"] as const) {
      expect(() =>
        decodeCurvePrdReviewContext(fixture, { ...scope, [field]: field === "initiativeVersion" ? 8 : "other" })
      ).toThrow();
    }
  });
  it.each(['W/"7"', '"initiative-7"', '"8"'])("rejects incompatible PRD concurrency token %s", (etag) => {
    const record = structuredClone(fixture);
    record.command_preconditions.commandETag = etag;
    expect(() => decodeCurvePrdReviewContext(record, scope)).toThrow();
  });
  it("does not accept a command capability or manufacture absence", () => {
    const record = structuredClone(fixture);
    record.capabilities.approve.available = true;
    expect(() => decodeCurvePrdReviewContext(record, scope)).toThrow();
    const absent = structuredClone(fixture);
    absent.checkpoint.availability = "ABSENT";
    expect(() => decodeCurvePrdReviewContext(absent, scope)).toThrow();
  });
  it("separates a stale new-submission report from a submitted checkpoint", () => {
    const record = structuredClone(fixture);
    Object.assign(record.readiness.metadata!, {
      applicability: "STALE",
      applicability_reasons: ["EXACT_SUBJECT_CHANGED"],
      ready_for_submission: false,
    });
    expect(decodeCurvePrdReviewContext(record, scope).checkpoint.metadata?.checkpoint_number).toBe(2);
    record.readiness.metadata!.ready_for_submission = true;
    expect(() => decodeCurvePrdReviewContext(record, scope)).toThrow();
  });
  it("does not render an impossible PRD review without a checkpoint", () => {
    const record = structuredClone(fixture);
    record.checkpoint = { availability: "ABSENT", metadata: null } as never;
    expect(() => decodeCurvePrdReviewContext(record, scope)).toThrow();
  });
  it("preserves unavailable checkpoint metadata without inventing absence", () => {
    const record = structuredClone(fixture);
    record.checkpoint = { availability: "UNAVAILABLE", metadata: null } as never;
    expect(decodeCurvePrdReviewContext(record, scope).checkpoint.availability).toBe("UNAVAILABLE");
  });
  it("rejects a decision bound to a different submitted checkpoint", () => {
    const record = structuredClone(fixture);
    record.state = "PLANNING";
    record.decision = {
      availability: "PRESENT",
      metadata: {
        id: "00000000-0000-4000-8000-000000000088",
        metadata_schema_version: "2.0-candidate",
        state: "APPROVED",
        gate_assignment_id: fixture.reviewer.assignment_id,
        checkpoint_id: fixture.checkpoint.metadata!.id,
        artifact_version_id: fixture.checkpoint.metadata!.artifact_version_id,
        evidence_snapshot_id: fixture.checkpoint.metadata!.evidence_snapshot_id,
        provider_version: fixture.checkpoint.metadata!.provider_version,
        content_digest: fixture.checkpoint.metadata!.content_digest,
        confirmed_risk_tier: "STANDARD",
        decided_by: fixture.reviewer.identity,
        decided_at: fixture.observed_at,
      },
    } as never;
    expect(() => decodeCurvePrdReviewContext(record, scope)).not.toThrow();
    for (const field of [
      "checkpoint_id",
      "artifact_version_id",
      "evidence_snapshot_id",
      "provider_version",
      "content_digest",
    ]) {
      const tampered = structuredClone(record);
      Object.assign(tampered.decision.metadata!, {
        [field]:
          field === "content_digest"
            ? `sha256:${"b".repeat(64)}`
            : field === "provider_version"
              ? "999"
              : "00000000-0000-4000-8000-000000000077",
      });
      expect(() => decodeCurvePrdReviewContext(tampered, scope)).toThrow();
    }
  });
  it.each(["submit", "approve", "request_changes", "reject"] as const)(
    "rejects stale capability evaluation for %s",
    (name) => {
      const record = structuredClone(fixture);
      record.capabilities[name].evaluated_at = "2026-10-01T12:00:00.000Z";
      expect(() => decodeCurvePrdReviewContext(record, scope)).toThrow();
    }
  );
  it.each([
    ["CURRENT", "CURRENT_OBSERVATION_UNAVAILABLE", true],
    ["STALE", "EXACT_SUBJECT_MATCH", false],
    ["UNVERIFIED", "EXACT_SUBJECT_CHANGED", false],
  ])("rejects contradictory applicability %s and %s", (applicability, reason, ready) => {
    const record = structuredClone(fixture);
    Object.assign(record.readiness.metadata!, {
      applicability,
      applicability_reasons: [reason],
      ready_for_submission: ready,
    });
    expect(() => decodeCurvePrdReviewContext(record, scope)).toThrow();
  });
  it("uses authenticated GET only, encodes route identifiers and passes cancellation", async () => {
    const service = new CurveService("http://curve.test");
    const get = vi.spyOn(service, "get").mockResolvedValue({ data: fixture } as never);
    const post = vi.spyOn(service, "post");
    const controller = new AbortController();
    await service.retrievePrdReviewContext("example/workspace", scope, controller.signal);
    expect(get).toHaveBeenCalledWith(
      `/api/v1/workspaces/example%2Fworkspace/curve/initiatives/${scope.initiativeId}/prd/review-context/`,
      { signal: controller.signal, headers: { "Cache-Control": "no-cache" } }
    );
    expect(post).not.toHaveBeenCalled();
  });
});
