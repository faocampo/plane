// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import { useEffect, useId, useRef, useState } from "react";
import { FileText, RefreshCw, Upload } from "lucide-react";
import type { ICurveInitiative } from "@plane/types";
import type { CurveLocalPrdCurrent } from "@plane/services";
import localPrd from "@/services/curve-local-prd.service";
// oxlint-disable-next-line import/no-unassigned-import -- Shared approved document surface styles.
import "./prd-review-panel.css";
// oxlint-disable-next-line import/no-unassigned-import -- Local document preview and upload states.
import "./local-prd-review-panel.css";

import { LocalPrdReviewActions } from "./local-prd-review-actions";

import { LocalDocumentText } from "./local-document-text";

import type { DocumentApprovalStatus } from "./document-review-stages";

type Props = {
  workspaceSlug: string;
  initiative: ICurveInitiative;
  viewerId?: string;
  onReviewSaved?: () => void;
  onStatus?: (status: DocumentApprovalStatus) => void;
  onAccessFailure?: (error: unknown) => void;
};
type Pending = { file: File; expectedVersion: number; sourceVersion: number; idempotencyKey: string };
type DocumentView = { text: string } | { url: string };
/** Remounting on identity/version changes clears private content and in-memory commands. */
export function LocalPrdReviewPanel(props: Props) {
  const { initiative, workspaceSlug, viewerId } = props;
  return (
    <LocalPrdReview
      key={`${workspaceSlug}:${initiative.workspace_id}:${initiative.product_id}:${initiative.id}:${initiative.version}:${viewerId}`}
      {...props}
    />
  );
}
function LocalPrdReview({ workspaceSlug, initiative, viewerId, onReviewSaved, onStatus, onAccessFailure }: Props) {
  const heading = useId();
  const inputId = useId();
  const hintId = useId();
  const [revision, refresh] = useState(0);
  const [current, setCurrent] = useState<CurveLocalPrdCurrent | null>(null);
  const [documentView, setDocumentView] = useState<DocumentView | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [readError, setReadError] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const pending = useRef<Pending | null>(null);
  const mutation = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const scope = { workspaceId: initiative.workspace_id, productId: initiative.product_id, initiativeId: initiative.id };
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      mutation.current?.abort();
      pending.current = null;
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    let objectUrl: string | undefined;
    setLoading(true);
    setCurrent(null);
    setDocumentView(null);
    setReadError("");
    if (!viewerId) {
      setLoading(false);
      setReadError("Sign in to view this document.");
      return () => controller.abort();
    }
    void (async () => {
      try {
        const data = await localPrd.retrieveCurrent(workspaceSlug, scope, controller.signal);
        if (!active) return;
        setCurrent(data);
        if (data.source) {
          const blob = await localPrd.retrieveContent(workspaceSlug, scope, data.source, controller.signal);
          if (!active) return;
          if (data.source.original.media_type === "application/pdf") {
            objectUrl = URL.createObjectURL(blob);
            setDocumentView({ url: objectUrl });
          } else {
            const text = await blob.text();
            if (active) setDocumentView({ text });
          }
        }
      } catch (error) {
        if (active) {
          setCurrent(null);
          setDocumentView(null);
          setReadError("We couldn’t load the current document. Refresh to check your access and try again.");
          onAccessFailure?.(error);
        }
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
    // The outer component keys every identity and Initiative version; revision is the explicit read generation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revision]);
  useEffect(() => {
    const onFocus = () => {
      const focused = document.activeElement;
      if (focused instanceof HTMLInputElement && focused.type === "file") return;
      if (!mutation.current) refresh((value) => value + 1);
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") onFocus();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);
  async function send(command: Pending) {
    if (mutation.current) return;
    const controller = new AbortController();
    mutation.current = controller;
    setBusy(true);
    setMessage("Uploading your PRD…");
    try {
      const result = await localPrd.upload(workspaceSlug, scope, command.file, command.sourceVersion, {
        expectedVersion: command.expectedVersion,
        idempotencyKey: command.idempotencyKey,
        signal: controller.signal,
      });
      if (!mounted.current) return;
      pending.current = null;
      setUncertain(false);
      setMessage(`PRD version ${result.data.version} saved.`);
      refresh((value) => value + 1);
    } catch (error) {
      if (!mounted.current) return;
      onAccessFailure?.(error);
      const code = (error as { code?: string }).code;
      if (code === "MUTATION_OUTCOME_UNKNOWN") {
        setUncertain(true);
        setMessage(
          "The connection ended before we could confirm your upload. Retry the same upload to confirm its result."
        );
      } else {
        pending.current = null;
        setUncertain(false);
        setMessage(
          code === "CONFLICT"
            ? "The document changed. Refresh before choosing your file again."
            : code === "INVALID"
              ? "Choose a non-empty PDF, Markdown or text file up to 10 MB."
              : "Your upload could not be accepted. Refresh to check your access, then try again."
        );
        refresh((value) => value + 1);
      }
    } finally {
      mutation.current = null;
      if (mounted.current) setBusy(false);
    }
  }
  function choose(file?: File) {
    if (!file || busy || pending.current || !current?.upload_available) return;
    if (!/\.(pdf|md|txt)$/i.test(file.name) || file.size === 0 || file.size > 10 * 1024 * 1024) {
      setMessage("Choose a non-empty PDF, Markdown or text file up to 10 MB.");
      return;
    }
    const command = {
      file,
      expectedVersion: current.initiative_version,
      sourceVersion: current.source?.version ?? 0,
      idempotencyKey: globalThis.crypto.randomUUID(),
    };
    pending.current = command;
    void send(command);
  }
  return (
    <section className="curve-prd-review curve-local-prd" aria-labelledby={heading} aria-busy={loading || busy}>
      <div className="curve-prd-review__heading">
        <h3 id={heading}>Product requirements</h3>
        <button
          type="button"
          className="curve-prd-review__refresh"
          disabled={busy || loading}
          onClick={() => refresh((value) => value + 1)}
        >
          <RefreshCw size={16} aria-hidden="true" /> Refresh
        </button>
      </div>
      <div className="curve-prd-review__layout">
        <div className="curve-prd-review__document">
          <div className="curve-prd-review__toolbar">
            <span className="curve-prd-review__file-icon">
              <FileText size={22} aria-hidden="true" />
            </span>
            <div>
              <h4>Requirements document</h4>
              <p>
                {current?.source
                  ? `Uploaded ${new Date(current.source.uploaded_at).toLocaleDateString()}`
                  : loading
                    ? "Checking document…"
                    : readError
                      ? "Document unavailable"
                      : "Start with your PRD"}
              </p>
            </div>
            {current?.source && <span className="curve-prd-review__version">v{current.source.version}</span>}
          </div>
          <div className="curve-prd-review__document-body">
            {loading && <p role="status">Loading your document…</p>}
            {readError && <p role="status">{readError}</p>}
            {!loading && !readError && !current?.source && (
              <div className="curve-local-prd__empty">
                <Upload size={32} aria-hidden="true" />
                <h4>Add your requirements</h4>
                <p>Upload the document that explains what you want to build and why.</p>
              </div>
            )}
            {documentView &&
              ("text" in documentView ? (
                <LocalDocumentText
                  text={documentView.text}
                  mediaType={current?.source?.original.media_type}
                  label="PRD document"
                />
              ) : (
                <>
                  <iframe className="curve-local-prd__pdf" title="PRD document" src={documentView.url} sandbox="" />
                  <a className="curve-prd-review__refresh" href={documentView.url} download="requirements.pdf">
                    Download PDF
                  </a>
                </>
              ))}
            {current?.upload_available && (
              <div className="curve-local-prd__upload">
                <label htmlFor={inputId}>{current.source ? "Replace PRD" : "Upload PRD"}</label>
                <input
                  id={inputId}
                  type="file"
                  accept=".pdf,.md,.txt"
                  aria-describedby={hintId}
                  disabled={busy || loading || uncertain}
                  onChange={(event) => {
                    choose(event.target.files?.[0]);
                    event.target.value = "";
                  }}
                />
                <p id={hintId}>PDF, Markdown or text · up to 10 MB. Selecting a file uploads it immediately.</p>
              </div>
            )}
          </div>
        </div>
        {viewerId && (
          <LocalPrdReviewActions
            workspaceSlug={workspaceSlug}
            scope={scope}
            revision={revision}
            sourceId={current?.source?.id}
            documentReady={!!documentView && !loading && !readError}
            disabled={busy || loading || uncertain}
            onBusy={setBusy}
            onStatus={onStatus}
            onAccessFailure={onAccessFailure}
            onSaved={() => {
              refresh((value) => value + 1);
              onReviewSaved?.();
            }}
          />
        )}
      </div>
      {message && (
        <p className="curve-local-prd__message" role="status">
          {message}
        </p>
      )}
      {uncertain && (
        <button
          className="curve-prd-review__refresh"
          type="button"
          disabled={busy}
          onClick={() => {
            if (pending.current) void send(pending.current);
          }}
        >
          Retry same upload
        </button>
      )}
    </section>
  );
}
