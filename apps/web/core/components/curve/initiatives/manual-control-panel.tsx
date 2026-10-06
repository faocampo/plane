/* eslint-disable unicorn/no-array-sort -- These are fresh arrays; keep ES2022 browser compatibility. */
import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  CircleHelp,
  FileText,
  Info,
  Loader2,
  LockKeyhole,
  MessageSquare,
  PauseCircle,
} from "lucide-react";
import { Button } from "@plane/propel/button";
import { ManualGate2Service, ManualPlanClientError, ManualPlanDraftService } from "@plane/services";
import type {
  ManualGate2Action,
  ManualGate2Api,
  ManualGate2Command,
  ManualGate2Material,
  ManualGate2Object,
  ManualGate2Status,
  ManualPlanApi,
  ManualPlanPreparation,
  ManualPlanTarget,
} from "@plane/services";
import { ManualPlanPanel } from "./manual-plan-panel";

const gateApi = new ManualGate2Service();
const draftApi = new ManualPlanDraftService();
const labels: Record<ManualGate2Action, string> = {
  PREPARE: "Send draft for review",
  APPROVE: "Approve and reserve tasks",
  REQUEST_CHANGES: "Request plan changes",
  RECONCILE: "Reconcile selected tasks",
  RELEASE: "Release reconciled tasks",
};
const states = {
  ABSENT: "Draft not submitted for review",
  PLAN_REVIEW: "Plan awaiting review",
  CHANGES_REQUESTED: "Changes requested",
  MANUAL_APPROVED: "Plan approved · tasks reserved",
  RELEASED: "Reservations released",
};
type Props = {
  target: ManualPlanTarget;
  viewerId?: string;
  initiativeVersion: number;
  api?: ManualGate2Api;
  drafts?: ManualPlanApi;
};
type Ready = { preparation: ManualPlanPreparation | null; status: ManualGate2Status | null; version: number };
const inputClass =
  "mt-1 w-full rounded-md border border-subtle bg-surface-1 px-3 py-2 text-13 text-primary focus-visible:outline-2 focus-visible:outline-accent-primary";
const focus = "focus-visible:ring-2 focus-visible:ring-accent-primary focus-visible:ring-offset-2";

/** Render only behind the independent local UI switch; every API also reauthorizes. */
export function ManualControlEntry({ state, ...props }: Props & { state: string }) {
  if (
    process.env.VITE_CURVE_MANUAL_PLAN_V2_ENABLED !== "true" ||
    !props.viewerId ||
    !["PLANNING", "PAUSED", "CANCELLED"].includes(state)
  )
    return null;
  return <ManualControlPanel {...props} />;
}

export function ManualControlPanel(props: Props) {
  const key = JSON.stringify([props.target, props.viewerId, props.initiativeVersion]);
  return <ManualControlSession key={key} {...props} />;
}
function ManualControlSession({ target: source, viewerId, api = gateApi, drafts = draftApi }: Props) {
  const { workspaceSlug, workspaceId, productId, initiativeId } = source;
  const target = useMemo(
    () => ({ workspaceSlug, workspaceId, productId, initiativeId }),
    [workspaceSlug, workspaceId, productId, initiativeId]
  );
  const id = useId();
  const [ready, setReady] = useState<Ready | null>(null);
  const [loading, setLoading] = useState(true);
  const [epoch, setEpoch] = useState(0);
  const [plan, setPlan] = useState(0);
  const [action, setAction] = useState<ManualGate2Action>("PREPARE");
  const [rationale, setRationale] = useState("");
  const [selection, setSelection] = useState<string[]>([]);
  const [definition, setDefinition] = useState<ManualGate2Material | null>(null);
  const [preparedDefinition, setPreparedDefinition] = useState<ManualGate2Material | null>(null);
  const [evidence, setEvidence] = useState<ManualGate2Material | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [unknown, setUnknown] = useState(false);
  const pending = useRef<ManualGate2Command | null>(null);
  const operation = useRef<AbortController | null>(null);
  const active = useRef(true);
  const writing = useRef(false);
  useEffect(
    () => () => {
      active.current = false;
      operation.current?.abort();
      pending.current = null;
    },
    []
  );
  function clear() {
    setReady(null);
    setDefinition(null);
    setPreparedDefinition(null);
    setEvidence(null);
    setReviewed(false);
    setSelection([]);
    setRationale("");
  }
  function refresh() {
    if (writing.current || pending.current) return;
    operation.current?.abort();
    clear();
    setLoading(true);
    setEpoch((v) => v + 1);
  }
  useEffect(() => {
    active.current = true;
    clear();
    setLoading(true);
    const controller = new AbortController();
    operation.current = controller;
    if (!viewerId) {
      setLoading(false);
      return () => controller.abort();
    }
    void Promise.allSettled([api.preparation(target, controller.signal), api.status(target, controller.signal)])
      .then(([prepared, current]) => {
        if (controller.signal.aborted || !active.current) return;
        const p = prepared.status === "fulfilled" ? prepared.value : null;
        const s = current.status === "fulfilled" ? current.value : null;
        if (!p && !s) throw new Error("unavailable");
        if (p && s && p.currentVersion !== s.currentVersion) throw new Error("conflict");
        setReady({ preparation: p?.data ?? null, status: s?.data ?? null, version: (p ?? s)!.currentVersion });
        setPlan(0);
        setAction(s?.data.allowed_actions[0] ?? "PREPARE");
        return undefined;
      })
      .catch(() => {
        if (!controller.signal.aborted) clear();
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
  const StatusIcon =
    busy || loading
      ? Loader2
      : unknown
        ? CircleHelp
        : !ready
          ? Info
          : current?.state === "MANUAL_APPROVED"
            ? LockKeyhole
            : current?.state === "RELEASED"
              ? CheckCircle2
              : current?.state === "CHANGES_REQUESTED"
                ? MessageSquare
                : FileText;
  const prepared = ready?.preparation?.plans[plan];
  const definitionRef = current?.definition_ref ?? prepared?.payload.definition_ref;
  const allowed = current?.allowed_actions ?? [];
  const rationales =
    current?.rationales.filter((r) => r.intent === (action === "RELEASE" ? "RECONCILE" : action)) ?? [];
  const rationaleRef = rationales.find((r) => r.reference.object_id === rationale)?.reference;
  const activeClaims = current?.claims.filter((c) => c.state === "ACTIVE") ?? [];
  const needsClaims = action === "RECONCILE" || action === "RELEASE";
  const reconciliation = current?.current_record?.action === "RECONCILE" ? current.current_record : null;
  const eligible = !!(
    ready &&
    current &&
    allowed.includes(action) &&
    definition &&
    reviewed &&
    (action === "PREPARE" || (rationaleRef && evidence?.reference.object_id === rationaleRef.object_id)) &&
    (!needsClaims || selection.length) &&
    (action !== "RELEASE" || reconciliation)
  );
  async function loadMaterial(ref: ManualGate2Object | undefined, kind: "DEFINITION" | "RATIONALE", preparing = false) {
    if (!ref || writing.current || pending.current || !ready) return;
    operation.current?.abort();
    const controller = new AbortController();
    operation.current = controller;
    setReviewed(false);
    if (preparing) setPreparedDefinition(null);
    else if (kind === "DEFINITION") setDefinition(null);
    else setEvidence(null);
    setBusy(true);
    setNotice("");
    try {
      const result = await api.material(target, ref, controller.signal);
      if (result.currentVersion !== ready.version || result.data.kind !== kind)
        throw new ManualPlanClientError("CONFLICT");
      if (!controller.signal.aborted && active.current) {
        if (preparing) setPreparedDefinition(result.data);
        else if (kind === "DEFINITION") setDefinition(result.data);
        else setEvidence(result.data);
      }
    } catch {
      if (!controller.signal.aborted) {
        clear();
        setNotice("The material or your access changed. Refresh before continuing.");
      }
    } finally {
      if (active.current) setBusy(false);
    }
  }
  async function submit() {
    if (writing.current || (!pending.current && !eligible)) return;
    const command =
      pending.current ??
      (current && ready
        ? {
            payload: {
              schema_version: "curve.manual-gate2.command/v2-candidate" as const,
              action,
              draft_revision_id: current.draft_revision_id,
              subject_ref: action === "PREPARE" ? null : current.subject_ref,
              rationale_ref: action === "PREPARE" ? null : rationaleRef!,
              claims: needsClaims
                ? activeClaims
                    .filter((c) => selection.includes(c.claim_id))
                    .map((c) => ({ claim_id: c.claim_id, generation: c.generation }))
                    .sort((a, b) => a.claim_id.localeCompare(b.claim_id))
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
      if (!active.current) return;
      pending.current = null;
      setNotice("Decision recorded. Checking the current plan and reservations.");
      setEpoch((v) => v + 1);
    } catch (error) {
      if (!active.current) return;
      if (error instanceof ManualPlanClientError && error.code === "UNKNOWN") {
        setUnknown(true);
        setNotice("The outcome could not be confirmed. Retry the same decision to recover its result.");
      } else {
        pending.current = null;
        setNotice(
          error instanceof ManualPlanClientError && error.code === "CONFLICT"
            ? "The plan, reservations or reconciliation changed. Refresh and review the current version."
            : "The decision is unavailable with your current access. Refresh to check again."
        );
      }
    } finally {
      writing.current = false;
      if (active.current) {
        setBusy(false);
        setLoading(false);
      }
    }
  }
  return (
    <section aria-labelledby={id} className="space-y-5 border-t border-subtle pt-5">
      <div>
        <h3 id={id} className="text-16 font-semibold text-primary">
          Manual plan
        </h3>
        <p className="mt-1 max-w-prose text-13 leading-6 text-secondary">
          Review the plan, record its decision and manage reserved tasks. Execution remains manual.
        </p>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex items-center gap-2 text-13 font-medium text-primary" role="status">
          <StatusIcon aria-hidden="true" className="size-4 shrink-0" />
          <span>
            {busy
              ? "Checking the request…"
              : loading
                ? "Checking current access…"
                : unknown
                  ? "Decision outcome not confirmed"
                  : current
                    ? states[current.state]
                    : ready
                      ? "No draft saved"
                      : "Manual plan unavailable for this view"}
          </span>
        </p>
        <Button variant="secondary" size="xl" className={focus} onClick={refresh} disabled={busy || unknown}>
          Refresh
        </Button>
      </div>
      {notice && (
        <p role="status" className="text-13 leading-6 text-secondary">
          {notice}
        </p>
      )}
      {unknown && (
        <Button size="xl" className={focus} onClick={() => void submit()} disabled={busy}>
          Retry the same decision
        </Button>
      )}
      {ready && (
        <>
          {current?.effective_hold && (
            <p className="flex items-start gap-2 rounded-md bg-warning-subtle p-3 text-13 text-primary">
              <PauseCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              <span>
                This Initiative is {current.effective_hold.toLowerCase()}. Its reservations remain in place until an
                explicit reconciled release.
              </span>
            </p>
          )}
          {ready.preparation && (
            <>
              {ready.preparation.plans.length > 1 && (
                <label className="block text-13 text-primary">
                  Prepared definition
                  <select
                    className={inputClass}
                    value={plan}
                    onChange={(e) => {
                      setPlan(Number(e.target.value));
                      setPreparedDefinition(null);
                      setReviewed(false);
                    }}
                  >
                    {ready.preparation.plans.map((p, i) => (
                      <option key={p.payload.definition_ref.object_id} value={i}>
                        Definition {i + 1}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {!prepared && (
                <p className="text-13 text-secondary">No prepared definition is available with your current access.</p>
              )}
              {prepared && prepared.payload.definition_ref.object_id !== current?.definition_ref.object_id && (
                <div>
                  <Button
                    variant="secondary"
                    size="xl"
                    className={focus}
                    disabled={busy}
                    onClick={() => void loadMaterial(prepared.payload.definition_ref, "DEFINITION", true)}
                  >
                    Read prepared definition
                  </Button>
                  {preparedDefinition && <MaterialContent material={preparedDefinition} />}
                </div>
              )}
              <ManualPlanPanel
                api={drafts}
                target={target}
                viewerId={viewerId}
                initiativeVersion={ready.version}
                prepared={prepared ? { payload: prepared.payload, initiativeVersion: ready.version } : undefined}
                onSaved={refresh}
              />
            </>
          )}
          {definitionRef && (
            <div>
              <Button
                variant="secondary"
                size="xl"
                className={focus}
                onClick={() => void loadMaterial(definitionRef, "DEFINITION")}
                disabled={busy}
              >
                Read plan definition
              </Button>
              {definition && <MaterialContent material={definition} />}
            </div>
          )}
          {current && (
            <>
              <div>
                <h4 className="text-13 font-semibold text-primary">Task reservations</h4>
                {!current.claims.length ? (
                  <p className="mt-2 text-13 text-secondary">No tasks are reserved by this plan.</p>
                ) : (
                  <ul className="mt-2 divide-y divide-subtle">
                    {current.claims.map((c, i) => (
                      <li key={c.claim_id} className="flex flex-wrap items-center gap-3 py-3 text-13 text-primary">
                        {c.state === "ACTIVE" && needsClaims && (
                          <input
                            aria-label={`Select task ${i + 1}`}
                            className={`size-5 ${focus}`}
                            type="checkbox"
                            checked={selection.includes(c.claim_id)}
                            onChange={(e) => {
                              setSelection((v) =>
                                e.target.checked ? [...v, c.claim_id] : v.filter((x) => x !== c.claim_id)
                              );
                              setReviewed(false);
                            }}
                          />
                        )}
                        <span>
                          Task {i + 1} · {c.state === "ACTIVE" ? "Reserved" : "Released"} · generation {c.generation}
                        </span>
                        <details className="min-w-0 text-secondary">
                          <summary className={`cursor-pointer py-1 ${focus}`}>Task identity</summary>
                          <span className="break-all">{c.issue_id}</span>
                        </details>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              {!!allowed.length && (
                <div className="space-y-4">
                  <label className="block text-13 font-medium text-primary">
                    Next decision
                    <select
                      className={inputClass}
                      value={action}
                      onChange={(e) => {
                        setAction(e.target.value as ManualGate2Action);
                        setRationale("");
                        setEvidence(null);
                        setReviewed(false);
                        setSelection([]);
                      }}
                    >
                      {allowed.map((a) => (
                        <option key={a} value={a}>
                          {labels[a]}
                        </option>
                      ))}
                    </select>
                  </label>
                  {action !== "PREPARE" && (
                    <div>
                      <label className="block text-13 font-medium text-primary">
                        Decision evidence
                        <select
                          className={inputClass}
                          value={rationale}
                          onChange={(e) => {
                            setRationale(e.target.value);
                            setEvidence(null);
                            setReviewed(false);
                          }}
                        >
                          <option value="">Choose protected evidence</option>
                          {rationales.map((r, i) => (
                            <option key={r.reference.object_id} value={r.reference.object_id}>
                              Evidence {i + 1}
                            </option>
                          ))}
                        </select>
                      </label>
                      {!rationales.length && (
                        <p className="mt-2 text-12 text-secondary">
                          No matching evidence is available. Prepare it with the plan’s authorized readers before
                          deciding.
                        </p>
                      )}
                      <Button
                        variant="secondary"
                        size="xl"
                        className={`mt-3 ${focus}`}
                        disabled={!rationaleRef || busy}
                        onClick={() => void loadMaterial(rationaleRef, "RATIONALE")}
                      >
                        Read decision evidence
                      </Button>
                      {evidence && <MaterialContent material={evidence} />}
                    </div>
                  )}
                  {action === "RELEASE" && !reconciliation && (
                    <p className="text-13 text-secondary">
                      Reconcile the selected tasks first. Any change to the tasks, access or review context requires a
                      new reconciliation.
                    </p>
                  )}
                  <label className="flex items-start gap-3 text-13 leading-6 text-primary">
                    <input
                      type="checkbox"
                      className={`mt-1 size-5 shrink-0 ${focus}`}
                      checked={reviewed}
                      disabled={!definition || (action !== "PREPARE" && !evidence)}
                      onChange={(e) => setReviewed(e.target.checked)}
                    />
                    <span>
                      I reviewed this plan{action !== "PREPARE" ? " and its decision evidence" : ""}
                      {needsClaims ? " and selected the reservations to reconcile or release" : ""}.
                    </span>
                  </label>
                  <Button size="xl" className={focus} disabled={!eligible || busy} onClick={() => void submit()}>
                    {labels[action]}
                  </Button>
                </div>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
function MaterialContent({ material }: { material: ManualGate2Material }) {
  let text = "";
  let outcomes: { id: string; text: string }[] = [];
  try {
    const body = JSON.parse(material.content) as Record<string, unknown>;
    if (material.kind === "RATIONALE" && typeof body.text === "string") text = body.text;
    if (material.kind === "DEFINITION" && Array.isArray(body.slices))
      outcomes = body.slices.flatMap((s: unknown) =>
        s && typeof s === "object" && "user_outcome" in s && typeof s.user_outcome === "string"
          ? [{ id: "id" in s && typeof s.id === "string" ? s.id : s.user_outcome, text: s.user_outcome }]
          : []
      );
  } catch {
    return (
      <p role="alert" className="mt-3 text-13 text-secondary">
        The protected material could not be displayed.
      </p>
    );
  }
  return (
    <div className="mt-3 min-w-0 space-y-3 text-13 leading-6 text-primary">
      {text && <p className="max-w-prose break-words whitespace-pre-wrap">{text}</p>}
      {!!outcomes.length && (
        <ul className="list-disc space-y-2 pl-5">
          {outcomes.map((outcome) => (
            <li key={outcome.id} className="max-w-prose break-words">
              {outcome.text}
            </li>
          ))}
        </ul>
      )}
      <details>
        <summary className="focus-visible:outline-accent-primary cursor-pointer text-secondary focus-visible:outline-2">
          Read the complete {material.kind === "DEFINITION" ? "definition" : "evidence"}
        </summary>
        <pre className="mt-3 max-h-80 overflow-auto rounded-md bg-layer-1 p-3 text-12 break-words whitespace-pre-wrap">
          {material.content}
        </pre>
      </details>
    </div>
  );
}
