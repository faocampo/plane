/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useRef, useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import { Inbox, Plus, RefreshCw, Search, TriangleAlert } from "lucide-react";

import { Dialog, EDialogWidth } from "@plane/propel/dialog";
import type {
  ICurveInitiative,
  ICurveProduct,
  IWorkspaceMember,
  TCurveGateType,
  TCurveInitiativeListState,
  TCurveInitiativeRiskTier,
} from "@plane/types";
import { Button } from "@plane/ui";
import { calculateTimeAgo, cn } from "@plane/utils";
import { useCurveInitiatives } from "@/hooks/use-curve-initiatives";
import { InitiativeCreateDrawer } from "./initiative-create-drawer";
import { InitiativeAvatar, InitiativeRiskBadge, InitiativeStateBadge, memberDisplayName } from "./initiative-ui";

const gateLabels: Record<TCurveGateType, string> = {
  PRD_APPROVAL: "Product Approver",
  PLAN_APPROVAL: "Technical Approver",
  CODE_READINESS: "Code Approver",
};

const filterClassName =
  "min-h-10 rounded-md border border-subtle bg-surface-1 px-3 text-12 text-primary outline-none focus:border-accent-primary focus:ring-2 focus:ring-accent-subtle";

type TReasonAction = "pause" | "resume" | "cancel";

const actionCopy: Record<TReasonAction, { title: string; description: string; button: string }> = {
  pause: {
    title: "Pause Initiative?",
    description: "Pause the current work while preserving its last confirmed lifecycle state.",
    button: "Pause Initiative",
  },
  resume: {
    title: "Resume Initiative?",
    description: "Resume the Initiative from the lifecycle state recorded before it was paused.",
    button: "Resume Initiative",
  },
  cancel: {
    title: "Cancel Initiative?",
    description: "Cancellation is terminal for this Initiative. Its history remains readable.",
    button: "Cancel Initiative",
  },
};

function InitiativeLoading() {
  return (
    <div
      className="mx-auto w-full max-w-7xl animate-pulse space-y-5 px-5 py-8 sm:px-8"
      aria-label="Loading Initiatives"
    >
      <div className="h-10 w-64 rounded-md bg-layer-1" />
      <div className="h-24 rounded-xl bg-layer-1" />
      <div className="grid gap-5 lg:grid-cols-[minmax(18rem,0.72fr)_minmax(0,1.28fr)]">
        <div className="h-96 rounded-xl bg-layer-1" />
        <div className="h-96 rounded-xl bg-layer-1" />
      </div>
    </div>
  );
}

function InitiativeEmpty({ filtered }: { filtered: boolean }) {
  return (
    <div className="flex min-h-64 flex-col items-center justify-center px-6 py-10 text-center">
      <span className="grid size-12 place-items-center rounded-xl bg-layer-1 text-secondary">
        <Inbox className="size-5" aria-hidden="true" />
      </span>
      <h3 className="mt-4 text-16 font-semibold text-primary">
        {filtered ? "No Initiatives match these filters" : "No Initiatives yet"}
      </h3>
      <p className="mt-2 max-w-sm text-12 leading-5 text-secondary">
        {filtered
          ? "Change the search, lifecycle state, or risk tier to see other loaded Initiatives."
          : "Create the first governed Initiative for an active Product."}
      </p>
    </div>
  );
}

function InitiativeRow({
  initiative,
  product,
  members,
  selected,
  onSelect,
}: {
  initiative: ICurveInitiative;
  product?: ICurveProduct;
  members: Map<string, IWorkspaceMember>;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "focus-visible:outline-accent-primary w-full border-b border-subtle px-4 py-4 text-left transition last:border-b-0 hover:bg-layer-1 focus-visible:relative focus-visible:z-10 focus-visible:outline-2 focus-visible:-outline-offset-2",
        selected && "bg-accent-subtle"
      )}
      aria-pressed={selected}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-13 font-semibold text-primary">{initiative.title}</h3>
          <p className="mt-1 truncate text-11 text-secondary">{product?.name ?? "Product unavailable"}</p>
        </div>
        <InitiativeStateBadge state={initiative.state} />
      </div>
      <div className="mt-3 flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono truncate text-10 text-tertiary">#{initiative.keyword}</p>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <InitiativeRiskBadge risk={initiative.risk_tier} />
            <span className="text-10 text-tertiary">Updated {calculateTimeAgo(initiative.updated_at)}</span>
          </div>
        </div>
        <div className="flex -space-x-1" aria-label="Assigned gate approvers">
          {initiative.gate_assignments.map((assignment) => (
            <InitiativeAvatar key={assignment.id} member={members.get(assignment.approver.actor_id)} size="sm" />
          ))}
        </div>
      </div>
    </button>
  );
}

function InitiativeDetail({
  initiative,
  product,
  members,
  etag,
  isMutating,
  onAccept,
  onAction,
}: {
  initiative: ICurveInitiative;
  product?: ICurveProduct;
  members: Map<string, IWorkspaceMember>;
  etag?: string;
  isMutating: boolean;
  onAccept: () => void;
  onAction: (action: TReasonAction) => void;
}) {
  const canMutate = !!etag && !isMutating;
  return (
    <article aria-labelledby="curve-initiative-detail-title" className="min-w-0">
      <header className="border-b border-subtle px-5 py-5 sm:px-6">
        <div className="flex flex-wrap items-center gap-2">
          <InitiativeStateBadge state={initiative.state} />
          <InitiativeRiskBadge risk={initiative.risk_tier} />
        </div>
        <h2
          id="curve-initiative-detail-title"
          className="mt-3 text-24 leading-8 font-semibold tracking-[-0.02em] text-primary"
        >
          {initiative.title}
        </h2>
        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-11 text-secondary">
          <span>{product?.name ?? "Product unavailable"}</span>
          <span aria-hidden="true">•</span>
          <code className="rounded bg-layer-1 px-1.5 py-0.5 text-10">#{initiative.keyword}</code>
        </div>
        <div className="mt-4 flex flex-wrap gap-2" aria-label="Initiative lifecycle actions">
          {initiative.state === "DRAFT" && (
            <Button size="lg" disabled={!canMutate} loading={isMutating} onClick={onAccept}>
              Accept refinement
            </Button>
          )}
          {(initiative.state === "DRAFT" || initiative.state === "ALIGNING") && (
            <Button size="lg" variant="neutral-primary" disabled={!canMutate} onClick={() => onAction("pause")}>
              Pause
            </Button>
          )}
          {initiative.state === "PAUSED" && (
            <Button size="lg" disabled={!canMutate} loading={isMutating} onClick={() => onAction("resume")}>
              Resume
            </Button>
          )}
          {initiative.state !== "CANCELLED" && (
            <Button size="lg" variant="neutral-primary" disabled={!canMutate} onClick={() => onAction("cancel")}>
              Cancel
            </Button>
          )}
          {!etag && initiative.state !== "CANCELLED" && (
            <span className="self-center text-11 text-tertiary">Loading current version…</span>
          )}
        </div>
      </header>

      <div className="grid lg:grid-cols-[minmax(0,1fr)_16rem]">
        <div className="space-y-7 px-5 py-6 sm:px-6">
          <section aria-labelledby="curve-initiative-problem-title">
            <h3 id="curve-initiative-problem-title" className="text-13 font-semibold text-primary">
              Problem and intended outcome
            </h3>
            <p className="mt-2 text-13 leading-6 whitespace-pre-wrap text-secondary">{initiative.description.body}</p>
          </section>
          <section aria-labelledby="curve-initiative-gates-title">
            <h3 id="curve-initiative-gates-title" className="text-13 font-semibold text-primary">
              Mandatory human gates
            </h3>
            <ul className="mt-3 space-y-2">
              {initiative.gate_assignments.map((assignment) => {
                const member = members.get(assignment.approver.actor_id);
                return (
                  <li key={assignment.id} className="flex items-center gap-3 rounded-lg bg-layer-1 px-3 py-3">
                    <InitiativeAvatar member={member} />
                    <div className="min-w-0 flex-1">
                      <p className="text-12 font-medium text-primary">{gateLabels[assignment.gate_type]}</p>
                      <p className="truncate text-11 text-secondary">{memberDisplayName(member)}</p>
                    </div>
                    <span className="text-10 font-medium text-success-primary">Active assignment</span>
                  </li>
                );
              })}
            </ul>
          </section>
          <section aria-labelledby="curve-initiative-activity-title">
            <h3 id="curve-initiative-activity-title" className="text-13 font-semibold text-primary">
              Lifecycle activity
            </h3>
            <ol className="mt-3 space-y-3 border-l border-subtle pl-4">
              <li>
                <p className="text-12 font-medium text-primary">Last confirmed update</p>
                <p className="mt-0.5 text-11 text-secondary">{calculateTimeAgo(initiative.updated_at)}</p>
              </li>
              <li>
                <p className="text-12 font-medium text-primary">Initiative created</p>
                <p className="mt-0.5 text-11 text-secondary">{calculateTimeAgo(initiative.created_at)}</p>
              </li>
            </ol>
          </section>
        </div>
        <aside
          className="border-t border-subtle bg-layer-1 px-5 py-6 lg:border-t-0 lg:border-l"
          aria-label="Initiative metadata"
        >
          <dl className="space-y-5">
            <div>
              <dt className="text-9 font-semibold tracking-[0.08em] text-tertiary uppercase">Mode</dt>
              <dd className="mt-1 text-11 text-primary">Standalone</dd>
            </div>
            <div>
              <dt className="text-9 font-semibold tracking-[0.08em] text-tertiary uppercase">Creator</dt>
              <dd className="mt-1 text-11 text-primary">
                {memberDisplayName(members.get(initiative.creator.actor_id))}
              </dd>
            </div>
            <div>
              <dt className="text-9 font-semibold tracking-[0.08em] text-tertiary uppercase">Workflow version</dt>
              <dd className="mt-1 text-11 text-primary">{initiative.workflow_version_id ?? "Not assigned"}</dd>
            </div>
            <div>
              <dt className="text-9 font-semibold tracking-[0.08em] text-tertiary uppercase">Optimistic version</dt>
              <dd className="mt-1 text-11 text-primary">v{initiative.version}</dd>
            </div>
            <div>
              <dt className="text-9 font-semibold tracking-[0.08em] text-tertiary uppercase">Updated</dt>
              <dd className="mt-1 text-11 text-primary">{new Date(initiative.updated_at).toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-9 font-semibold tracking-[0.08em] text-tertiary uppercase">External resource</dt>
              <dd className="mt-1 text-11 text-primary">
                {initiative.first_external_resource_at ? "Linked" : "None linked"}
              </dd>
            </div>
          </dl>
        </aside>
      </div>
    </article>
  );
}

export const InitiativeWorkspace = observer(function InitiativeWorkspace({ workspaceSlug }: { workspaceSlug: string }) {
  const {
    products,
    initiatives,
    nextCursor,
    selectedInitiative,
    selectedEtag,
    activeMembers,
    problem,
    isLoading,
    isLoadingMore,
    isMutating,
    isPermissionLimited,
    isConflict,
    selectInitiative,
    loadMore,
    createInitiative,
    acceptRefinement,
    pauseInitiative,
    resumeInitiative,
    cancelInitiative,
    refreshSelected,
    refresh,
  } = useCurveInitiatives(workspaceSlug);
  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState<"ALL" | TCurveInitiativeListState>("ALL");
  const [riskFilter, setRiskFilter] = useState<"ALL" | TCurveInitiativeRiskTier>("ALL");
  const [createOpen, setCreateOpen] = useState(false);
  const [reasonAction, setReasonAction] = useState<TReasonAction>();
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const createTriggerRef = useRef<HTMLButtonElement>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const productMap = useMemo(() => new Map(products.map((product) => [product.id, product])), [products]);
  const memberMap = useMemo(() => new Map(activeMembers.map((member) => [member.member.id, member])), [activeMembers]);

  const normalizedSearch = search.trim().toLowerCase();
  const visibleInitiatives = initiatives.filter((initiative) => {
    const product = productMap.get(initiative.product_id);
    const matchesSearch =
      !normalizedSearch ||
      [initiative.title, initiative.keyword, initiative.description.body, product?.name]
        .filter(Boolean)
        .some((value) => value?.toLowerCase().includes(normalizedSearch));
    const matchesState = stateFilter === "ALL" || initiative.state === stateFilter;
    const matchesRisk = riskFilter === "ALL" || initiative.risk_tier === riskFilter;
    return matchesSearch && matchesState && matchesRisk;
  });
  const visibleSelected = visibleInitiatives.find(({ id }) => id === selectedInitiative?.id);
  const filtered = !!normalizedSearch || stateFilter !== "ALL" || riskFilter !== "ALL";
  const activeCount = initiatives.filter(({ state }) => state === "DRAFT" || state === "ALIGNING").length;
  const pausedCount = initiatives.filter(({ state }) => state === "PAUSED").length;
  const needsAttentionCount = initiatives.filter(
    ({ risk_tier, state }) => risk_tier === "HIGH" && state !== "CANCELLED"
  ).length;
  const createUnavailableReason =
    products.length === 0
      ? "An active Product is required before an Initiative can be created."
      : activeMembers.length === 0
        ? "At least one active workspace member is required before an Initiative can be created."
        : undefined;

  const closeCreate = () => {
    setCreateOpen(false);
    window.setTimeout(() => createTriggerRef.current?.focus(), 0);
  };

  const openReasonAction = (action: TReasonAction) => {
    setReason("");
    setReasonError(false);
    setReasonAction(action);
  };

  const submitReasonAction = async () => {
    if (!reasonAction || !reason.trim()) {
      setReasonError(true);
      return;
    }
    const succeeded =
      reasonAction === "pause"
        ? await pauseInitiative(reason.trim())
        : reasonAction === "resume"
          ? await resumeInitiative(reason.trim())
          : await cancelInitiative(reason.trim());
    if (succeeded) {
      setAnnouncement(
        reasonAction === "pause"
          ? "Initiative paused."
          : reasonAction === "resume"
            ? "Initiative resumed."
            : "Initiative cancelled."
      );
      setReasonAction(undefined);
    }
  };

  const handleCreate = async (payload: Parameters<typeof createInitiative>[0]) => {
    const succeeded = await createInitiative(payload);
    if (succeeded) setAnnouncement("Initiative created in Draft state.");
    return succeeded;
  };

  const handleAcceptRefinement = async () => {
    const succeeded = await acceptRefinement();
    if (succeeded) setAnnouncement("Initiative refinement accepted. State changed to Aligning.");
  };

  if (isLoading) return <InitiativeLoading />;

  if (isPermissionLimited) {
    return (
      <div className="mx-auto flex min-h-[30rem] w-full max-w-2xl items-center px-5 py-10">
        <section className="w-full rounded-xl border border-subtle bg-layer-1 p-8 text-center shadow-raised-100">
          <TriangleAlert className="mx-auto size-8 text-warning-primary" aria-hidden="true" />
          <h1 className="mt-4 text-24 font-semibold text-primary">Initiatives are unavailable</h1>
          <p className="mt-3 text-13 text-secondary">Your current workspace access does not permit this Curve view.</p>
          <Link
            href={`/${workspaceSlug}`}
            className="focus-visible:ring-accent-primary mt-5 inline-flex min-h-10 items-center rounded-md px-3 text-12 font-medium text-accent-primary outline-none hover:bg-layer-1 focus-visible:ring-2"
          >
            Return to workspace
          </Link>
        </section>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-7xl px-5 py-8 sm:px-8 lg:py-10">
      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>
      <header className="flex flex-col justify-between gap-5 sm:flex-row sm:items-start">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-11 font-semibold tracking-[0.08em] text-accent-primary uppercase">Product</p>
            <span className="rounded-full bg-layer-1 px-2 py-1 text-10 font-medium text-secondary">
              Local · manual-first
            </span>
          </div>
          <h1 className="mt-1 text-32 leading-tight font-semibold tracking-[-0.025em] text-primary">Initiatives</h1>
          <p className="mt-2 max-w-2xl text-13 leading-6 text-secondary">
            Shape product intent, assign mandatory human gates, and keep readiness visible before planning or execution
            begins.
          </p>
        </div>
        <div className="flex max-w-sm flex-col items-start gap-2 sm:items-end">
          <Button
            ref={createTriggerRef}
            size="xl"
            prependIcon={<Plus />}
            disabled={!!createUnavailableReason}
            aria-describedby={createUnavailableReason ? "curve-initiative-create-requirement" : undefined}
            onClick={() => setCreateOpen(true)}
          >
            New Initiative
          </Button>
          {createUnavailableReason && (
            <p id="curve-initiative-create-requirement" className="text-11 leading-5 text-secondary sm:text-right">
              {createUnavailableReason}
            </p>
          )}
        </div>
      </header>

      <section
        className="mt-6 grid overflow-hidden rounded-xl border border-subtle bg-layer-1 shadow-raised-100 sm:grid-cols-3"
        aria-label="Loaded Initiative portfolio summary"
      >
        {[
          { label: "Active", value: activeCount, detail: "Draft or aligning" },
          { label: "Paused", value: pausedCount, detail: "Explicitly recoverable" },
          { label: "Needs attention", value: needsAttentionCount, detail: "High-risk active work" },
        ].map(({ label, value, detail }) => (
          <div
            key={label}
            className="border-b border-subtle px-4 py-4 last:border-b-0 sm:border-r sm:border-b-0 sm:last:border-r-0"
          >
            <p className="text-9 font-semibold tracking-[0.08em] text-tertiary uppercase">{label}</p>
            <p className="mt-1 text-24 font-semibold text-primary">{value}</p>
            <p className="mt-1 text-10 text-secondary">{detail}</p>
          </div>
        ))}
      </section>

      {problem && (
        <div
          role="alert"
          className="mt-5 flex flex-col justify-between gap-3 rounded-lg border border-danger-subtle bg-danger-subtle p-4 sm:flex-row sm:items-center"
        >
          <div className="flex items-start gap-3">
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-danger-primary" aria-hidden="true" />
            <div>
              <p className="text-13 font-semibold text-danger-primary">{problem.title}</p>
              <p className="mt-1 text-11 text-danger-secondary">
                The last confirmed workspace state remains visible.
                {problem.correlation_id ? ` Reference ${problem.correlation_id}.` : ""}
              </p>
            </div>
          </div>
          <Button
            size="lg"
            variant="neutral-primary"
            prependIcon={<RefreshCw />}
            onClick={() => void (isConflict ? refreshSelected() : refresh())}
          >
            {isConflict ? "Reload current state" : "Try again"}
          </Button>
        </div>
      )}

      <section
        className="mt-4 overflow-hidden rounded-xl border border-subtle bg-layer-1 shadow-raised-100"
        aria-label="Initiative filters"
      >
        <div className="grid gap-3 p-3 md:grid-cols-[minmax(0,1fr)_12rem_12rem_auto]">
          <label className="relative">
            <span className="sr-only">Search loaded Initiatives</span>
            <Search
              className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-placeholder"
              aria-hidden="true"
            />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search title, keyword, Product, or description"
              className={`${filterClassName} w-full pl-9`}
            />
          </label>
          <label>
            <span className="sr-only">Filter by lifecycle state</span>
            <select
              value={stateFilter}
              onChange={(event) => setStateFilter(event.target.value as typeof stateFilter)}
              className={`${filterClassName} w-full`}
            >
              <option value="ALL">All states</option>
              <option value="DRAFT">Draft</option>
              <option value="ALIGNING">Aligning</option>
              <option value="PAUSED">Paused</option>
              <option value="CANCELLED">Cancelled</option>
            </select>
          </label>
          <label>
            <span className="sr-only">Filter by risk tier</span>
            <select
              value={riskFilter}
              onChange={(event) => setRiskFilter(event.target.value as typeof riskFilter)}
              className={`${filterClassName} w-full`}
            >
              <option value="ALL">All risk tiers</option>
              <option value="LOW">Low risk</option>
              <option value="STANDARD">Standard risk</option>
              <option value="HIGH">High risk</option>
            </select>
          </label>
          <p className="self-center text-right text-11 text-tertiary" role="status">
            {visibleInitiatives.length} visible loaded {visibleInitiatives.length === 1 ? "Initiative" : "Initiatives"}
            {nextCursor ? " · more available" : ""}
          </p>
        </div>
      </section>

      <div className="mt-4 grid overflow-hidden rounded-xl border border-subtle bg-surface-1 shadow-raised-100 lg:grid-cols-[minmax(18rem,0.72fr)_minmax(0,1.28fr)]">
        <section
          className="min-w-0 border-b border-subtle lg:border-r lg:border-b-0"
          aria-labelledby="curve-initiative-list-title"
        >
          <div className="flex items-center justify-between gap-3 border-b border-subtle px-4 py-3">
            <h2 id="curve-initiative-list-title" className="text-12 font-semibold text-primary">
              Workspace Initiatives
            </h2>
            <span className="text-10 text-tertiary">Newest first</span>
          </div>
          {visibleInitiatives.length === 0 ? (
            <InitiativeEmpty filtered={filtered} />
          ) : (
            <div>
              {visibleInitiatives.map((initiative) => (
                <InitiativeRow
                  key={initiative.id}
                  initiative={initiative}
                  product={productMap.get(initiative.product_id)}
                  members={memberMap}
                  selected={visibleSelected?.id === initiative.id}
                  onSelect={() => selectInitiative(initiative.id)}
                />
              ))}
            </div>
          )}
          {nextCursor && (
            <div className="border-t border-subtle p-3">
              <Button
                className="w-full"
                size="lg"
                variant="neutral-primary"
                loading={isLoadingMore}
                onClick={() => void loadMore()}
              >
                Load more
              </Button>
            </div>
          )}
        </section>

        <section className="min-w-0" aria-label="Selected Initiative">
          {visibleSelected ? (
            <InitiativeDetail
              initiative={visibleSelected}
              product={productMap.get(visibleSelected.product_id)}
              members={memberMap}
              etag={selectedEtag}
              isMutating={isMutating}
              onAccept={() => void handleAcceptRefinement()}
              onAction={openReasonAction}
            />
          ) : (
            <div className="flex min-h-80 items-center justify-center p-8 text-center">
              <div>
                <h2 className="text-16 font-semibold text-primary">Choose a visible Initiative</h2>
                <p className="mt-2 text-12 text-secondary">
                  Select one row to inspect its definition and lifecycle actions.
                </p>
              </div>
            </div>
          )}
        </section>
      </div>

      {createOpen && (
        <InitiativeCreateDrawer
          open
          products={products}
          members={activeMembers}
          isSubmitting={isMutating}
          onClose={closeCreate}
          onCreate={handleCreate}
        />
      )}

      {reasonAction && (
        <Dialog open onOpenChange={(open) => !open && setReasonAction(undefined)}>
          <Dialog.Panel initialFocus={reasonRef} width={EDialogWidth.MD}>
            <div className="p-5 sm:p-6">
              <Dialog.Title>{actionCopy[reasonAction].title}</Dialog.Title>
              <p className="mt-2 text-12 leading-5 text-secondary">
                {reasonAction === "cancel" && selectedInitiative
                  ? `Cancel “${selectedInitiative.title}”. ${actionCopy.cancel.description}`
                  : actionCopy[reasonAction].description}
              </p>
              <label htmlFor="curve-initiative-action-reason" className="mt-5 block text-12 font-semibold text-primary">
                Reason
              </label>
              <textarea
                ref={reasonRef}
                id="curve-initiative-action-reason"
                value={reason}
                onChange={(event) => {
                  setReason(event.target.value);
                  setReasonError(false);
                }}
                className={cn(
                  filterClassName,
                  "mt-1 min-h-24 w-full resize-y py-2",
                  reasonError && "border-danger-strong focus:border-danger-strong focus:ring-danger-subtle"
                )}
                maxLength={2000}
                aria-invalid={reasonError}
                aria-describedby={reasonError ? "curve-initiative-action-reason-error" : undefined}
              />
              {reasonError && (
                <p
                  id="curve-initiative-action-reason-error"
                  role="alert"
                  className="mt-1 text-12 font-medium text-danger-primary"
                >
                  Enter a reason.
                </p>
              )}
              <div className="mt-5 flex justify-end gap-2">
                <Button size="lg" variant="neutral-primary" onClick={() => setReasonAction(undefined)}>
                  Keep current state
                </Button>
                <Button size="lg" loading={isMutating} onClick={() => void submitReasonAction()}>
                  {actionCopy[reasonAction].button}
                </Button>
              </div>
            </div>
          </Dialog.Panel>
        </Dialog>
      )}
    </div>
  );
});
