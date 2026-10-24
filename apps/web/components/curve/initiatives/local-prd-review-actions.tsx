// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import { useEffect, useId, useRef, useState } from "react";
import { CheckCircle2, Clock3, FileText, MessageSquare } from "lucide-react";
import type { CurveExistingWorkInitiativeScope } from "@plane/types";
import type { CurveLocalReviewCurrent, LocalPrdReopeningCurrent, LocalReviewAction } from "@plane/services";
import localPrd from "@/services/curve-local-prd.service";

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
  onAccessFailure?: (error: unknown) => void;
};
type Pending = {
  current: CurveLocalReviewCurrent;
  action: LocalReviewAction | "REOPEN";
  feedback: string | null;
  key: string;
};
export function LocalPrdReviewActions({
  workspaceSlug,
  scope,
  revision,
  sourceId,
  documentReady,
  disabled,
  onBusy,
  onSaved,
  onStatus,
  onAccessFailure,
}: Props) {
  const feedbackId = useId();
  const [current, setCurrent] = useState<CurveLocalReviewCurrent | null>(null);
  const [reopening, setReopening] = useState<LocalPrdReopeningCurrent | null>(null);
  const [confirmReopen, setConfirmReopen] = useState(false);
  const reopenConfirmButton = useRef<HTMLButtonElement | null>(null);
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
  useEffect(() => {
    if (confirmReopen) reopenConfirmButton.current?.focus();
  }, [confirmReopen]);
  const feedbackInput = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    if (editing) feedbackInput.current?.focus();
  }, [editing]);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setCurrent(null);
    setReopening(null);
    setConfirmReopen(false);
    onStatus?.("LOADING");
    setSavedNote("");
    setError("");
    void (async () => {
      try {
        const data = await localPrd.retrieveReview(workspaceSlug, scope, controller.signal);
        const update =
          data.decision?.state === "APPROVED"
            ? await localPrd.retrieveReopening(workspaceSlug, scope, data, controller.signal)
            : null;
        if (!active) return;
        setCurrent(data);
        setReopening(update);
        onStatus?.(
          !data.source
            ? "EMPTY"
            : update?.reopening?.source_id === data.source.id
              ? "UPDATING"
              : !data.submission_is_current
                ? "READY"
                : data.decision?.state === "APPROVED"
                  ? "APPROVED"
                  : data.decision?.state === "CHANGES_REQUESTED"
                    ? "CHANGES"
                    : "REVIEW"
        );
        if (data.decision?.feedback && data.submission) {
          const text = await localPrd.retrieveFeedback(
            workspaceSlug,
            scope,
            data.decision,
            data.submission,
            controller.signal
          );
          if (active) setSavedNote(text);
        }
      } catch (failure) {
        if (active) {
          setCurrent(null);
          setSavedNote("");
          onAccessFailure?.(failure);
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
    if (mutation.current || !command.current.source) return;
    const controller = new AbortController();
    mutation.current = controller;
    setBusy(true);
    onBusy(true);
    setMessage(command.action === "REOPEN" ? "Reopening the PRD…" : "Saving your review…");
    try {
      if (command.action === "REOPEN") {
        await localPrd.reopen(workspaceSlug, scope, command.current, {
          expectedVersion: command.current.initiative_version,
          idempotencyKey: command.key,
          signal: controller.signal,
        });
      } else
        await localPrd.review(
          workspaceSlug,
          scope,
          command.current.source,
          command.action,
          command.action === "SUBMIT" ? null : command.current.submission,
          command.feedback,
          {
            expectedVersion: command.current.initiative_version,
            idempotencyKey: command.key,
            signal: controller.signal,
          }
        );
      if (!mounted.current) return;
      pending.current = null;
      setUncertain(false);
      setEditing(false);
      setConfirmReopen(false);
      setNote("");
      setMessage(
        command.action === "REOPEN"
          ? "PRD reopened. Upload the updated document to begin a new review."
          : command.action === "SUBMIT"
            ? "Sent for Product review."
            : command.action === "APPROVE"
              ? "PRD approved. The implementation plan is next."
              : "Feedback saved. The PRD is ready for revision."
      );
      onSaved();
    } catch (failure) {
      if (!mounted.current) return;
      onAccessFailure?.(failure);
      if ((failure as { code?: string }).code === "MUTATION_OUTCOME_UNKNOWN") {
        setUncertain(true);
        setMessage(
          command.action === "REOPEN"
            ? "We couldn’t confirm whether the PRD reopened. Retry to check the same request."
            : "We couldn’t confirm the result. Retry the same review to check whether it was saved."
        );
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
  function act(action: LocalReviewAction | "REOPEN") {
    if (
      !current ||
      disabled ||
      busy ||
      pending.current ||
      !documentReady ||
      current.source?.id !== sourceId ||
      (action === "REOPEN" ? !reopening?.can_reopen : !current.available_actions.includes(action))
    )
      return;
    if (action === "REQUEST_CHANGES" && (!note.trim() || new TextEncoder().encode(note).length > 16384)) return;
    const command = { current, action, feedback: action === "REQUEST_CHANGES" ? note : null, key: crypto.randomUUID() };
    pending.current = command;
    void send(command);
  }
  const needsReplacement = !!reopening?.reopening && reopening.reopening.source_id === current?.source?.id;
  const approved = current?.submission_is_current && current.decision?.state === "APPROVED";
  const returned = current?.submission_is_current && current.decision?.state === "CHANGES_REQUESTED";
  const waiting = current?.initiative_state === "PRD_REVIEW";
  const locked = disabled || busy || uncertain || !documentReady || current?.source?.id !== sourceId || !!error;
  const Icon = approved ? CheckCircle2 : returned ? MessageSquare : waiting ? Clock3 : FileText;
  return (
    <aside className="curve-prd-review__reviewer" aria-label="Product review status" aria-busy={busy}>
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
          : needsReplacement
            ? "Update the PRD"
            : approved
              ? "Product approved"
              : returned
                ? "Changes requested"
                : waiting
                  ? "In Product review"
                  : current?.source
                    ? "Ready for Product review"
                    : "Prepare the PRD"}
      </h4>
      <p>
        {!current
          ? "Current review details will appear here."
          : needsReplacement
            ? "Upload an updated document, then send it to Product for a new approval. The previous approval stays in history."
            : approved
              ? "Your PRD is approved. Open the Implementation plan tab to see its Technical review status."
              : returned
                ? "Update the document using the feedback, then send it for review again."
                : waiting
                  ? "The assigned Product reviewer can approve this document or request changes."
                  : current?.source
                    ? "Send this version to the assigned Product reviewer."
                    : "Upload your requirements to get started."}
      </p>
      {approved && reopening?.can_reopen && !confirmReopen && (
        <button
          className="curve-local-review__secondary"
          type="button"
          disabled={locked}
          onClick={() => setConfirmReopen(true)}
        >
          Update PRD
        </button>
      )}
      {confirmReopen && (
        <div className="curve-local-review__feedback">
          <h5>Start a new document review?</h5>
          <p>
            The updated PRD will need Product approval, followed by a fresh Technical review of the implementation plan.
            Your previous reviews stay in history.
          </p>
          <button
            className="curve-local-review__primary"
            type="button"
            ref={reopenConfirmButton}
            disabled={locked}
            onClick={() => act("REOPEN")}
          >
            Reopen PRD
          </button>
          <button
            className="curve-local-review__secondary"
            type="button"
            disabled={busy || uncertain}
            onClick={() => setConfirmReopen(false)}
          >
            Keep current approval
          </button>
        </div>
      )}
      {savedNote && (
        <div className="curve-local-review__feedback">
          <h5>Product feedback</h5>
          <p>{savedNote}</p>
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      {current?.available_actions.includes("SUBMIT") && (
        <button className="curve-local-review__primary" type="button" disabled={locked} onClick={() => act("SUBMIT")}>
          Send for Product review
        </button>
      )}
      {current?.available_actions.includes("APPROVE") && !editing && (
        <button className="curve-local-review__primary" type="button" disabled={locked} onClick={() => act("APPROVE")}>
          Approve PRD
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
          {pending.current?.action === "REOPEN" ? "Retry reopening" : "Retry same review"}
        </button>
      )}
    </aside>
  );
}
