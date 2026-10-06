/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 */
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { FileText, Info, RefreshCw } from "lucide-react";
import { Button } from "@plane/propel/button";
import { ManualPlanClientError } from "@plane/services";
import type {
  ManualPlanApi,
  ManualPlanCommand,
  ManualPlanRevision,
  ManualPlanSave,
  ManualPlanStatus,
  ManualPlanTarget,
} from "@plane/services";

type Props = {
  api: ManualPlanApi;
  target: ManualPlanTarget;
  viewerId?: string;
  initiativeVersion: number;
  prepared?: { payload: ManualPlanSave; initiativeVersion: number };
};
type View =
  | { state: "loading" | "unavailable" }
  | { state: "ready"; status: ManualPlanStatus; revisions: ManualPlanRevision[] };
const focus = "focus-visible:ring-2 focus-visible:ring-accent-primary focus-visible:ring-offset-2";

/** Not mounted until the backend and protected definition producer are qualified. */
export function ManualPlanPanel(props: Props) {
  // Identity changes remount synchronously: no frame can display the previous user's metadata.
  const { workspaceSlug, workspaceId, productId, initiativeId } = props.target;
  const target = useMemo(
    () => ({ workspaceSlug, workspaceId, productId, initiativeId }),
    [workspaceSlug, workspaceId, productId, initiativeId]
  );
  const key = JSON.stringify([props.viewerId, target, props.initiativeVersion, props.prepared]);
  return <ManualPlanSession key={key} {...props} target={target} />;
}
function ManualPlanSession({ api, target, viewerId, prepared }: Props) {
  const titleId = useId();
  const [view, setView] = useState<View>({ state: "loading" });
  const [revision, setRevision] = useState(0);
  const [activity, setActivity] = useState<"idle" | "saving" | "history" | "unknown">("idle");
  const [notice, setNotice] = useState("");
  const pending = useRef<ManualPlanCommand | null>(null);
  const operation = useRef<AbortController | null>(null);
  const busy = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      operation.current?.abort();
      pending.current = null;
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    operation.current = controller;
    setView({ state: "loading" });
    if (!viewerId) {
      setView({ state: "unavailable" });
      return () => controller.abort();
    }
    void (async () => {
      const result = await api.status(target, controller.signal);
      const revisions: ManualPlanRevision[] = [];
      if (result.data.draft_status === "CURRENT") {
        const current = await api.current(target, controller.signal);
        if (
          current.etag !== result.etag ||
          current.data.id !== result.data.current_revision_id ||
          current.data.revision !== result.data.expected_draft_revision
        )
          throw new ManualPlanClientError("CONFLICT");
        revisions.push(current.data);
      }
      if (!controller.signal.aborted) setView({ state: "ready", status: result.data, revisions });
    })().catch(() => {
      if (!controller.signal.aborted) setView({ state: "unavailable" });
    });
    return () => controller.abort();
  }, [api, target, viewerId, revision]);
  useEffect(() => {
    const refresh = () => {
      if (busy.current) return;
      operation.current?.abort();
      setView({ state: "loading" });
      setRevision((value) => value + 1);
    };
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
  const refresh = () => {
    operation.current?.abort();
    setView({ state: "loading" });
    setNotice("");
    setRevision((value) => value + 1);
  };
  const ready = view.state === "ready" ? view : null;
  const current = ready?.revisions[0];
  const canSave = !!(
    viewerId &&
    prepared &&
    ready &&
    prepared.initiativeVersion === ready.status.initiative_version &&
    prepared.payload.expected_draft_revision === ready.status.expected_draft_revision
  );
  async function save() {
    if (busy.current || (!pending.current && !canSave)) return;
    const command =
      pending.current ??
      (prepared && ready
        ? {
            payload: structuredClone(prepared.payload),
            expectedVersion: ready.status.initiative_version,
            idempotencyKey: crypto.randomUUID(),
          }
        : null);
    if (!command) return;
    pending.current = command;
    busy.current = true;
    setActivity("saving");
    setNotice("");
    operation.current?.abort();
    const controller = new AbortController();
    operation.current = controller;
    setView({ state: "loading" });
    try {
      await api.save(target, command, controller.signal);
      if (!mounted.current) return;
      pending.current = null;
      setActivity("idle");
      setNotice("Draft saved. Refreshing its current status.");
      setRevision((value) => value + 1);
    } catch (error) {
      if (!mounted.current) return;
      setView({ state: "unavailable" });
      if (error instanceof ManualPlanClientError && error.code === "UNKNOWN") {
        setActivity("unknown");
        setNotice("The save result could not be confirmed. Retry the same save to check its outcome.");
      } else {
        pending.current = null;
        setActivity("idle");
        setNotice(
          error instanceof ManualPlanClientError && error.code === "CONFLICT"
            ? "The plan or Initiative changed. Refresh and prepare the draft again."
            : "The draft could not be saved. Refresh to check current access and try again."
        );
      }
    } finally {
      busy.current = false;
    }
  }
  async function previous() {
    const last = ready?.revisions.at(-1);
    if (busy.current || !ready || !last?.predecessor_id) return;
    busy.current = true;
    setActivity("history");
    setNotice("");
    operation.current?.abort();
    const controller = new AbortController();
    operation.current = controller;
    try {
      const result = await api.revision(target, last.predecessor_id, controller.signal);
      if (
        result.currentVersion !== ready.status.initiative_version ||
        result.data.draft_id !== last.draft_id ||
        result.data.revision !== last.revision - 1
      )
        throw new ManualPlanClientError("CONFLICT");
      if (!controller.signal.aborted) setView({ ...ready, revisions: [...ready.revisions, result.data] });
    } catch {
      if (!controller.signal.aborted) {
        setView({ state: "unavailable" });
        setNotice("Revision history is unavailable. Refresh to check current access.");
      }
    } finally {
      busy.current = false;
      if (mounted.current) setActivity("idle");
    }
  }
  const stateText =
    activity === "saving"
      ? "Saving draft…"
      : view.state === "loading"
        ? "Checking current access…"
        : view.state === "unavailable"
          ? "Draft unavailable for this view"
          : ready?.status.draft_status === "ABSENT"
            ? "No draft saved"
            : ready?.status.draft_status === "STALE"
              ? "Draft needs a fresh plan"
              : "Draft saved for review";
  return (
    <section
      aria-labelledby={titleId}
      className="min-w-0 space-y-5 rounded-xl border border-subtle-1 bg-surface-1 p-5 text-body-sm-regular text-primary sm:p-6"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-2">
          <h2 id={titleId} className="text-h5-semibold">
            Manual plan
          </h2>
          <p role="status" aria-live="polite" className="flex items-center gap-2 text-secondary">
            <FileText className="size-4 shrink-0" aria-hidden="true" />
            {stateText}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            size="xl"
            className={focus}
            disabled={activity === "saving" || activity === "history" || view.state === "loading"}
            onClick={refresh}
            prependIcon={<RefreshCw aria-hidden="true" />}
          >
            Refresh
          </Button>
          <Button
            size="xl"
            className={focus}
            disabled={activity === "saving" || activity === "history" || (!canSave && activity !== "unknown")}
            onClick={() => void save()}
          >
            {activity === "saving" ? "Saving…" : activity === "unknown" ? "Retry same save" : "Save prepared draft"}
          </Button>
        </div>
      </div>
      {notice && (
        <p role="alert" className="max-w-prose text-secondary">
          {notice}
        </p>
      )}
      {ready?.status.draft_status === "ABSENT" && (
        <p className="max-w-prose text-secondary">
          Prepare a plan from the approved PRD to save your first draft. Work stays in its existing projects.
        </p>
      )}
      {ready?.status.draft_status === "STALE" && (
        <p className="max-w-prose text-secondary">
          The approved scope or planning inputs changed. Prepare a fresh plan before continuing.
        </p>
      )}
      {current && (
        <div className="space-y-4">
          <dl className="grid gap-4 border-y border-subtle-1 py-4 sm:grid-cols-3">
            <div>
              <dt className="text-body-xs-regular text-secondary">Current revision</dt>
              <dd className="mt-1 font-medium tabular-nums">Revision {current.revision}</dd>
            </div>
            <div>
              <dt className="text-body-xs-regular text-secondary">Saved at</dt>
              <dd className="mt-1 tabular-nums">
                <time dateTime={current.recorded_at}>
                  {new Date(current.recorded_at).toLocaleString(undefined, {
                    dateStyle: "medium",
                    timeStyle: "short",
                    timeZone: "UTC",
                  })}{" "}
                  UTC
                </time>
              </dd>
            </div>
            <div>
              <dt className="text-body-xs-regular text-secondary">Approval</dt>
              <dd className="mt-1">Not approved</dd>
            </div>
          </dl>
          <details>
            <summary
              className={`w-fit cursor-pointer rounded-sm text-secondary underline-offset-4 hover:underline ${focus}`}
            >
              Revision evidence
            </summary>
            <ol className="mt-3 space-y-4">
              {ready.revisions.map((item) => (
                <li key={item.id} className="space-y-1">
                  <p className="font-medium">Revision {item.revision}</p>
                  <p className="text-body-xs-regular text-secondary">Definition digest</p>
                  <code className="block text-body-xs-regular break-all text-secondary">
                    {item.definition_ref.digest}
                  </code>
                </li>
              ))}
            </ol>
            {ready.revisions.at(-1)?.predecessor_id && (
              <Button
                size="xl"
                variant="secondary"
                className={`mt-4 ${focus}`}
                disabled={activity === "history"}
                onClick={() => void previous()}
              >
                {activity === "history" ? "Loading revision…" : "Load previous revision"}
              </Button>
            )}
          </details>
        </div>
      )}
      {prepared && ready && canSave && (
        <p className="max-w-prose text-secondary">
          A prepared draft is ready to save as revision {ready.status.expected_draft_revision + 1}.
        </p>
      )}
      <p className="flex max-w-prose items-start gap-2 text-body-xs-regular leading-relaxed text-secondary">
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <span>
          Saving retains a draft. Technical approval and task reservations are separate steps. No work starts
          automatically.
        </span>
      </p>
    </section>
  );
}
