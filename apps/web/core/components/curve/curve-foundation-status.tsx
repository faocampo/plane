/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Ban,
  Check,
  CheckCircle2,
  ChevronDown,
  Circle,
  Clock3,
  Gauge,
  LoaderCircle,
  RefreshCw,
  TriangleAlert,
  Wifi,
  WifiOff,
  XCircle,
} from "lucide-react";

import { Button } from "@plane/propel/button";
import { Dialog, EDialogWidth } from "@plane/propel/dialog";
import type { TCurveConnectionState, TCurveOperationStatus } from "@plane/types";
import { cn } from "@plane/utils";
import { useCurveFoundation } from "@/hooks/use-curve-foundation";
import {
  CURVE_CANCELLABLE_STATUSES,
  CURVE_TERMINAL_STATUSES,
  deriveCurveProgressStages,
  humanizeCurveStatus,
} from "./curve-foundation-state";

type TStatusTone = "danger" | "info" | "neutral" | "success" | "warning";

const statusCopy: Record<TCurveOperationStatus, { title: string; description: string; tone: TStatusTone }> = {
  PENDING: {
    title: "Starting foundation probe",
    description: "Curve accepted the verification request and is recording the Operation.",
    tone: "info",
  },
  QUEUED: {
    title: "Probe queued",
    description: "The Operation is recorded and waiting for the local workflow worker.",
    tone: "info",
  },
  RUNNING: {
    title: "Workflow running",
    description: "Curve is executing the harmless synthetic verification through Temporal.",
    tone: "info",
  },
  WAITING_FOR_HUMAN: {
    title: "Verification needs attention",
    description: "The Operation is waiting for an authorized human response.",
    tone: "warning",
  },
  CANCEL_REQUESTED: {
    title: "Cancellation requested",
    description: "Curve is stopping the current verification while retaining completed evidence.",
    tone: "warning",
  },
  SUCCEEDED: {
    title: "Foundation verified",
    description: "Curve recorded, orchestrated, and reported the Operation successfully.",
    tone: "success",
  },
  FAILED: {
    title: "Foundation check could not complete",
    description: "The safe diagnostic below can be used to retry without exposing internal details.",
    tone: "danger",
  },
  CANCELLED: {
    title: "Probe cancelled",
    description: "The verification stopped and the evidence completed before cancellation remains available.",
    tone: "neutral",
  },
};

const connectionCopy: Record<TCurveConnectionState, string> = {
  CONNECTING: "Connecting",
  LIVE: "Updates live",
  RECONNECTING: "Reconnecting",
  STALE: "Resync required",
  OFFLINE: "Updates offline",
};

const formatTime = (value?: string) => {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(parsed);
};

const StateIcon = ({ status }: { status?: TCurveOperationStatus }) => {
  if (status === "SUCCEEDED") return <CheckCircle2 className="size-6" aria-hidden="true" />;
  if (status === "FAILED") return <XCircle className="size-6" aria-hidden="true" />;
  if (status === "CANCELLED") return <Ban className="size-6" aria-hidden="true" />;
  if (status) return <LoaderCircle className="size-6 animate-spin motion-reduce:animate-none" aria-hidden="true" />;
  return <Gauge className="size-6" aria-hidden="true" />;
};

function ConnectionPill({ state }: { state: TCurveConnectionState }) {
  const connected = state === "LIVE";
  return (
    <div
      role="status"
      className={cn(
        "inline-flex min-h-8 items-center gap-2 rounded-full border px-3 text-12 font-medium",
        connected
          ? "border-success-subtle bg-success-subtle text-success-primary"
          : state === "STALE" || state === "OFFLINE"
            ? "border-danger-subtle bg-danger-subtle text-danger-primary"
            : "border-warning-subtle bg-warning-subtle text-warning-primary"
      )}
    >
      {connected ? (
        <Wifi className="size-3.5" aria-hidden="true" />
      ) : (
        <WifiOff className="size-3.5" aria-hidden="true" />
      )}
      {connectionCopy[state]}
    </div>
  );
}

function FoundationSkeleton() {
  return (
    <div
      className="mx-auto w-full max-w-6xl animate-pulse space-y-6 px-5 py-8 sm:px-8 lg:py-10"
      aria-label="Loading Foundation status"
    >
      <div className="space-y-3">
        <div className="h-4 w-32 rounded bg-layer-1" />
        <div className="h-9 w-72 rounded bg-layer-1" />
        <div className="h-5 max-w-xl rounded bg-layer-1" />
      </div>
      <div className="h-36 rounded-xl bg-layer-1" />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,0.42fr)]">
        <div className="h-80 rounded-xl bg-layer-1" />
        <div className="h-80 rounded-xl bg-layer-1" />
      </div>
    </div>
  );
}

export function CurvePermissionLimited({ workspaceSlug }: { workspaceSlug: string }) {
  return (
    <div className="mx-auto flex min-h-[28rem] w-full max-w-2xl items-center px-5 py-10">
      <section
        className="w-full rounded-xl border border-subtle bg-layer-1 p-8 text-center shadow-raised-100"
        aria-labelledby="curve-permission-title"
      >
        <div className="mx-auto mb-5 grid size-12 place-items-center rounded-xl bg-warning-subtle text-warning-primary">
          <TriangleAlert className="size-6" aria-hidden="true" />
        </div>
        <h1 id="curve-permission-title" className="text-24 font-semibold text-primary">
          Foundation status is unavailable
        </h1>
        <p className="mx-auto mt-3 max-w-lg text-14 text-secondary">
          Your current workspace access does not permit this local verification. Ask a workspace administrator to review
          your Curve access.
        </p>
        <Link href={`/${workspaceSlug}`} className="mt-6 inline-flex">
          <Button size="xl" variant="secondary">
            Back to workspace
          </Button>
        </Link>
      </section>
    </div>
  );
}

export function CurveFoundationStatus({ workspaceSlug, workspaceId }: { workspaceSlug: string; workspaceId: string }) {
  const {
    operation,
    etag,
    problem,
    connectionState,
    updates,
    lastEventId,
    lastUpdateAt,
    isLoading,
    isCreating,
    isCancelling,
    isPermissionLimited,
    createProbe,
    cancelProbe,
    resync,
    refresh,
  } = useCurveFoundation(workspaceSlug, workspaceId);
  const [isCancelOpen, setIsCancelOpen] = useState(false);
  const cancelTriggerRef = useRef<HTMLButtonElement>(null);
  const keepRunningRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isCancelOpen) return;
    const focusFrame = window.requestAnimationFrame(() => keepRunningRef.current?.focus());
    return () => window.cancelAnimationFrame(focusFrame);
  }, [isCancelOpen]);

  if (isLoading) return <FoundationSkeleton />;
  if (isPermissionLimited) return <CurvePermissionLimited workspaceSlug={workspaceSlug} />;

  const copy = operation ? statusCopy[operation.status] : undefined;
  const stages = deriveCurveProgressStages(
    operation,
    updates.flatMap((update) => (update.status ? [update.status] : []))
  );
  const completedStages = stages.filter((stage) => stage.state === "complete").length;
  const isStale = connectionState === "STALE";
  const canCancel = !!operation && CURVE_CANCELLABLE_STATUSES.has(operation.status) && !isCancelling;
  const canRun = !operation || CURVE_TERMINAL_STATUSES.has(operation.status);
  const tone = copy?.tone ?? "neutral";

  const closeCancelDialog = () => {
    setIsCancelOpen(false);
    window.setTimeout(() => cancelTriggerRef.current?.focus(), 0);
  };

  const confirmCancellation = async () => {
    await cancelProbe();
    closeCancelDialog();
  };

  return (
    <div className="mx-auto w-full max-w-6xl px-5 py-8 sm:px-8 lg:py-10">
      <div className="mb-7 flex flex-col justify-between gap-5 sm:flex-row sm:items-start">
        <div>
          <div className="mb-2 flex items-center gap-2 text-12 font-medium text-secondary">
            <span className="size-2 rounded-full bg-success-primary ring-4 ring-success-subtle" aria-hidden="true" />
            Local environment
          </div>
          <h1 className="text-32 leading-tight font-semibold tracking-[-0.025em] text-primary">Foundation status</h1>
          <p className="mt-2 max-w-[70ch] text-14 leading-6 text-secondary">
            Verify that Curve can record, orchestrate, and report one harmless workspace Operation end to end.
          </p>
        </div>
        <ConnectionPill state={connectionState} />
      </div>

      <section
        className={cn(
          "rounded-xl border bg-layer-1 p-5 shadow-raised-100 sm:p-6",
          tone === "success" && "border-success-subtle",
          tone === "danger" && "border-danger-subtle",
          tone === "warning" && "border-warning-subtle",
          tone === "info" && "border-accent-subtle",
          tone === "neutral" && "border-subtle"
        )}
        aria-labelledby="foundation-summary-title"
      >
        <div className="grid items-center gap-5 lg:grid-cols-[auto_minmax(0,1fr)_auto]">
          <div
            className={cn(
              "grid size-12 place-items-center rounded-xl",
              tone === "success" && "bg-success-subtle text-success-primary",
              tone === "danger" && "bg-danger-subtle text-danger-primary",
              tone === "warning" && "bg-warning-subtle text-warning-primary",
              tone === "info" && "bg-accent-subtle text-accent-primary",
              tone === "neutral" && "bg-layer-2 text-secondary"
            )}
          >
            <StateIcon status={operation?.status} />
          </div>
          <div aria-live="polite" aria-atomic="true">
            <h2 id="foundation-summary-title" className="text-18 font-semibold text-primary">
              {isCreating ? "Starting foundation probe" : (copy?.title ?? "Ready to verify")}
            </h2>
            <p className="mt-1 text-14 text-secondary">
              {isCreating
                ? "Submitting one idempotent local verification command."
                : (copy?.description ?? "No foundation probe has run in this workspace yet.")}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-12 text-tertiary">
              <span>{operation ? `Operation ${humanizeCurveStatus(operation.status)}` : "Local only"}</span>
              <span aria-hidden="true">•</span>
              <span>Harmless synthetic Operation</span>
              {lastUpdateAt && (
                <>
                  <span aria-hidden="true">•</span>
                  <span>Updated {formatTime(lastUpdateAt)}</span>
                </>
              )}
            </div>
          </div>
          <div className="flex flex-wrap gap-2 lg:justify-end">
            {isStale ? (
              <Button size="xl" onClick={() => void resync()} prependIcon={<RefreshCw />}>
                Resync status
              </Button>
            ) : canRun ? (
              <Button size="xl" loading={isCreating} onClick={() => void createProbe()}>
                {operation ? (operation.status === "FAILED" ? "Try again" : "Run again") : "Run foundation probe"}
              </Button>
            ) : canCancel ? (
              <Button ref={cancelTriggerRef} size="xl" variant="secondary" onClick={() => setIsCancelOpen(true)}>
                Cancel probe
              </Button>
            ) : null}
          </div>
        </div>
      </section>

      {problem && connectionState !== "STALE" && (
        <div
          className="mt-5 flex items-start justify-between gap-4 rounded-lg border border-danger-subtle bg-danger-subtle p-4"
          role="alert"
        >
          <div className="flex items-start gap-3">
            <TriangleAlert className="mt-0.5 size-4 flex-none text-danger-primary" aria-hidden="true" />
            <div>
              <p className="text-13 font-semibold text-danger-primary">{problem.title}</p>
              <p className="mt-1 text-12 text-danger-secondary">
                The last confirmed state remains visible. Retry the safe status request when ready.
              </p>
            </div>
          </div>
          <Button size="lg" variant="secondary" onClick={() => void refresh()}>
            Try again
          </Button>
        </div>
      )}

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(17rem,0.42fr)]">
        <section
          className="overflow-hidden rounded-xl border border-subtle bg-layer-1 shadow-raised-100"
          aria-labelledby="probe-progress-title"
        >
          <div className="flex items-center justify-between gap-4 border-b border-subtle px-5 py-4">
            <h2 id="probe-progress-title" className="text-16 font-semibold text-primary">
              Probe progress
            </h2>
            <span className="text-12 text-tertiary">
              {operation ? `${completedStages} of 5 complete` : "Not started"}
            </span>
          </div>
          <ol className="px-5 py-2">
            {stages.map((stage, index) => (
              <li key={stage.key} className="relative grid grid-cols-[2rem_minmax(0,1fr)] gap-3 py-3">
                {index < stages.length - 1 && (
                  <span
                    className="absolute top-9 bottom-[-0.75rem] left-[0.9375rem] w-px bg-layer-3"
                    aria-hidden="true"
                  />
                )}
                <span
                  className={cn(
                    "relative z-[1] grid size-8 place-items-center rounded-full border bg-layer-1",
                    stage.state === "complete" && "border-success-strong bg-success-primary text-on-color",
                    stage.state === "active" && "border-accent-strong bg-accent-subtle text-accent-primary",
                    stage.state === "failed" && "border-danger-strong bg-danger-subtle text-danger-primary",
                    stage.state === "waiting" && "border-subtle text-placeholder"
                  )}
                  aria-hidden="true"
                >
                  {stage.state === "complete" ? (
                    <Check className="size-4" />
                  ) : stage.state === "active" ? (
                    <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" />
                  ) : stage.state === "failed" ? (
                    <XCircle className="size-4" />
                  ) : (
                    <Circle className="size-3" />
                  )}
                </span>
                <div className="pt-1">
                  <p className="text-13 font-semibold text-primary">{stage.label}</p>
                  <p className="mt-0.5 text-12 leading-5 text-tertiary">{stage.description}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section
          className="overflow-hidden rounded-xl border border-subtle bg-layer-1 shadow-raised-100"
          aria-labelledby="latest-updates-title"
        >
          <div className="flex items-center justify-between border-b border-subtle px-5 py-4">
            <h2 id="latest-updates-title" className="text-16 font-semibold text-primary">
              Latest updates
            </h2>
            <Clock3 className="size-4 text-placeholder" aria-hidden="true" />
          </div>
          <div className="p-5">
            {updates.length === 0 ? (
              <p className="py-10 text-center text-13 text-tertiary">No live updates yet.</p>
            ) : (
              <ol className="space-y-4" aria-live="polite">
                {updates.map((update) => (
                  <li key={update.eventId} className="flex gap-3 border-b border-subtle pb-4 last:border-0 last:pb-0">
                    <span className="mt-1.5 size-2 flex-none rounded-full bg-accent-primary" aria-hidden="true" />
                    <div>
                      <p className="text-12 font-semibold text-primary">
                        {update.status ? humanizeCurveStatus(update.status) : "Operation updated"}
                      </p>
                      <p className="mt-1 text-11 text-tertiary">Received {formatTime(update.occurredAt)}</p>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </section>
      </div>

      <details className="group mt-5 rounded-xl border border-subtle bg-layer-1 shadow-raised-100">
        <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-4 rounded-xl px-5 py-4 text-14 font-semibold text-primary focus-visible:ring-2 focus-visible:ring-accent-strong focus-visible:outline-none focus-visible:ring-inset">
          Technical details
          <ChevronDown
            className="size-4 text-tertiary transition-transform group-open:rotate-180 motion-reduce:transition-none"
            aria-hidden="true"
          />
        </summary>
        <dl className="grid gap-x-8 gap-y-4 border-t border-subtle px-5 py-5 text-12 sm:grid-cols-2">
          <div>
            <dt className="text-tertiary">Operation ID</dt>
            <dd className="font-mono mt-1 break-all text-primary">{operation?.id ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-tertiary">Optimistic version</dt>
            <dd className="font-mono mt-1 text-primary">{operation?.version ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-tertiary">ETag</dt>
            <dd className="font-mono mt-1 break-all text-primary">{etag ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-tertiary">Connection</dt>
            <dd className="mt-1 text-primary">{connectionCopy[connectionState]}</dd>
          </div>
          <div>
            <dt className="text-tertiary">Last event ID</dt>
            <dd className="font-mono mt-1 break-all text-primary">{lastEventId ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-tertiary">Last confirmed update</dt>
            <dd className="mt-1 text-primary">{formatTime(lastUpdateAt)}</dd>
          </div>
          {problem && (
            <div className="sm:col-span-2">
              <dt className="text-tertiary">Safe diagnostic</dt>
              <dd className="font-mono mt-1 break-all text-danger-primary">{problem.type}</dd>
            </div>
          )}
        </dl>
      </details>

      {isCancelOpen && operation && (
        <Dialog open={isCancelOpen} onOpenChange={(open) => (open ? setIsCancelOpen(true) : closeCancelDialog())}>
          <Dialog.Panel width={EDialogWidth.SM}>
            <div className="p-6">
              <Dialog.Title>Cancel foundation probe?</Dialog.Title>
              <p className="mt-4 text-13 leading-5 text-secondary">
                The current verification will stop. Operation history and evidence completed before cancellation remain
                available.
              </p>
              <div className="mt-6 flex justify-end gap-2">
                <Button ref={keepRunningRef} size="lg" variant="secondary" onClick={closeCancelDialog}>
                  Keep running
                </Button>
                <Button
                  size="lg"
                  variant="error-fill"
                  loading={isCancelling}
                  onClick={() => void confirmCancellation()}
                >
                  Cancel probe
                </Button>
              </div>
            </div>
          </Dialog.Panel>
        </Dialog>
      )}
    </div>
  );
}
