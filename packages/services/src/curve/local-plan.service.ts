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
import { requireCurve, isCurveVersion, validateCurveScope } from "./existing-work-validation";
import { localReviewExact } from "./local-prd-review.validation";
import type { LocalReviewAction } from "./local-prd-review.validation";
import {
  decodeLocalPlanApproval,
  localPlanRevisionApprovalReferences,
  decodeLocalPlanRevision,
  decodeLocalPlanSubmission,
  decodeLocalPlanDecision,
} from "./local-plan.validation";
import type {
  LocalPlanApproval,
  LocalPlanRevision,
  LocalPlanSubmission,
  LocalPlanDecision,
  LocalPlanReference,
} from "./local-plan.validation";
export * from "./local-plan.validation";
export type LocalPlanCurrent = LocalPlanApproval & {
  /** Client-derived approval context for reading a retained plan revision. */
  revision_approval?: LocalPlanApproval;
  schema_version: "curve.local-plan-current/v1-candidate";
  revision: LocalPlanRevision | null;
  initiative_version: number;
  upload_available: boolean;
};
export type LocalPlanReviewCurrent = LocalPlanApproval & {
  /** Historical context grants no current review authority. */
  revision_approval?: LocalPlanApproval;
  schema_version: "curve.local-plan-review-current/v1-candidate";
  revision: LocalPlanRevision | null;
  initiative_version: number;
  initiative_state: "PLANNING";
  revision_is_current: boolean;
  submission: LocalPlanSubmission | null;
  decision: LocalPlanDecision | null;
  available_actions: LocalReviewAction[];
};
function root(slug: string, scope: CurveExistingWorkInitiativeScope) {
  validateCurveScope(scope);
  return `${curveExistingWorkRoot(slug)}initiatives/${curveExistingWorkId(scope.initiativeId)}/local-plan/v1/`;
}
function pins(approval: LocalPlanApproval) {
  return {
    prd_submission_id: approval.prd_submission.id,
    prd_submission_digest: approval.prd_submission.digest,
    prd_decision_id: approval.prd_approval.id,
    prd_decision_digest: approval.prd_approval.digest,
  };
}
async function hash(bytes: ArrayBuffer) {
  return `sha256:${Array.from(new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", bytes)), (b) => b.toString(16).padStart(2, "0")).join("")}`;
}
export class CurveLocalPlanService extends CurveExistingWorkTransport {
  private async revisionApproval(
    slug: string,
    scope: CurveExistingWorkInitiativeScope,
    revision: unknown,
    current: LocalPlanApproval,
    initiativeVersion: number,
    signal?: AbortSignal
  ): Promise<LocalPlanApproval> {
    const refs = await localPlanRevisionApprovalReferences(revision, scope);
    if (
      refs.submissionId === current.prd_submission.id &&
      refs.submissionDigest === current.prd_submission.digest &&
      refs.decisionId === current.prd_approval.id &&
      refs.decisionDigest === current.prd_approval.digest
    )
      return current;
    const path = root(slug, scope).replace(/local-plan\/v1\/$/, "local-prd/v1/review/");
    const [submission, decision] = await Promise.all([
      this.read(`${path}submissions/${curveExistingWorkId(refs.submissionId)}/`, signal),
      this.read(`${path}decisions/${curveExistingWorkId(refs.decisionId)}/`, signal),
    ]);
    curveExistingWorkEtag(submission, `"${initiativeVersion}"`);
    curveExistingWorkEtag(decision, `"${initiativeVersion}"`);
    const historical = await decodeLocalPlanApproval(
      { prd_submission: submission.data, prd_approval: decision.data },
      scope
    );
    requireCurve(
      historical.prd_submission.id === refs.submissionId &&
        historical.prd_submission.digest === refs.submissionDigest &&
        historical.prd_approval.id === refs.decisionId &&
        historical.prd_approval.digest === refs.decisionDigest &&
        historical.prd_approval.initiative_version < current.prd_approval.initiative_version
    );
    this.checkCancellation(signal);
    return historical;
  }

  retrieveCurrent(
    slug: string,
    scope: CurveExistingWorkInitiativeScope,
    signal?: AbortSignal
  ): Promise<LocalPlanCurrent> {
    return this.safely(async () => {
      const response = await this.read(`${root(slug, scope)}revisions/current/`, signal);
      const data: unknown = structuredClone(response.data);
      localReviewExact(data, "schema_version,revision,initiative_version,prd_submission,prd_approval,upload_available");
      requireCurve(
        data.schema_version === "curve.local-plan-current/v1-candidate" &&
          isCurveVersion(data.initiative_version) &&
          typeof data.upload_available === "boolean"
      );
      const approval = await decodeLocalPlanApproval(data as unknown as LocalPlanApproval, scope);
      const revisionApproval =
        data.revision === null
          ? approval
          : await this.revisionApproval(slug, scope, data.revision, approval, data.initiative_version, signal);
      const revision =
        data.revision === null ? null : await decodeLocalPlanRevision(data.revision, scope, revisionApproval);
      if (revision) requireCurve(revision.initiative_version <= data.initiative_version);
      curveExistingWorkEtag(response, `"${data.initiative_version}"`);
      this.checkCancellation(signal);
      return { ...data, ...approval, revision, revision_approval: revisionApproval } as LocalPlanCurrent;
    });
  }
  retrieveReview(
    slug: string,
    scope: CurveExistingWorkInitiativeScope,
    signal?: AbortSignal
  ): Promise<LocalPlanReviewCurrent> {
    return this.safely(async () => {
      const response = await this.read(`${root(slug, scope)}review/current/`, signal);
      const data: unknown = structuredClone(response.data);
      localReviewExact(
        data,
        "schema_version,initiative_version,initiative_state,revision,prd_submission,prd_approval,submission,decision,revision_is_current,available_actions"
      );
      requireCurve(
        data.schema_version === "curve.local-plan-review-current/v1-candidate" &&
          isCurveVersion(data.initiative_version) &&
          data.initiative_state === "PLANNING" &&
          typeof data.revision_is_current === "boolean"
      );
      const approval = await decodeLocalPlanApproval(data as unknown as LocalPlanApproval, scope);
      const revisionApproval =
        data.revision === null
          ? approval
          : await this.revisionApproval(slug, scope, data.revision, approval, data.initiative_version, signal);
      const revision =
        data.revision === null ? null : await decodeLocalPlanRevision(data.revision, scope, revisionApproval);
      if (data.submission !== null) requireCurve(revision);
      const submission =
        data.submission === null
          ? null
          : await decodeLocalPlanSubmission(data.submission, scope, revision!, revisionApproval);
      if (data.decision !== null) requireCurve(submission);
      const decision =
        data.decision === null
          ? null
          : await decodeLocalPlanDecision(data.decision, scope, revision!, submission!, revisionApproval);
      for (const record of [revision, submission, decision])
        if (record) requireCurve(record.initiative_version <= data.initiative_version);
      requireCurve(
        Array.isArray(data.available_actions) &&
          new Set(data.available_actions).size === data.available_actions.length &&
          data.available_actions.every((a) => ["SUBMIT", "APPROVE", "REQUEST_CHANGES"].includes(a))
      );
      requireCurve(
        data.revision_is_current ===
          !!(
            revision &&
            revision.prd_submission_id === approval.prd_submission.id &&
            revision.prd_submission_digest === approval.prd_submission.digest &&
            revision.prd_decision_id === approval.prd_approval.id &&
            revision.prd_decision_digest === approval.prd_approval.digest
          )
      );
      if (data.available_actions.length) requireCurve(revision && data.revision_is_current);
      if (data.available_actions.includes("SUBMIT")) requireCurve(!submission);
      if (data.available_actions.some((a) => a !== "SUBMIT")) requireCurve(submission && !decision);
      curveExistingWorkEtag(response, `"${data.initiative_version}"`);
      this.checkCancellation(signal);
      return {
        ...data,
        ...approval,
        revision,
        submission,
        decision,
        revision_approval: revisionApproval,
      } as LocalPlanReviewCurrent;
    });
  }
  upload(
    slug: string,
    scope: CurveExistingWorkInitiativeScope,
    file: File,
    sourceVersion: number,
    approval: LocalPlanApproval,
    options: CurveExistingWorkMutation
  ) {
    return this.safely(async () => {
      const accepted = await decodeLocalPlanApproval(approval, scope);
      const command = curveExistingWorkMutation(options);
      requireCurve(
        Number.isSafeInteger(sourceVersion) &&
          sourceVersion >= 0 &&
          sourceVersion < Number.MAX_SAFE_INTEGER &&
          file.size > 0 &&
          file.size <= 10485760
      );
      const ext = file.name.toLowerCase().split(".").pop();
      const media =
        ext === "pdf" ? "application/pdf" : ext === "md" ? "text/markdown" : ext === "txt" ? "text/plain" : undefined;
      requireCurve(media);
      const path = `${root(slug, scope)}revisions/`;
      const response = await this.mutate(path, file, command, `"${command.expectedVersion}"`, {
        contentType: media,
        sourceVersion,
        planApproval: {
          submissionId: accepted.prd_submission.id,
          submissionDigest: accepted.prd_submission.digest,
          decisionId: accepted.prd_approval.id,
          decisionDigest: accepted.prd_approval.digest,
        },
      });
      return this.verifyMutation(command.signal, async () => {
        requireCurve(response.status === 201 || response.status === 200);
        const data = await decodeLocalPlanRevision(response.data, scope, accepted);
        requireCurve(
          data.version === sourceVersion + 1 &&
            data.initiative_version === command.expectedVersion &&
            data.original.size_bytes === file.size &&
            data.original.media_type === media &&
            data.original.digest === (await hash(await file.arrayBuffer()))
        );
        requireCurve(
          response.headers.location === `${path}${data.id}/` &&
            response.headers["idempotency-replayed"] === (response.status === 200 ? "true" : "false")
        );
        return {
          data,
          etag: curveExistingWorkEtag(response, `"${command.expectedVersion}"`),
          replayed: response.status === 200,
        };
      });
    });
  }
  review(
    slug: string,
    scope: CurveExistingWorkInitiativeScope,
    current: LocalPlanReviewCurrent,
    action: LocalReviewAction,
    feedback: string | null,
    options: CurveExistingWorkMutation
  ) {
    return this.safely(async () => {
      const approval = await decodeLocalPlanApproval(current, scope);
      requireCurve(current.revision && current.revision_is_current && current.available_actions.includes(action));
      const plan = await decodeLocalPlanRevision(current.revision, scope, approval);
      const command = curveExistingWorkMutation(options);
      requireCurve(["SUBMIT", "APPROVE", "REQUEST_CHANGES"].includes(action));
      const subject =
        current.submission === null ? null : await decodeLocalPlanSubmission(current.submission, scope, plan, approval);
      requireCurve(action === "SUBMIT" ? subject === null : subject !== null);
      if (action === "REQUEST_CHANGES")
        requireCurve(
          typeof feedback === "string" &&
            feedback.trim().length > 0 &&
            !feedback.includes("\u0000") &&
            new TextEncoder().encode(feedback).length <= 16384 &&
            new TextDecoder("utf-8", { fatal: true }).decode(new TextEncoder().encode(feedback)) === feedback
        );
      else requireCurve(feedback === null);
      const path = `${root(slug, scope)}review/`;
      const response = await this.mutate(
        `${path}commands/`,
        {
          action,
          plan_revision_id: plan.id,
          plan_revision_digest: plan.digest,
          ...pins(approval),
          ...(subject ? { submission_id: subject.id, submission_digest: subject.digest } : {}),
          ...(action === "REQUEST_CHANGES" ? { feedback } : {}),
        },
        command,
        `"${command.expectedVersion}"`
      );
      return this.verifyMutation(command.signal, async () => {
        requireCurve(response.status === 201 || response.status === 200);
        const data =
          action === "SUBMIT"
            ? await decodeLocalPlanSubmission(response.data, scope, plan, approval)
            : await decodeLocalPlanDecision(response.data, scope, plan, subject!, approval);
        requireCurve(data.initiative_version === command.expectedVersion);
        if (action !== "SUBMIT")
          requireCurve((data as LocalPlanDecision).state === (action === "APPROVE" ? "APPROVED" : "CHANGES_REQUESTED"));
        if (action === "REQUEST_CHANGES") {
          const bytes = new TextEncoder().encode(feedback!);
          const ref = (data as LocalPlanDecision).feedback;
          requireCurve(ref && ref.size_bytes === bytes.length && ref.digest === (await hash(bytes.buffer)));
        }
        requireCurve(
          response.headers.location === `${path}${action === "SUBMIT" ? "submissions" : "decisions"}/${data.id}/` &&
            response.headers["idempotency-replayed"] === (response.status === 200 ? "true" : "false")
        );
        requireCurve(typeof response.headers.etag === "string" && /^"[1-9][0-9]*"$/.test(response.headers.etag));
        const etag = curveExistingWorkEtag(response, response.headers.etag);
        const version = Number(etag.slice(1, -1));
        requireCurve(
          isCurveVersion(version) &&
            (response.status === 201 ? version === command.expectedVersion : version >= command.expectedVersion)
        );
        return { data, initiativeVersion: version, etag, replayed: response.status === 200 };
      });
    });
  }
  private async content(path: string, ref: LocalPlanReference, signal?: AbortSignal) {
    const response = await this.get(path, {
      signal,
      timeout: this.requestTimeoutMs,
      responseType: "arraybuffer",
      headers: { "Cache-Control": "no-store" },
    });
    requireCurve(
      response.status === 200 &&
        response.data instanceof ArrayBuffer &&
        response.data.byteLength === ref.size_bytes &&
        (await hash(response.data)) === ref.digest
    );
    this.checkCancellation(signal);
    return response.data as ArrayBuffer;
  }
  retrieveContent(
    slug: string,
    scope: CurveExistingWorkInitiativeScope,
    plan: LocalPlanRevision,
    approval: LocalPlanApproval,
    signal?: AbortSignal
  ): Promise<Blob> {
    return this.safely(async () => {
      const revision = await decodeLocalPlanRevision(plan, scope, approval);
      const bytes = await this.content(
        `${root(slug, scope)}revisions/${curveExistingWorkId(revision.id)}/content/`,
        revision.original,
        signal
      );
      return new Blob([bytes], {
        type: revision.original.media_type === "application/pdf" ? "application/pdf" : "text/plain;charset=utf-8",
      });
    });
  }
  retrieveFeedback(
    slug: string,
    scope: CurveExistingWorkInitiativeScope,
    current: LocalPlanReviewCurrent,
    signal?: AbortSignal
  ): Promise<string> {
    return this.safely(async () => {
      requireCurve(current.revision && current.submission && current.decision);
      const decision = await decodeLocalPlanDecision(
        current.decision,
        scope,
        current.revision,
        current.submission,
        current.revision_approval ?? current
      );
      requireCurve(decision.feedback);
      const bytes = await this.content(
        `${root(slug, scope)}review/decisions/${curveExistingWorkId(decision.id)}/feedback/`,
        decision.feedback,
        signal
      );
      return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    });
  }
}
