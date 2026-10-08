/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { useEffect, useState } from "react";
import type { ICurveInitiative, ICurvePrdReviewContext } from "@plane/types";
import { Button } from "@makeplane/propel/components/button";
import curveService from "@/services/curve.service";

type View =
  | { key: string; status: "loading" | "unavailable" }
  | { key: string; status: "ready"; data: ICurvePrdReviewContext };
const unavailable = (availability: string, absent: string) =>
  availability === "ABSENT" ? absent : "Unavailable for this view";
const label = (value: string) => value.toLowerCase().split("_").join(" ");

export function PrdReviewPanel({
  workspaceSlug,
  initiative,
  viewerId,
}: {
  workspaceSlug: string;
  initiative: ICurveInitiative;
  viewerId?: string;
}) {
  const [revision, setRevision] = useState(0);
  const key = `${viewerId ?? "signed-out"}:${workspaceSlug}:${initiative.workspace_id}:${initiative.id}:${initiative.version}:${revision}`;
  const [result, setResult] = useState<View>({ key, status: "loading" });
  const view: View = result.key === key ? result : { key, status: "loading" };
  useEffect(() => {
    if (!viewerId) {
      setResult({ key, status: "unavailable" });
      return;
    }
    let active = true;
    const controller = new AbortController();
    setResult({ key, status: "loading" });
    void curveService
      .retrievePrdReviewContext(
        workspaceSlug,
        {
          workspaceId: initiative.workspace_id,
          initiativeId: initiative.id,
          initiativeVersion: initiative.version,
        },
        controller.signal
      )
      .then((data) => {
        if (active) setResult({ key, status: "ready", data });
        return data;
      })
      .catch(() => {
        // Do not echo provider errors, object existence, or stale protected metadata.
        if (active) setResult({ key, status: "unavailable" });
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [key, workspaceSlug, initiative.workspace_id, initiative.id, initiative.version, revision, viewerId]);
  useEffect(() => {
    const refresh = () => setRevision((value) => value + 1);
    const visible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", visible);
    return () => {
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", visible);
    };
  }, []);
  const context = view.status === "ready" ? view.data : null;
  const checkpoint = context?.checkpoint.metadata;
  const readiness = context?.readiness.metadata;
  const decision = context?.decision.metadata;
  return (
    <section
      aria-labelledby="curve-initiative-documents-title"
      className="border-t border-subtle pt-5"
      aria-busy={view.status === "loading"}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="curve-initiative-documents-title" className="text-13 font-semibold text-primary">
          Documents and PRD review
        </h3>
        <Button
          variant="secondary"
          size="sm"
          disabled={view.status === "loading"}
          onClick={() => setRevision((value) => value + 1)}
          stretch="auto"
          label="Refresh PRD context"
        />
      </div>
      {view.status === "loading" && (
        <p role="status" className="mt-3 text-12 text-secondary">
          Checking authorized PRD metadata…
        </p>
      )}
      {view.status === "unavailable" && (
        <div role="status" className="mt-3 text-12 leading-5 text-secondary">
          <p className="font-medium">PRD context unavailable</p>
          <p>
            Access or current context could not be verified. Refresh the Initiative and retry. This does not mean that
            no PRD or decision exists.
          </p>
        </div>
      )}
      {context && (
        <div className="mt-4 space-y-4 text-12 leading-5">
          <p className="text-tertiary">
            Checked {new Date(context.observed_at).toLocaleString()}. Access is checked again when this view refreshes.
          </p>
          <dl className="grid gap-4 sm:grid-cols-2">
            <div>
              <dt className="text-secondary">Submitted PRD</dt>
              <dd className="mt-1 text-primary">
                {checkpoint
                  ? `Checkpoint ${checkpoint.checkpoint_number} · provider version ${checkpoint.provider_version}`
                  : unavailable(context.checkpoint.availability, "No submitted checkpoint recorded")}
              </dd>
            </div>
            <div>
              <dt className="text-secondary">Current Product Approver</dt>
              <dd className="mt-1 text-primary">
                {context.reviewer.display_name ?? "Reviewer unavailable"}
                {context.reviewer.validity === "INVALID" ? " · assignment needs attention" : ""}
                {context.reviewer.requesting_human_is_reviewer ? " · you" : ""}
              </dd>
            </div>
            <div>
              <dt className="text-secondary">Decision on this checkpoint</dt>
              <dd className="mt-1 text-primary">
                {decision ? label(decision.state) : unavailable(context.decision.availability, "No decision recorded")}
              </dd>
            </div>
            <div>
              <dt className="text-secondary">Linked document</dt>
              <dd className="mt-1 text-primary">
                {context.binding.metadata
                  ? label(context.binding.metadata.synchronization_status)
                  : unavailable(context.binding.availability, "No binding recorded")}
              </dd>
            </div>
          </dl>
          <div>
            <h4 className="font-semibold text-primary">Readiness for a new submission</h4>
            {readiness && (
              <p className="mt-1 text-secondary">
                Original assessment: {label(readiness.status)} · {new Date(readiness.checked_at).toLocaleString()}
              </p>
            )}
            <p className="mt-1 text-secondary">
              {readiness
                ? readiness.ready_for_submission
                  ? "The exact current report is ready. This is not an approval."
                  : readiness.applicability !== "CURRENT"
                    ? `Assessment ${label(readiness.applicability)}. This does not invalidate review of an existing immutable checkpoint.`
                    : "The current assessment is blocked."
                : unavailable(context.readiness.availability, "No readiness report recorded")}
            </p>
            {readiness && readiness.reasons.length > 0 && (
              <ul className="mt-2 list-disc space-y-1 pl-5 text-secondary">
                {readiness.reasons.slice(0, 8).map((reason) => (
                  <li key={reason}>{label(reason.replace(":", ": "))}</li>
                ))}
                {readiness.reasons.length > 8 && (
                  <li>{readiness.reasons.length - 8} additional checks are listed in evidence details.</li>
                )}
              </ul>
            )}
          </div>
          <p className="text-secondary">
            Submission and approval actions are unavailable in this read-only view. Document bodies, protected evidence
            and private review rationale require separate access.
          </p>
          <details>
            <summary className="cursor-pointer rounded-sm py-1 font-medium text-accent-primary focus-visible:outline-2">
              Version and evidence details
            </summary>
            <dl className="mt-3 space-y-3 break-all text-secondary">
              <div>
                <dt>Initiative version</dt>
                <dd>{context.initiative_version}</dd>
              </div>
              {checkpoint && (
                <>
                  <div>
                    <dt>Checkpoint reference</dt>
                    <dd>{checkpoint.id}</dd>
                  </div>
                  <div>
                    <dt>Evidence snapshot</dt>
                    <dd>{checkpoint.evidence_snapshot_id}</dd>
                  </div>
                  <div>
                    <dt>Content digest</dt>
                    <dd>{checkpoint.content_digest}</dd>
                  </div>
                </>
              )}
              {decision && (
                <>
                  <div>
                    <dt>Original decision reviewer</dt>
                    <dd>{decision.decided_by.actor_id}</dd>
                  </div>
                  <div>
                    <dt>Decision recorded</dt>
                    <dd>{new Date(decision.decided_at).toLocaleString()}</dd>
                  </div>
                </>
              )}
              {readiness && (
                <div>
                  <dt>Assessment reasons</dt>
                  <dd>{readiness.reasons.length ? readiness.reasons.join("; ") : "No structural blockers recorded"}</dd>
                </div>
              )}
            </dl>
          </details>
        </div>
      )}
      <details className="mt-3 text-12 text-secondary">
        <summary className="cursor-pointer rounded-sm py-1 font-medium text-accent-primary focus-visible:outline-2">
          What is needed for PRD review?
        </summary>
        <p className="mt-2 leading-5">
          A submitted immutable document, accessible supporting evidence and the current assigned reviewer. Readiness
          alone does not mean approval.
        </p>
      </details>
    </section>
  );
}
