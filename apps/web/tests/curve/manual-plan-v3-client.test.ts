// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import { describe, it, expect, vi } from "vitest";
import {
  decodeManualPlanRevisionV3,
  decodeManualPlanSaveV3,
  decodeManualPlanStatusV3,
  ManualPlanDraftServiceV3,
} from "../../../../packages/services/src/curve/manual-plan-draft-v3.service";
import { payload, revision, status, target, result, response } from "./manual-plan-v3-fixtures";
import {
  decodeManualPlanSave as decodeLegacySave,
  decodeManualPlanStatus as decodeLegacyStatus,
  decodeManualPlanRevision as decodeLegacyRevision,
} from "../../../../packages/services/src/curve/manual-plan-draft.service";
import { payload as legacyPayload, status as legacyStatus, revision as legacyRevision } from "./manual-plan-fixtures";
const location = `/api/v1/workspaces/synthetic/curve/initiatives/${target.initiativeId}/manual-plan-drafts/v3/revisions/${revision.id}/`;
const command = () => ({ payload: structuredClone(payload), expectedVersion: 9, idempotencyKey: "synthetic-retry" });
const csrf = () => response({ csrf_token: "a".repeat(64) });

describe("two-stage manual draft transport", () => {
  it("decodes the frozen canonical save, status and immutable revision", async () => {
    expect(decodeManualPlanSaveV3(payload)).toEqual(payload);
    expect(decodeManualPlanStatusV3(status, target, 10)).toEqual(status);
    expect(await decodeManualPlanRevisionV3(revision, target, 10)).toEqual(revision);
  });
  it.each(["policy_edition", "controlling", "workspace_id", "initiative_id", "digest", "predecessor_id"])(
    "rejects revision substitution of %s",
    async (key) => {
      await expect(decodeManualPlanRevisionV3({ ...revision, [key]: "substituted" }, target, 10)).rejects.toThrow();
    }
  );
  it("rejects unknown fields, profile substitutions and inconsistent absent metadata", () => {
    expect(() => decodeManualPlanSaveV3({ ...payload, approved: true })).toThrow();
    expect(() =>
      decodeManualPlanSaveV3({
        ...payload,
        manual_profile_ref: { ...payload.manual_profile_ref, digest: "sha256:" + "0".repeat(64) },
      })
    ).toThrow();
    expect(() => decodeManualPlanStatusV3({ ...status, draft_status: "ABSENT" }, target, 10)).toThrow();
  });
  it("uses current typed ETag and never normalizes weak or foreign validators", async () => {
    await Promise.all(
      ["W/" + result(null).etag, '"10"', '"curve-initiative:30000000-0000-4000-8000-000000000999:v10"'].map(
        async (etag) => {
          const send = vi.fn().mockResolvedValue(response(status, 200, { ETag: etag }));
          await expect(new ManualPlanDraftServiceV3(send).status(target)).rejects.toThrow();
        }
      )
    );
  });
  it("sends exact save with fresh CSRF, session cookie policy and typed precondition", async () => {
    const send = vi
      .fn()
      .mockResolvedValueOnce(csrf())
      .mockResolvedValueOnce(response(revision, 201, { Location: location }));
    expect(await new ManualPlanDraftServiceV3(send).save(target, command())).toEqual(result(revision));
    expect(send.mock.calls[1][1]).toMatchObject({
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: {
        "If-Match": result(null, 9).etag,
        "Idempotency-Key": "synthetic-retry",
        "X-CSRFTOKEN": "a".repeat(64),
      },
    });
    expect(send.mock.calls).toHaveLength(2);
  });
  it("allows original replay under a newer current Initiative ETag", async () => {
    const send = vi
      .fn()
      .mockResolvedValueOnce(csrf())
      .mockResolvedValueOnce(response(revision, 200, { Location: location, ETag: result(null, 12).etag }));
    expect((await new ManualPlanDraftServiceV3(send).save(target, command())).currentVersion).toBe(12);
  });
  it.each(["network", "malformed", "server", "location"])(
    "keeps %s mutation outcome unknown without automatic retry",
    async (mode) => {
      const send = vi.fn().mockResolvedValueOnce(csrf());
      if (mode === "network") send.mockRejectedValueOnce(new Error("private response"));
      else
        send.mockResolvedValueOnce(
          response(mode === "malformed" ? { private: "hidden" } : revision, mode === "server" ? 500 : 201, {
            Location: mode === "location" ? "/other/" : location,
          })
        );
      await expect(new ManualPlanDraftServiceV3(send).save(target, command())).rejects.toMatchObject({
        code: "UNKNOWN",
      });
      expect(send).toHaveBeenCalledTimes(2);
    }
  );
  it("treats a received conflict as rejection without retaining its body", async () => {
    const send = vi
      .fn()
      .mockResolvedValueOnce(csrf())
      .mockResolvedValueOnce(response({ secret: "never keep" }, 412));
    await expect(new ManualPlanDraftServiceV3(send).save(target, command())).rejects.toMatchObject({
      code: "CONFLICT",
    });
  });
  it("bounds streamed reads and refuses cancellation before dispatch", async () => {
    const send = vi.fn().mockResolvedValue(response({ value: "x".repeat(70000) }));
    await expect(new ManualPlanDraftServiceV3(send).status(target)).rejects.toMatchObject({ code: "INVALID" });
    send.mockClear();
    const controller = new AbortController();
    controller.abort();
    await expect(new ManualPlanDraftServiceV3(send).status(target, controller.signal)).rejects.toMatchObject({
      code: "CANCELLED",
    });
    expect(send).not.toHaveBeenCalled();
  });
  it("snapshot protects the exact command while CSRF is in flight", async () => {
    let finish!: (value: Response) => void;
    const wait = new Promise<Response>((resolve) => {
      finish = resolve;
    });
    const send = vi
      .fn()
      .mockReturnValueOnce(wait)
      .mockResolvedValueOnce(response(revision, 201, { Location: location }));
    const input = command();
    const pending = new ManualPlanDraftServiceV3(send).save(target, input);
    input.payload.expected_draft_revision = 8;
    input.expectedVersion = 99;
    finish(csrf());
    await pending;
    expect(JSON.parse(send.mock.calls[1][1].body).expected_draft_revision).toBe(0);
  });
});

describe("explicit two-stage edition boundary", () => {
  it("rejects old documents in the two-stage client and new documents in the historical client", async () => {
    expect(() => decodeManualPlanSaveV3(legacyPayload)).toThrow();
    expect(() => decodeManualPlanStatusV3(legacyStatus, target, 10)).toThrow();
    await expect(decodeManualPlanRevisionV3(legacyRevision, target, 10)).rejects.toThrow();
    expect(() => decodeLegacySave(payload)).toThrow();
    expect(() => decodeLegacyStatus(status, target, 10)).toThrow();
    await expect(decodeLegacyRevision(revision, target, 10)).rejects.toThrow();
  });
  it("rejects a historical profile even when the outer edition is current", () => {
    expect(() =>
      decodeManualPlanSaveV3({ ...payload, manual_profile_ref: legacyPayload.manual_profile_ref })
    ).toThrow();
  });
  it("reads status, current and historical revisions only through the explicit v3 routes", async () => {
    const send = vi
      .fn()
      .mockResolvedValueOnce(response(status))
      .mockResolvedValueOnce(response(revision))
      .mockResolvedValueOnce(response(revision));
    const service = new ManualPlanDraftServiceV3(send);
    await service.status(target);
    await service.current(target);
    await service.revision(target, revision.id);
    const root = `/api/v1/workspaces/${target.workspaceSlug}/curve/initiatives/${target.initiativeId}/manual-plan-drafts/v3/`;
    expect(send.mock.calls.map(([url]) => url)).toEqual([
      root + "status/",
      root + "current/",
      root + `revisions/${revision.id}/`,
    ]);
  });
  it("sends no request when asked to save a historical edition", async () => {
    const send = vi.fn();
    await expect(
      new ManualPlanDraftServiceV3(send).save(target, { ...command(), payload: legacyPayload as never })
    ).rejects.toMatchObject({ code: "INVALID" });
    expect(send).not.toHaveBeenCalled();
  });
});
