/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { useEffect, useId, useState } from "react";
import { CheckCircle2, Clock3, FileText, Info, MessageSquare, RefreshCw, ShieldCheck, UserRound } from "lucide-react";
import type { ICurveInitiative, ICurvePrdReviewContext } from "@plane/types";
// oxlint-disable-next-line import/no-unassigned-import -- Load the scoped review styles.
import "./prd-review-panel.css";
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
  const titleId = useId();
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
  const review =
    decision?.state === "APPROVED"
      ? {
          title: "Product approved",
          description: "Approval is recorded for this submitted PRD version.",
          tone: "approved",
          Icon: CheckCircle2,
        }
      : decision?.state === "CHANGES_REQUESTED"
        ? {
            title: "Changes requested",
            description: "Update the PRD using the Product reviewer’s feedback, then submit a new version.",
            tone: "changes",
            Icon: MessageSquare,
          }
        : decision?.state === "REJECTED"
          ? {
              title: "PRD rejected",
              description: "A rejection is recorded for this submitted PRD version.",
              tone: "changes",
              Icon: MessageSquare,
            }
          : context?.decision.availability === "UNAVAILABLE" || context?.checkpoint.availability === "UNAVAILABLE"
            ? {
                title: "Review status unavailable",
                description: "Refresh to check the decision on this PRD.",
                tone: "neutral",
                Icon: Info,
              }
            : checkpoint
              ? {
                  title: "Awaiting Product review",
                  description: "Product reviews the requirements and intended outcome.",
                  tone: "pending",
                  Icon: Clock3,
                }
              : {
                  title: "Prepare the PRD",
                  description: "Submit the requirements document to begin Product review.",
                  tone: "neutral",
                  Icon: FileText,
                };
  const StatusIcon = review.Icon;
  return (
    <section className="curve-prd-review" aria-labelledby={titleId} aria-busy={view.status === "loading"}>
      <div className="curve-prd-review__heading">
        <h3 id={titleId}>Product requirements</h3>
        <button
          type="button"
          className="curve-prd-review__refresh"
          disabled={view.status === "loading"}
          onClick={() => setRevision((value) => value + 1)}
          aria-label="Refresh PRD context"
        >
          <RefreshCw size={16} aria-hidden="true" /> Refresh
        </button>
      </div>
      {view.status === "loading" && (
        <div className="curve-prd-review__empty" role="status">
          <FileText size={30} aria-hidden="true" />
          <h4>Checking your PRD…</h4>
          <p>Loading the current document and Product review status.</p>
        </div>
      )}
      {view.status === "unavailable" && (
        <div className="curve-prd-review__empty" role="status">
          <Info size={30} aria-hidden="true" />
          <h4>PRD context unavailable</h4>
          <p>We couldn’t verify access to the current document. Refresh to try again.</p>
        </div>
      )}
      {context && (
        <div className="curve-prd-review__layout">
          <div className="curve-prd-review__document">
            <div className="curve-prd-review__toolbar">
              <span className="curve-prd-review__file-icon">
                <FileText size={22} aria-hidden="true" />
              </span>
              <div>
                <h4>Requirements document</h4>
                <p>
                  {checkpoint
                    ? `Submitted ${new Date(checkpoint.recorded_at).toLocaleDateString()}`
                    : context.checkpoint.availability === "ABSENT"
                      ? "Ready when you are"
                      : "Submission status unavailable"}
                </p>
              </div>
              {checkpoint && <span className="curve-prd-review__version">v{checkpoint.checkpoint_number}</span>}
            </div>
            <div className="curve-prd-review__document-body">
              <h4>
                {checkpoint
                  ? "Submitted PRD"
                  : context.checkpoint.availability === "ABSENT"
                    ? "Add your requirements"
                    : "Document unavailable"}
              </h4>
              <p>
                {checkpoint
                  ? "This saved version is the document covered by the Product review."
                  : unavailable(context.checkpoint.availability, "No submitted checkpoint recorded")}
              </p>
              {checkpoint && (
                <p className="curve-prd-review__document-record">
                  <ShieldCheck size={18} aria-hidden="true" />
                  Checkpoint {checkpoint.checkpoint_number} · provider version {checkpoint.provider_version}
                </p>
              )}
              <div className="curve-prd-review__notice">
                <Info size={18} aria-hidden="true" />
                <p>Document content and private reviewer feedback require separate access.</p>
              </div>
              <details className="curve-prd-review__details">
                <summary>Version and evidence details</summary>
                <dl>
                  <div>
                    <dt>Initiative version</dt>
                    <dd>{context.initiative_version}</dd>
                  </div>
                  <div>
                    <dt>Linked document</dt>
                    <dd>
                      {context.binding.metadata
                        ? label(context.binding.metadata.synchronization_status)
                        : unavailable(context.binding.availability, "No binding recorded")}
                    </dd>
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
                </dl>
                <h5>Readiness for a new submission</h5>
                {readiness && (
                  <p>
                    Original assessment: {label(readiness.status)} · {new Date(readiness.checked_at).toLocaleString()}
                  </p>
                )}
                <p>
                  {readiness
                    ? readiness.ready_for_submission
                      ? "The exact current report is ready. This is not an approval."
                      : readiness.applicability !== "CURRENT"
                        ? `Assessment ${label(readiness.applicability)}. This does not invalidate review of an existing immutable checkpoint.`
                        : "The current assessment is blocked."
                    : unavailable(context.readiness.availability, "No readiness report recorded")}
                </p>
                {readiness && readiness.reasons.length > 0 && (
                  <ul>
                    {readiness.reasons.map((reason) => (
                      <li key={reason}>{label(reason.replace(":", ": "))}</li>
                    ))}
                  </ul>
                )}
                <p>
                  Checked {new Date(context.observed_at).toLocaleString()}. Access is checked again when this view
                  refreshes.
                </p>
              </details>
            </div>
          </div>
          <aside
            className={`curve-prd-review__reviewer curve-prd-review__reviewer--${review.tone}`}
            aria-label="Product review status"
          >
            <StatusIcon className="curve-prd-review__status-icon" size={28} aria-hidden="true" />
            <h4>{review.title}</h4>
            <p>{review.description}</p>
            <div className="curve-prd-review__person">
              <span className="curve-prd-review__avatar">
                <UserRound size={20} aria-hidden="true" />
              </span>
              <div>
                <strong>
                  {context.reviewer.display_name ?? "Reviewer unavailable"}
                  {context.reviewer.requesting_human_is_reviewer ? " · you" : ""}
                </strong>
                <span>Product reviewer</span>
              </div>
            </div>
            {context.reviewer.validity !== "VALID" && (
              <p className="curve-prd-review__warning">
                {context.reviewer.validity === "INVALID"
                  ? "The reviewer assignment needs attention."
                  : "The current reviewer could not be verified."}
              </p>
            )}
            {context.binding.metadata && context.binding.metadata.synchronization_status !== "CURRENT" && (
              <p className="curve-prd-review__warning">
                The linked document needs a current check. The decision shown applies to the saved version above.
              </p>
            )}
            <p className="curve-prd-review__decision">
              {decision
                ? `Decision: ${label(decision.state)}`
                : unavailable(context.decision.availability, "No decision recorded")}
            </p>
            <div className="curve-prd-review__notice">
              <Info size={18} aria-hidden="true" />
              <p>Review actions are currently unavailable. Refresh to check for updates.</p>
            </div>
            <details className="curve-prd-review__details">
              <summary>What is needed for PRD review?</summary>
              <p>A submitted document, accessible supporting evidence and the assigned Product reviewer.</p>
            </details>
          </aside>
        </div>
      )}
    </section>
  );
}
