// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import { useEffect, useId, useRef, useState } from "react";
import { CheckCircle2, Clock3, FileText, MessageSquare } from "lucide-react";
import type { CurveExistingWorkInitiativeScope } from "@plane/types";
import type { LocalPlanReviewCurrent, LocalReviewAction } from "@plane/services";
import localPlan from "@/services/curve-local-plan.service";

import type { DocumentApprovalStatus } from "./document-review-stages";

type Props = {
  workspaceSlug: string;
  scope: CurveExistingWorkInitiativeScope;
  revision: number;
  sourceId?: string;
  documentReady: boolean;
  disabled: boolean;
  onBusy: (busy: boolean) => void;
  onSaved: () => void;
  onStatus?: (status: DocumentApprovalStatus) => void;
};
type Pending = { current: LocalPlanReviewCurrent; action: LocalReviewAction; feedback: string | null; key: string };
export function LocalPlanReviewActions({
  workspaceSlug,
  scope,
  revision,
  sourceId,
  documentReady,
  disabled,
  onBusy,
  onSaved,
  onStatus,
}: Props) {
  const feedbackId = useId();
  const [current, setCurrent] = useState<LocalPlanReviewCurrent | null>(null);
  const [note, setNote] = useState("");
  const [savedNote, setSavedNote] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const pending = useRef<Pending | null>(null);
  const mutation = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      mutation.current?.abort();
      pending.current = null;
    };
  }, []);
  const feedbackInput = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    if (editing) feedbackInput.current?.focus();
  }, [editing]);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setCurrent(null);
    onStatus?.("LOADING");
    setSavedNote("");
    setError("");
    void (async () => {
      try {
        const data = await localPlan.retrieveReview(workspaceSlug, scope, controller.signal);
        if (!active) return;
        setCurrent(data);
        onStatus?.(
          !data.revision
            ? "EMPTY"
            : !data.revision_is_current
              ? "UPDATING"
              : !data.submission
                ? "READY"
                : data.decision?.state === "APPROVED"
                  ? "APPROVED"
                  : data.decision?.state === "CHANGES_REQUESTED"
                    ? "CHANGES"
                    : "REVIEW"
        );
        if (data.revision_is_current && data.decision?.feedback && data.submission) {
          const text = await localPlan.retrieveFeedback(workspaceSlug, scope, data, controller.signal);
          if (active) setSavedNote(text);
        }
      } catch {
        if (active) {
          setError("Review details couldn’t be loaded. Refresh to try again.");
          onStatus?.("UNAVAILABLE");
        }
      }
    })();
    return () => {
      active = false;
      controller.abort();
    };
    // Parent identity key scopes private data; revision refreshes the saved state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revision]);
  async function send(command: Pending) {
    if (mutation.current || !command.current.revision) return;
    const controller = new AbortController();
    mutation.current = controller;
    setBusy(true);
    onBusy(true);
    setMessage("Saving your review…");
    try {
      await localPlan.review(workspaceSlug, scope, command.current, command.action, command.feedback, {
        expectedVersion: command.current.initiative_version,
        idempotencyKey: command.key,
        signal: controller.signal,
      });
      if (!mounted.current) return;
      pending.current = null;
      setUncertain(false);
      setEditing(false);
      setNote("");
      setMessage(
        command.action === "SUBMIT"
          ? "Sent for Technical review."
          : command.action === "APPROVE"
            ? "Plan approved. Both document reviews are complete."
            : "Feedback saved. The plan is ready for revision."
      );
      onSaved();
    } catch (failure) {
      if (!mounted.current) return;
      if ((failure as { code?: string }).code === "MUTATION_OUTCOME_UNKNOWN") {
        setUncertain(true);
        setMessage("We couldn’t confirm the result. Retry the same review to check whether it was saved.");
      } else {
        pending.current = null;
        setUncertain(false);
        setMessage(
          "The review could not be saved. Refresh to check the latest document and your access, then try again."
        );
        onSaved();
      }
    } finally {
      mutation.current = null;
      if (mounted.current) {
        setBusy(false);
        onBusy(pending.current !== null);
      }
    }
  }
  function act(action: LocalReviewAction) {
    if (
      !current ||
      disabled ||
      busy ||
      pending.current ||
      !documentReady ||
      current.revision?.id !== sourceId ||
      !current.available_actions.includes(action)
    )
      return;
    if (action === "REQUEST_CHANGES" && (!note.trim() || new TextEncoder().encode(note).length > 16384)) return;
    const command = { current, action, feedback: action === "REQUEST_CHANGES" ? note : null, key: crypto.randomUUID() };
    pending.current = command;
    void send(command);
  }
  const outdated = !!current?.revision && !current.revision_is_current;
  const approved = current?.revision_is_current && current.decision?.state === "APPROVED";
  const returned = current?.revision_is_current && current.decision?.state === "CHANGES_REQUESTED";
  const waiting = current?.revision_is_current && !!current.submission && !current.decision;
  const locked = disabled || busy || uncertain || !documentReady || current?.revision?.id !== sourceId || !!error;
  const Icon = approved ? CheckCircle2 : returned ? MessageSquare : waiting ? Clock3 : FileText;
  return (
    <aside className="curve-prd-review__reviewer" aria-label="Technical review status" aria-busy={busy}>
      <Icon
        size={28}
        className={approved ? "curve-local-review__approved" : "curve-local-review__icon"}
        aria-hidden="true"
      />
      <h4>
        {!current
          ? error
            ? "Review status unavailable"
            : "Checking review status…"
          : outdated
            ? "Update the plan"
            : approved
              ? "Technical approved"
              : returned
                ? "Changes requested"
                : waiting
                  ? "In Technical review"
                  : current?.revision
                    ? "Ready for Technical review"
                    : "Prepare the plan"}
      </h4>
      <p>
        {!current
          ? "Current review details will appear here."
          : outdated
            ? "Product approved a new PRD. Upload a plan for those requirements, then send it for Technical review. Previous reviews stay in history."
            : approved
              ? "Your plan is approved. Both document reviews are complete."
              : returned
                ? "Update the document using the feedback, then send it for review again."
                : waiting
                  ? "The assigned Technical reviewer can approve this document or request changes."
                  : current?.revision
                    ? "Send this version to the assigned Technical reviewer."
                    : "Upload your implementation plan to get started."}
      </p>
      {savedNote && (
        <div className="curve-local-review__feedback">
          <h5>Technical feedback</h5>
          <p>{savedNote}</p>
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      {current?.available_actions.includes("SUBMIT") && (
        <button className="curve-local-review__primary" type="button" disabled={locked} onClick={() => act("SUBMIT")}>
          Send for Technical review
        </button>
      )}
      {current?.available_actions.includes("APPROVE") && !editing && (
        <button className="curve-local-review__primary" type="button" disabled={locked} onClick={() => act("APPROVE")}>
          Approve plan
        </button>
      )}
      {current?.available_actions.includes("REQUEST_CHANGES") && !editing && (
        <button
          className="curve-local-review__secondary"
          type="button"
          disabled={locked}
          onClick={() => setEditing(true)}
        >
          Request changes
        </button>
      )}
      {editing && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            act("REQUEST_CHANGES");
          }}
        >
          <label htmlFor={feedbackId}>What needs to change?</label>
          <textarea
            id={feedbackId}
            value={note}
            required
            disabled={busy || uncertain}
            onChange={(event) => setNote(event.target.value)}
            rows={5}
            ref={feedbackInput}
          />
          <p>Describe the changes needed before approval.</p>
          {new TextEncoder().encode(note).length > 16384 && <p role="alert">Keep your feedback under 16 KB.</p>}
          <button
            className="curve-local-review__primary"
            type="submit"
            disabled={locked || !note.trim() || new TextEncoder().encode(note).length > 16384}
          >
            Send feedback
          </button>
          <button
            className="curve-local-review__secondary"
            type="button"
            disabled={busy || uncertain}
            onClick={() => setEditing(false)}
          >
            Cancel
          </button>
        </form>
      )}
      {message && <p role="status">{message}</p>}
      {uncertain && (
        <button
          className="curve-local-review__primary"
          type="button"
          disabled={busy}
          onClick={() => {
            if (pending.current) void send(pending.current);
          }}
        >
          Retry same review
        </button>
      )}
    </aside>
  );
}
