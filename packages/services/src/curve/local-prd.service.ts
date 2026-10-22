// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import type { CurveExistingWorkInitiativeScope, CurveExistingWorkMutation } from "@plane/types";
import {
  CurveExistingWorkTransport,
  curveExistingWorkRoot,
  curveExistingWorkId,
  curveExistingWorkMutation,
  curveExistingWorkEtag,
} from "./existing-work-transport";
import {
  requireCurve,
  requireCurveDigest,
  isCurveUuid,
  isCurveVersion,
  validateCurveScope,
} from "./existing-work-validation";

import { decodeLocalPrdReopening } from "./local-prd-reopening.validation";
import type { LocalPrdReopeningCurrent } from "./local-prd-reopening.validation";
export type { LocalPrdReopening, LocalPrdReopeningCurrent } from "./local-prd-reopening.validation";
import { decodeLocalSubmission, decodeLocalDecision, localReviewExact } from "./local-prd-review.validation";
import type { LocalSubmission, LocalDecision, LocalReviewAction } from "./local-prd-review.validation";
export type { LocalSubmission, LocalDecision, LocalReviewAction } from "./local-prd-review.validation";
export type CurveLocalReviewCurrent = {
  schema_version: "curve.local-prd-review-current/v1-candidate";
  initiative_version: number;
  initiative_state: string;
  source: CurveLocalPrdSource | null;
  submission: LocalSubmission | null;
  decision: LocalDecision | null;
  submission_is_current: boolean;
  available_actions: LocalReviewAction[];
};
function reviewRoot(slug: string, scope: CurveExistingWorkInitiativeScope) {
  return root(slug, scope).replace(/sources\/$/, "review/");
}

export const CURVE_LOCAL_PRD_MAX_BYTES = 10 * 1024 * 1024;
type Media = "application/pdf" | "text/markdown" | "text/plain";
type Reference = { object_id: string; digest: string; size_bytes: number; media_type: string };
export type CurveLocalPrdSource = {
  schema_version: "curve.local-prd-source/v1-candidate";
  source_kind: "LOCAL_UPLOAD";
  id: string;
  workspace_id: string;
  initiative_id: string;
  version: number;
  predecessor_id: string | null;
  uploaded_by: string;
  uploaded_at: string;
  original: Reference;
  snapshot: Reference;
  normalization_schema_version: "curve.local-upload.normalized/v1-candidate";
  digest: string;
};
export type CurveLocalPrdCurrent = {
  schema_version: "curve.local-prd-current/v1-candidate";
  source: CurveLocalPrdSource | null;
  initiative_version: number;
  upload_available: boolean;
};
function exact(input: unknown, keys: string): asserts input is Record<string, unknown> {
  requireCurve(input !== null && typeof input === "object" && !Array.isArray(input));
  const expected = keys.split(",");
  requireCurve(Object.keys(input).length === expected.length && expected.every((key) => Object.hasOwn(input, key)));
}
function digest(input: unknown): input is string {
  return typeof input === "string" && /^sha256:[0-9a-f]{64}$/.test(input);
}
function reference(input: unknown, snapshot: boolean): asserts input is Reference {
  exact(input, "object_id,digest,size_bytes,media_type");
  requireCurve(isCurveUuid(input.object_id) && digest(input.digest) && isCurveVersion(input.size_bytes));
  requireCurve(input.size_bytes <= (snapshot ? 6 * CURVE_LOCAL_PRD_MAX_BYTES + 4096 : CURVE_LOCAL_PRD_MAX_BYTES));
  requireCurve(
    (snapshot ? ["application/json"] : ["application/pdf", "text/plain", "text/markdown"]).includes(
      String(input.media_type)
    )
  );
}
export async function decodeCurveLocalPrdSource(
  input: unknown,
  scope: CurveExistingWorkInitiativeScope
): Promise<CurveLocalPrdSource> {
  validateCurveScope(scope);
  const data: unknown = structuredClone(input);
  exact(
    data,
    "schema_version,source_kind,id,workspace_id,initiative_id,version,predecessor_id,uploaded_by,uploaded_at,original,snapshot,normalization_schema_version,digest"
  );
  requireCurve(data.schema_version === "curve.local-prd-source/v1-candidate" && data.source_kind === "LOCAL_UPLOAD");
  requireCurve(data.normalization_schema_version === "curve.local-upload.normalized/v1-candidate");
  requireCurve(data.workspace_id === scope.workspaceId && data.initiative_id === scope.initiativeId);
  requireCurve(isCurveUuid(data.id) && isCurveUuid(data.uploaded_by) && isCurveVersion(data.version));
  requireCurve(
    data.version === 1
      ? data.predecessor_id === null
      : isCurveUuid(data.predecessor_id) && data.predecessor_id !== data.id
  );
  requireCurve(
    typeof data.uploaded_at === "string" &&
      /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$/.test(data.uploaded_at) &&
      Number.isFinite(Date.parse(data.uploaded_at))
  );
  reference(data.original, false);
  reference(data.snapshot, true);
  requireCurve(data.original.object_id !== data.snapshot.object_id && digest(data.digest));
  const { digest: expected, ...metadata } = data;
  await requireCurveDigest(metadata, expected as string);
  return data as CurveLocalPrdSource;
}
function root(slug: string, scope: CurveExistingWorkInitiativeScope) {
  validateCurveScope(scope);
  return `${curveExistingWorkRoot(slug)}initiatives/${curveExistingWorkId(scope.initiativeId)}/local-prd/v1/sources/`;
}
export class CurveLocalPrdService extends CurveExistingWorkTransport {
  retrieveReopening(
    slug: string,
    scope: CurveExistingWorkInitiativeScope,
    review: CurveLocalReviewCurrent,
    signal?: AbortSignal
  ): Promise<LocalPrdReopeningCurrent> {
    return this.safely(async () => {
      const response = await this.read(`${root(slug, scope).replace(/sources\/$/, "reopening/")}`, signal);
      const data: unknown = structuredClone(response.data);
      localReviewExact(data, "schema_version,initiative_version,initiative_state,can_reopen,reopening");
      requireCurve(
        data.schema_version === "curve.local-prd-reopening-current/v1-candidate" &&
          isCurveVersion(data.initiative_version) &&
          data.initiative_version === review.initiative_version &&
          data.initiative_state === review.initiative_state &&
          typeof data.can_reopen === "boolean"
      );
      const submission = review.submission === null ? null : await decodeLocalSubmission(review.submission, scope);
      const decision = review.decision === null ? null : await decodeLocalDecision(review.decision, scope, submission!);
      requireCurve(data.reopening === null || (submission !== null && decision?.state === "APPROVED"));
      const reopening =
        data.reopening === null ? null : await decodeLocalPrdReopening(data.reopening, scope, submission!, decision!);
      if (reopening)
        requireCurve(
          !review.submission_is_current &&
            reopening.initiative_version < data.initiative_version &&
            ["ALIGNING", "PAUSED", "CANCELLED"].includes(String(data.initiative_state))
        );
      if (data.can_reopen)
        requireCurve(
          !reopening &&
            decision?.state === "APPROVED" &&
            review.submission_is_current &&
            data.initiative_state === "PLANNING"
        );
      curveExistingWorkEtag(response, `"${data.initiative_version}"`);
      this.checkCancellation(signal);
      return { ...data, reopening } as LocalPrdReopeningCurrent;
    });
  }
  reopen(
    slug: string,
    scope: CurveExistingWorkInitiativeScope,
    review: CurveLocalReviewCurrent,
    options: CurveExistingWorkMutation
  ) {
    return this.safely(async () => {
      const command = curveExistingWorkMutation(options);
      requireCurve(
        review.source &&
          review.submission &&
          review.decision &&
          review.submission_is_current &&
          review.initiative_state === "PLANNING"
      );
      const source = await decodeCurveLocalPrdSource(review.source, scope);
      const submission = await decodeLocalSubmission(review.submission, scope);
      const decision = await decodeLocalDecision(review.decision, scope, submission);
      requireCurve(
        decision.state === "APPROVED" &&
          submission.source_id === source.id &&
          submission.source_digest === source.digest &&
          submission.content_digest === source.snapshot.digest &&
          submission.source_version === source.version &&
          review.initiative_version === command.expectedVersion
      );
      const path = root(slug, scope).replace(/sources\/$/, "");
      const response = await this.mutate(
        `${path}reopening/`,
        {
          action: "REOPEN",
          source_id: source.id,
          source_digest: source.digest,
          submission_id: submission.id,
          submission_digest: submission.digest,
          decision_id: decision.id,
          decision_digest: decision.digest,
        },
        command,
        `"${command.expectedVersion}"`
      );
      return this.verifyMutation(command.signal, async () => {
        requireCurve(response.status === 201 || response.status === 200);
        const data = await decodeLocalPrdReopening(response.data, scope, submission, decision);
        requireCurve(data.initiative_version === command.expectedVersion);
        requireCurve(response.headers.location === `${path}reopenings/${data.id}/`);
        requireCurve(response.headers["idempotency-replayed"] === (response.status === 200 ? "true" : "false"));
        requireCurve(typeof response.headers.etag === "string");
        const etag = curveExistingWorkEtag(response, response.headers.etag);
        requireCurve(/^"[1-9][0-9]*"$/.test(etag));
        const version = Number(etag.slice(1, -1));
        requireCurve(
          isCurveVersion(version) &&
            (response.status === 201 ? version === command.expectedVersion + 1 : version >= command.expectedVersion + 1)
        );
        return { data, initiativeVersion: version, etag, replayed: response.status === 200 };
      });
    });
  }

  retrieveReview(
    slug: string,
    scope: CurveExistingWorkInitiativeScope,
    signal?: AbortSignal
  ): Promise<CurveLocalReviewCurrent> {
    return this.safely(async () => {
      const response = await this.read(`${reviewRoot(slug, scope)}current/`, signal);
      const data: unknown = structuredClone(response.data);
      localReviewExact(
        data,
        "schema_version,initiative_version,initiative_state,source,submission,decision,submission_is_current,available_actions"
      );
      requireCurve(
        data.schema_version === "curve.local-prd-review-current/v1-candidate" && isCurveVersion(data.initiative_version)
      );
      requireCurve(typeof data.initiative_state === "string" && typeof data.submission_is_current === "boolean");
      requireCurve(
        Array.isArray(data.available_actions) &&
          new Set(data.available_actions).size === data.available_actions.length &&
          data.available_actions.every((action) => ["SUBMIT", "APPROVE", "REQUEST_CHANGES"].includes(action))
      );
      const source = data.source === null ? null : await decodeCurveLocalPrdSource(data.source, scope);
      const submission = data.submission === null ? null : await decodeLocalSubmission(data.submission, scope);
      requireCurve(data.decision === null || submission !== null);
      const decision = data.decision === null ? null : await decodeLocalDecision(data.decision, scope, submission!);
      if (submission) requireCurve(submission.initiative_version < data.initiative_version);
      if (decision) requireCurve(decision.initiative_version < data.initiative_version);
      if (data.submission_is_current)
        requireCurve(
          source &&
            submission &&
            submission.source_id === source.id &&
            submission.source_version === source.version &&
            submission.source_digest === source.digest &&
            submission.content_digest === source.snapshot.digest
        );
      if (data.available_actions.includes("SUBMIT")) requireCurve(source && data.initiative_state === "ALIGNING");
      if (data.available_actions.some((action) => action !== "SUBMIT"))
        requireCurve(
          source && submission && !decision && data.submission_is_current && data.initiative_state === "PRD_REVIEW"
        );
      curveExistingWorkEtag(response, `"${data.initiative_version}"`);
      this.checkCancellation(signal);
      return { ...data, source, submission, decision } as CurveLocalReviewCurrent;
    });
  }
  review(
    slug: string,
    scope: CurveExistingWorkInitiativeScope,
    source: CurveLocalPrdSource,
    action: LocalReviewAction,
    submission: LocalSubmission | null,
    feedback: string | null,
    options: CurveExistingWorkMutation
  ) {
    return this.safely(async () => {
      const command = curveExistingWorkMutation(options);
      const current = await decodeCurveLocalPrdSource(source, scope);
      requireCurve(["SUBMIT", "APPROVE", "REQUEST_CHANGES"].includes(action));
      const subject = submission === null ? null : await decodeLocalSubmission(submission, scope);
      requireCurve(
        action === "SUBMIT"
          ? subject === null
          : subject !== null &&
              subject.source_id === current.id &&
              subject.source_digest === current.digest &&
              subject.content_digest === current.snapshot.digest
      );
      if (action === "REQUEST_CHANGES")
        requireCurve(
          typeof feedback === "string" &&
            feedback.trim().length > 0 &&
            !feedback.includes("\u0000") &&
            new TextDecoder("utf-8", { fatal: true }).decode(new TextEncoder().encode(feedback)) === feedback &&
            new TextEncoder().encode(feedback).length <= 16384
        );
      else requireCurve(feedback === null);
      const body = {
        action,
        source_id: current.id,
        source_digest: current.digest,
        ...(subject ? { submission_id: subject.id, submission_digest: subject.digest } : {}),
        ...(action === "REQUEST_CHANGES" ? { feedback } : {}),
      };
      const path = reviewRoot(slug, scope);
      const response = await this.mutate(`${path}commands/`, body, command, `"${command.expectedVersion}"`);
      return this.verifyMutation(command.signal, async () => {
        requireCurve(response.status === 201 || response.status === 200);
        const data =
          action === "SUBMIT"
            ? await decodeLocalSubmission(response.data, scope)
            : await decodeLocalDecision(response.data, scope, subject!);
        requireCurve(
          data.initiative_version === command.expectedVersion &&
            data.source_id === current.id &&
            data.source_digest === current.digest
        );
        if (action === "SUBMIT")
          requireCurve(
            (data as LocalSubmission).source_version === current.version &&
              (data as LocalSubmission).content_digest === current.snapshot.digest
          );
        if (action === "REQUEST_CHANGES") {
          const bytes = new TextEncoder().encode(feedback!);
          const hash = await globalThis.crypto.subtle.digest("SHA-256", bytes);
          const ref = (data as LocalDecision).feedback;
          requireCurve(
            ref &&
              ref.size_bytes === bytes.length &&
              ref.digest ===
                `sha256:${Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("")}`
          );
        }
        if (action !== "SUBMIT")
          requireCurve((data as LocalDecision).state === (action === "APPROVE" ? "APPROVED" : "CHANGES_REQUESTED"));
        requireCurve(
          response.headers.location === `${path}${action === "SUBMIT" ? "submissions" : "decisions"}/${data.id}/`
        );
        requireCurve(response.headers["idempotency-replayed"] === (response.status === 200 ? "true" : "false"));
        requireCurve(typeof response.headers.etag === "string");
        const etag = curveExistingWorkEtag(response, response.headers.etag);
        requireCurve(/^"[1-9][0-9]*"$/.test(etag));
        const version = Number(etag.slice(1, -1));
        requireCurve(
          isCurveVersion(version) &&
            (response.status === 201 ? version === command.expectedVersion + 1 : version >= command.expectedVersion + 1)
        );
        return { data, initiativeVersion: version, etag, replayed: response.status === 200 };
      });
    });
  }
  retrieveFeedback(
    slug: string,
    scope: CurveExistingWorkInitiativeScope,
    decision: LocalDecision,
    submission: LocalSubmission,
    signal?: AbortSignal
  ): Promise<string> {
    return this.safely(async () => {
      const item = await decodeLocalDecision(decision, scope, submission);
      requireCurve(item.feedback !== null);
      const response = await this.get(`${reviewRoot(slug, scope)}decisions/${curveExistingWorkId(item.id)}/feedback/`, {
        signal,
        responseType: "arraybuffer",
        headers: { "Cache-Control": "no-store" },
      });
      requireCurve(
        response.status === 200 &&
          response.data instanceof ArrayBuffer &&
          response.data.byteLength === item.feedback.size_bytes
      );
      const hash = await globalThis.crypto.subtle.digest("SHA-256", response.data);
      requireCurve(
        `sha256:${Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("")}` ===
          item.feedback.digest
      );
      const text = new TextDecoder("utf-8", { fatal: true }).decode(response.data);
      this.checkCancellation(signal);
      return text;
    });
  }
  retrieveCurrent(
    slug: string,
    scope: CurveExistingWorkInitiativeScope,
    signal?: AbortSignal
  ): Promise<CurveLocalPrdCurrent> {
    return this.safely(async () => {
      const response = await this.read(`${root(slug, scope)}current/`, signal);
      const data: unknown = structuredClone(response.data);
      exact(data, "schema_version,source,initiative_version,upload_available");
      requireCurve(
        data.schema_version === "curve.local-prd-current/v1-candidate" &&
          isCurveVersion(data.initiative_version) &&
          typeof data.upload_available === "boolean"
      );
      const source = data.source === null ? null : await decodeCurveLocalPrdSource(data.source, scope);
      curveExistingWorkEtag(response, `"${data.initiative_version}"`);
      this.checkCancellation(signal);
      return {
        schema_version: "curve.local-prd-current/v1-candidate",
        source,
        initiative_version: data.initiative_version,
        upload_available: data.upload_available,
      };
    });
  }
  upload(
    slug: string,
    scope: CurveExistingWorkInitiativeScope,
    file: File,
    sourceVersion: number,
    options: CurveExistingWorkMutation
  ) {
    return this.safely(async () => {
      const path = root(slug, scope);
      const command = curveExistingWorkMutation(options);
      requireCurve(
        Number.isSafeInteger(sourceVersion) && sourceVersion >= 0 && sourceVersion < Number.MAX_SAFE_INTEGER
      );
      requireCurve(file.size > 0 && file.size <= CURVE_LOCAL_PRD_MAX_BYTES);
      const extension = file.name.toLowerCase().split(".").pop();
      const media: Media | undefined =
        extension === "pdf"
          ? "application/pdf"
          : extension === "md"
            ? "text/markdown"
            : extension === "txt"
              ? "text/plain"
              : undefined;
      requireCurve(media);
      const response = await this.mutate(path, file, command, `"${command.expectedVersion}"`, {
        contentType: media,
        sourceVersion,
      });
      return this.verifyMutation(command.signal, async () => {
        requireCurve(response.status === 201 || response.status === 200);
        const data = await decodeCurveLocalPrdSource(response.data, scope);
        requireCurve(
          data.version === sourceVersion + 1 &&
            data.original.size_bytes === file.size &&
            data.original.media_type === media
        );
        requireCurve(response.headers.location === `${path}${data.id}/`);
        requireCurve(response.headers["idempotency-replayed"] === (response.status === 200 ? "true" : "false"));
        return {
          data,
          etag: curveExistingWorkEtag(response, `"${command.expectedVersion}"`),
          replayed: response.status === 200,
        };
      });
    });
  }
  retrieveContent(
    slug: string,
    scope: CurveExistingWorkInitiativeScope,
    source: CurveLocalPrdSource,
    signal?: AbortSignal
  ): Promise<Blob> {
    return this.safely(async () => {
      const verified = await decodeCurveLocalPrdSource(source, scope);
      this.checkCancellation(signal);
      const response = await this.get(`${root(slug, scope)}${curveExistingWorkId(verified.id)}/content/`, {
        signal,
        responseType: "arraybuffer",
        headers: { "Cache-Control": "no-store" },
      });
      requireCurve(response.status === 200 && response.data instanceof ArrayBuffer);
      requireCurve(response.data.byteLength === verified.original.size_bytes);
      const hash = await globalThis.crypto.subtle.digest("SHA-256", response.data);
      requireCurve(
        `sha256:${Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("")}` ===
          verified.original.digest
      );
      this.checkCancellation(signal);
      // Text is always exposed as plain text; the viewer owns and revokes its object URL.
      return new Blob([response.data], {
        type: verified.original.media_type === "application/pdf" ? "application/pdf" : "text/plain;charset=utf-8",
      });
    });
  }
}
