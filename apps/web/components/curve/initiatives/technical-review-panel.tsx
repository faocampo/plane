// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { CheckCircle2, FileText, MessageSquare, RefreshCw } from "lucide-react";
import { ManualGate2ServiceV3, ManualPlanDraftServiceV3, ManualPlanClientError } from "@plane/services";
import type {
  ManualGate2ApiV3,
  ManualGate2ActionV3,
  ManualGate2CommandV3,
  ManualGate2MaterialV3,
  ManualGate2StatusV3,
  ManualPlanApiV3,
  ManualPlanPreparationV3,
  ManualPlanTargetV3,
} from "@plane/services";
import { MaterialContent, materialLabel, taskLabel } from "./manual-plan-content";
import { ManualPlanPanelV3 } from "./manual-plan-panel-v3";
// oxlint-disable-next-line import/no-unassigned-import -- Load the scoped review styles.
import "./prd-review-panel.css";
// oxlint-disable-next-line import/no-unassigned-import -- Load the scoped review styles.
import "./technical-review-panel.css";

const service = new ManualGate2ServiceV3();
const draftService = new ManualPlanDraftServiceV3();
type Props = {
  target: ManualPlanTargetV3;
  viewerId?: string;
  initiativeVersion: number;
  reviewerName?: string;
  api?: ManualGate2ApiV3;
  drafts?: ManualPlanApiV3;
};
type Ready = {
  status: ManualGate2StatusV3 | null;
  preparation: ManualPlanPreparationV3 | null;
  version: number;
  materials: Record<string, ManualGate2MaterialV3>;
};
const labels: Record<ManualGate2ActionV3, string> = {
  PREPARE: "Send for Technical review",
  APPROVE: "Approve plan",
  REQUEST_CHANGES: "Request changes",
  RECONCILE: "Review reserved tasks",
  RELEASE: "Release selected tasks",
};
const states = {
  ABSENT: "Ready to send",
  PLAN_REVIEW: "Awaiting Technical approval",
  CHANGES_REQUESTED: "Changes requested",
  MANUAL_APPROVED: "Plan approved",
  RELEASED: "Tasks released",
};

export function TechnicalReviewPanel(props: Props) {
  return (
    <TechnicalReviewSession key={JSON.stringify([props.target, props.viewerId, props.initiativeVersion])} {...props} />
  );
}

function TechnicalReviewSession({
  target: source,
  viewerId,
  reviewerName,
  api = service,
  drafts = draftService,
}: Props) {
  const { workspaceSlug, workspaceId, productId, initiativeId } = source;
  const target = useMemo(
    () => ({ workspaceSlug, workspaceId, productId, initiativeId }),
    [workspaceSlug, workspaceId, productId, initiativeId]
  );
  const id = useId();
  const [ready, setReady] = useState<Ready | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [unknown, setUnknown] = useState(false);
  const [draftPending, setDraftPending] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const [action, setAction] = useState<ManualGate2ActionV3>("APPROVE");
  const [rationale, setRationale] = useState("");
  const [plan, setPlan] = useState(0);
  const [selection, setSelection] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const operation = useRef<AbortController | null>(null);
  const pending = useRef<ManualGate2CommandV3 | null>(null);
  const writing = useRef(false);
  const draftWriting = useRef(false);
  const mounted = useRef(true);
  const clear = () => {
    setReady(null);
    setSelection([]);
    setRationale("");
  };
  function refresh() {
    if (writing.current || pending.current || draftWriting.current) return;
    operation.current?.abort();
    clear();
    setLoading(true);
    setEpoch((v) => v + 1);
  }
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      operation.current?.abort();
      pending.current = null;
    };
  }, []);
  useEffect(() => {
    clear();
    setLoading(true);
    const controller = new AbortController();
    operation.current = controller;
    if (!viewerId) {
      setLoading(false);
      return () => controller.abort();
    }
    void (async () => {
      const [preparationResult, statusResult] = await Promise.allSettled([
        api.preparation(target, controller.signal),
        api.status(target, controller.signal),
      ]);
      const preparation = preparationResult.status === "fulfilled" ? preparationResult.value : null;
      const status = statusResult.status === "fulfilled" ? statusResult.value : null;
      if (!preparation && !status) throw new Error("unavailable");
      if (preparation && status && preparation.currentVersion !== status.currentVersion) throw new Error("changed");
      const version = (status ?? preparation)!.currentVersion;
      const references = [
        ...(status
          ? [
              { ref: status.data.definition_ref, kind: "DEFINITION" as const },
              ...status.data.rationales.map((r) => ({ ref: r.reference, kind: "RATIONALE" as const })),
            ]
          : []),
        ...(preparation?.data.plans.map((p) => ({ ref: p.payload.definition_ref, kind: "DEFINITION" as const })) ?? []),
      ];
      const materials: Ready["materials"] = {};
      for (const { ref, kind } of references) {
        if (controller.signal.aborted) return;
        if (materials[ref.object_id]) {
          if (materials[ref.object_id].reference.digest !== ref.digest || materials[ref.object_id].kind !== kind)
            throw new Error("changed");
          continue;
        }
        // eslint-disable-next-line no-await-in-loop -- Validate and deduplicate each protected reference before the next read.
        const result = await api.material(target, ref, controller.signal);
        if (
          result.currentVersion !== version ||
          result.data.kind !== kind ||
          result.data.reference.object_id !== ref.object_id ||
          result.data.reference.digest !== ref.digest
        )
          throw new Error("changed");
        materials[ref.object_id] = result.data;
      }
      if (controller.signal.aborted || !mounted.current) return;
      setReady({ status: status?.data ?? null, preparation: preparation?.data ?? null, version, materials });
      setPlan(0);
      setAction(
        status?.data.allowed_actions.includes("APPROVE") ? "APPROVE" : (status?.data.allowed_actions[0] ?? "PREPARE")
      );
    })()
      .catch(() => {
        if (!controller.signal.aborted) {
          clear();
          setNotice("The plan or your access changed. Refresh to load the current review.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [api, target, viewerId, epoch]);
  useEffect(() => {
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
  const current = ready?.status;
  const prepared = ready?.preparation?.plans[plan];
  const definition =
    ready?.materials[current?.definition_ref.object_id ?? prepared?.payload.definition_ref.object_id ?? ""];
  const rationales =
    current?.rationales.filter((r) => r.intent === (action === "RELEASE" ? "RECONCILE" : action)) ?? [];
  const selectedRationale =
    rationales.find((r) => r.reference.object_id === rationale) ??
    (rationales.length === 1 ? rationales[0] : undefined);
  const evidence = ready?.materials[selectedRationale?.reference.object_id ?? ""];
  const needsClaims = action === "RECONCILE" || action === "RELEASE";
  const reconciliation = current?.current_record?.action === "RECONCILE" ? current.current_record : null;
  const eligible = !!(
    current &&
    definition &&
    current.allowed_actions.includes(action) &&
    (action === "PREPARE" || evidence) &&
    (!needsClaims || selection.length) &&
    (action !== "RELEASE" || reconciliation)
  );
  function choose(next: ManualGate2ActionV3) {
    setAction(next);
    setRationale("");
    setSelection([]);
  }
  async function submit() {
    if (writing.current || draftWriting.current || (!pending.current && !eligible)) return;
    const command: ManualGate2CommandV3 | null =
      pending.current ??
      (current && ready
        ? {
            payload: {
              schema_version: "curve.manual-gate2.command/v3-candidate",
              action,
              draft_revision_id: current.draft_revision_id,
              subject_ref: action === "PREPARE" ? null : current.subject_ref,
              rationale_ref: action === "PREPARE" ? null : selectedRationale!.reference,
              claims: needsClaims
                ? current.claims
                    .filter((c) => c.state === "ACTIVE" && selection.includes(c.claim_id))
                    .map((c) => ({ claim_id: c.claim_id, generation: c.generation }))
                : [],
              reconciliation_ref:
                action === "RELEASE" && reconciliation
                  ? { entity_id: reconciliation.id, digest: reconciliation.digest }
                  : null,
            },
            expectedVersion: ready.version,
            idempotencyKey: crypto.randomUUID(),
          }
        : null);
    if (!command) return;
    pending.current = structuredClone(command);
    writing.current = true;
    setBusy(true);
    setUnknown(false);
    clear();
    setNotice("");
    operation.current?.abort();
    const controller = new AbortController();
    operation.current = controller;
    try {
      await api.execute(target, command, controller.signal);
      if (!mounted.current) return;
      pending.current = null;
      setNotice("Your decision was recorded.");
      setEpoch((v) => v + 1);
    } catch (error) {
      if (!mounted.current) return;
      if (error instanceof ManualPlanClientError && error.code === "UNKNOWN") {
        setUnknown(true);
        setNotice("We could not confirm the result. Recover this decision before continuing.");
      } else {
        pending.current = null;
        setNotice(
          error instanceof ManualPlanClientError && error.code === "CONFLICT"
            ? "This review changed. Refresh and review the latest version."
            : "The decision is unavailable with your current access. Refresh to check again."
        );
      }
    } finally {
      writing.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  const approved = current?.state === "MANUAL_APPROVED";
  const Icon = approved ? CheckCircle2 : current?.state === "CHANGES_REQUESTED" ? MessageSquare : FileText;
  return (
    <section className="curve-prd-review curve-technical-review" aria-labelledby={id} aria-busy={loading || busy}>
      <div className="curve-prd-review__heading">
        <h3 id={id}>Implementation plan</h3>
        <button
          type="button"
          className="curve-prd-review__refresh"
          onClick={refresh}
          disabled={busy || loading || unknown || draftPending}
        >
          <RefreshCw size={16} aria-hidden="true" />
          Refresh
        </button>
      </div>
      {notice && (
        <p role="status" className="curve-prd-review__notice">
          {notice}
        </p>
      )}
      {unknown && (
        <button type="button" className="curve-technical-review__primary" disabled={busy} onClick={() => void submit()}>
          Recover decision
        </button>
      )}
      {loading || busy ? (
        <p role="status">{busy ? "Recording your decision…" : "Loading your plan…"}</p>
      ) : ready ? (
        <div className="curve-prd-review__layout">
          <article className="curve-prd-review__document">
            <div className="curve-prd-review__toolbar">
              <span className="curve-prd-review__file-icon">
                <FileText size={20} aria-hidden="true" />
              </span>
              <h4>Implementation plan</h4>
              <span className="curve-prd-review__version">Current review</span>
            </div>
            <div className="curve-prd-review__document-body">
              {definition ? (
                <MaterialContent material={definition} />
              ) : (
                <p>Your plan will appear here when it is available.</p>
              )}
              {ready.preparation && (!current || ["ABSENT", "CHANGES_REQUESTED"].includes(current.state)) && (
                <details className="curve-prd-review__details" open={!current}>
                  <summary>{current ? "Replace the plan" : "Save a plan for review"}</summary>
                  {ready.preparation.plans.length > 1 && (
                    <label>
                      Prepared plan
                      <select value={plan} disabled={draftPending} onChange={(e) => setPlan(Number(e.target.value))}>
                        {ready.preparation.plans.map((p, i) => (
                          <option key={p.payload.definition_ref.object_id} value={i}>
                            {materialLabel(ready.materials[p.payload.definition_ref.object_id]) ?? `Plan ${i + 1}`}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  {prepared && current && prepared.payload.definition_ref.digest !== current.definition_ref.digest && (
                    <MaterialContent material={ready.materials[prepared.payload.definition_ref.object_id]} />
                  )}
                  <ManualPlanPanelV3
                    api={drafts}
                    target={target}
                    viewerId={viewerId}
                    initiativeVersion={ready.version}
                    prepared={prepared ? { payload: prepared.payload, initiativeVersion: ready.version } : undefined}
                    onSaved={refresh}
                    onPendingChange={(value) => {
                      draftWriting.current = value;
                      setDraftPending(value);
                    }}
                  />
                </details>
              )}
              {current && (
                <details className="curve-prd-review__details">
                  <summary>Version and review history</summary>
                  <dl>
                    <dt>Plan revision</dt>
                    <dd>{current.draft_revision_id}</dd>
                    <dt>Current decision</dt>
                    <dd>{current.current_record?.action ? labels[current.current_record.action] : "Draft"}</dd>
                    <dt>Document fingerprint</dt>
                    <dd>{current.definition_ref.digest}</dd>
                  </dl>
                </details>
              )}
            </div>
          </article>
          <aside
            className={`curve-prd-review__reviewer ${approved ? "curve-prd-review__reviewer--approved" : current?.state === "CHANGES_REQUESTED" ? "curve-prd-review__reviewer--changes" : ""}`}
            aria-label="Technical review"
          >
            <Icon size={28} className="curve-prd-review__status-icon" aria-hidden="true" />
            <h4>{current ? states[current.state] : "Prepare your plan"}</h4>
            <p>
              {approved
                ? "Technical approval is recorded for this plan."
                : current?.state === "CHANGES_REQUESTED"
                  ? "Update the plan using the feedback, then send it for another review."
                  : "Technical reviews how the approved requirements will be delivered."}
            </p>
            <div className="curve-prd-review__person">
              <span className="curve-prd-review__avatar" aria-hidden="true">
                {reviewerName?.slice(0, 1) ?? "T"}
              </span>
              <div>
                <strong>{reviewerName ?? "Assigned Technical reviewer"}</strong>
                <span>Implementation plan approval</span>
              </div>
            </div>
            {current?.effective_hold && (
              <p className="curve-prd-review__warning">
                This Initiative is {current.effective_hold.toLowerCase()}. Task reservations remain recorded.
              </p>
            )}
            {!!current?.allowed_actions.length && (
              <>
                <div className="curve-technical-review__choices" role="group" aria-label="Decision">
                  {current.allowed_actions
                    .filter((a) => ["PREPARE", "APPROVE", "REQUEST_CHANGES"].includes(a))
                    .map((a) => (
                      <button key={a} type="button" aria-pressed={action === a} onClick={() => choose(a)}>
                        {a === "APPROVE" ? "Approve" : a === "REQUEST_CHANGES" ? "Changes needed" : "Send for review"}
                      </button>
                    ))}
                </div>
                {current.allowed_actions.some((a) => a === "RECONCILE" || a === "RELEASE") && (
                  <details className="curve-prd-review__details">
                    <summary>Manage task reservations</summary>
                    {current.allowed_actions
                      .filter((a) => a === "RECONCILE" || a === "RELEASE")
                      .map((a) => (
                        <button key={a} type="button" aria-pressed={action === a} onClick={() => choose(a)}>
                          {labels[a]}
                        </button>
                      ))}
                  </details>
                )}
                {action !== "PREPARE" && (
                  <div className="curve-technical-review__feedback">
                    <h5>{action === "REQUEST_CHANGES" ? "Feedback to the author" : "Decision note"}</h5>
                    {rationales.length > 1 && (
                      <label>
                        Choose a saved note
                        <select value={rationale} onChange={(e) => setRationale(e.target.value)}>
                          <option value="">Choose a note</option>
                          {rationales.map((r) => (
                            <option key={r.reference.object_id} value={r.reference.object_id}>
                              {materialLabel(ready.materials[r.reference.object_id]) ?? "Saved note"}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                    {evidence ? (
                      <MaterialContent material={evidence} showRationaleTitle={false} />
                    ) : (
                      <p>
                        {rationales.length
                          ? "Choose the note you want to record with this decision."
                          : "A saved decision note is needed before you can continue."}
                      </p>
                    )}
                  </div>
                )}
                {needsClaims && (
                  <fieldset>
                    <legend>Tasks to {action === "RELEASE" ? "release" : "review"}</legend>
                    {current.claims
                      .filter((c) => c.state === "ACTIVE")
                      .map((c) => (
                        <label className="curve-technical-review__task" key={c.claim_id}>
                          <input
                            type="checkbox"
                            checked={selection.includes(c.claim_id)}
                            onChange={(e) =>
                              setSelection((v) =>
                                e.target.checked ? [...v, c.claim_id] : v.filter((x) => x !== c.claim_id)
                              )
                            }
                          />
                          {taskLabel(definition ?? null, c.installation_id, c.issue_id)}
                        </label>
                      ))}
                    {action === "RELEASE" && !reconciliation && <p>Review the reserved tasks before releasing them.</p>}
                  </fieldset>
                )}
                <button
                  className="curve-technical-review__primary"
                  type="button"
                  disabled={!eligible || draftPending}
                  onClick={() => void submit()}
                >
                  {action === "APPROVE"
                    ? "Record approval"
                    : action === "REQUEST_CHANGES"
                      ? "Send change request"
                      : labels[action]}
                </button>
              </>
            )}
            {current && !current.allowed_actions.length && (
              <p>Available actions depend on your assignment and the current review status.</p>
            )}
          </aside>
        </div>
      ) : (
        !unknown && (
          <div className="curve-prd-review__empty">
            <FileText size={28} aria-hidden="true" />
            <h4>Plan review unavailable</h4>
            <p>Refresh to check the current plan and your access.</p>
          </div>
        )
      )}
    </section>
  );
}
