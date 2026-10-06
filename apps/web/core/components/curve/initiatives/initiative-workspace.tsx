/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useRef, useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import { Inbox, Pencil, Plus, RefreshCw, Search, TriangleAlert } from "lucide-react";

import { Dialog, EDialogWidth } from "@plane/propel/dialog";
import type {
  ICurveInitiative,
  ICurveInitiativeDraftUpdateRequest,
  ICurveProduct,
  IWorkspaceMember,
  TCurveInitiativeBusinessIntent,
  TCurveInitiativeListState,
  TCurveInitiativeRiskTier,
} from "@plane/types";
import { Button } from "@plane/ui";
import { calculateTimeAgo, cn } from "@plane/utils";
import { useUser } from "@/hooks/store/user";
import { useCurveInitiatives } from "@/hooks/use-curve-initiatives";
import { InitiativeCreateDrawer } from "./initiative-create-drawer";
import { PrdReviewPanel } from "./prd-review-panel";
import { ManualControlEntry } from "./manual-control-panel";
import {
  InitiativeAvatar,
  InitiativeRiskBadge,
  InitiativeStateBadge,
  initiativeApproverRoles,
  initiativeBusinessIntentLabel,
  initiativeBusinessIntentOptions,
  memberDisplayName,
} from "./initiative-ui";

const filterClassName =
  "min-h-10 rounded-md border border-subtle bg-surface-1 px-3 text-12 text-primary outline-none focus:border-accent-primary focus:ring-2 focus:ring-accent-subtle";

type TReasonAction = "pause" | "resume" | "cancel";
type TSummaryFilter = "ACTIVE" | "PAUSED" | "NEEDS_ATTENTION";

function initialInitiativeFilter<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  if (typeof window === "undefined") return fallback;
  const value = new URLSearchParams(window.location.search).get(key);
  return value && allowed.includes(value as T) ? (value as T) : fallback;
}

function initialSummaryFilter(): TSummaryFilter | undefined {
  if (typeof window === "undefined") return undefined;
  const value = new URLSearchParams(window.location.search).get("summary");
  return value && ["ACTIVE", "PAUSED", "NEEDS_ATTENTION"].includes(value) ? (value as TSummaryFilter) : undefined;
}

const initiativeKeywordPattern = /^[A-Za-z0-9][A-Za-z0-9-]{0,49}$/;

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
      <div className="grid gap-5 lg:grid-cols-[minmax(16rem,0.65fr)_minmax(0,1.35fr)]">
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
  workspaceSlug,
  viewerId,
  initiative,
  product,
  members,
  etag,
  isMutating,
  onAccept,
  onEdit,
  onAction,
}: {
  workspaceSlug: string;
  viewerId?: string;
  initiative: ICurveInitiative;
  product?: ICurveProduct;
  members: Map<string, IWorkspaceMember>;
  etag?: string;
  isMutating: boolean;
  onAccept: () => void;
  onEdit: () => void;
  onAction: (action: TReasonAction) => void;
}) {
  const canMutate = !!etag && !isMutating;
  const canEdit = initiative.state === "DRAFT" && !initiative.first_external_resource_at;
  const isDraft = initiative.state === "DRAFT";
  const nextStep = isDraft
    ? initiative.business_intent
      ? "Start alignment"
      : "Choose a business intent"
    : initiative.state === "ALIGNING"
      ? "Prepare for PRD review"
      : initiative.state === "PAUSED"
        ? "Resume when the work can continue"
        : initiative.state === "CANCELLED"
          ? "This Initiative is cancelled"
          : initiative.state === "PRD_REVIEW"
            ? "Review the submitted PRD"
            : "Check the current lifecycle stage";
  return (
    <article aria-labelledby="curve-initiative-detail-title" className="min-w-0">
      <header className="border-b border-subtle px-5 py-5 sm:px-6">
        <div className="flex flex-wrap items-center gap-3">
          <InitiativeStateBadge state={initiative.state} />
          <InitiativeRiskBadge risk={initiative.risk_tier} />
        </div>
        <h2
          id="curve-initiative-detail-title"
          className="mt-3 text-24 leading-8 font-semibold tracking-[-0.02em] break-words text-primary"
        >
          {initiative.title}
        </h2>
        <p className="mt-2 text-12 break-words text-secondary">
          {product?.name ?? "Product unavailable"} · #{initiative.keyword}
        </p>
        <div className="mt-6">
          <h3 className="text-13 font-semibold text-primary">{nextStep}</h3>
          <p className="mt-1 max-w-prose text-12 leading-5 text-secondary">
            {isDraft
              ? initiative.business_intent
                ? "Start alignment moves this Initiative from Draft to Aligning and records the current workflow and approver assignments."
                : "Choose and save a business intent before starting alignment."
              : initiative.state === "ALIGNING"
                ? "Complete the Idea Brief and PRD, resolve blockers and identify assumptions before submitting an exact version for review."
                : initiative.state === "PAUSED"
                  ? "The last confirmed lifecycle stage is preserved. A reason is required to resume."
                  : initiative.state === "CANCELLED"
                    ? "Its history remains available. Cancellation cannot be reversed."
                    : "Check the authorized PRD context below. Lifecycle state alone does not establish a current approval."}
          </p>
          <div className="mt-3 flex flex-wrap gap-2" aria-label="Initiative lifecycle actions">
            {isDraft && (
              <Button
                size="lg"
                disabled={!canMutate || !initiative.business_intent}
                loading={isMutating}
                onClick={onAccept}
              >
                Start alignment
              </Button>
            )}
            {canEdit && (
              <Button
                size="lg"
                variant="neutral-primary"
                prependIcon={<Pencil />}
                disabled={!canMutate}
                onClick={onEdit}
              >
                Edit Initiative
              </Button>
            )}
            {initiative.state === "PAUSED" && (
              <Button size="lg" disabled={!canMutate} loading={isMutating} onClick={() => onAction("resume")}>
                Resume
              </Button>
            )}
          </div>
          {!etag && initiative.state !== "CANCELLED" && (
            <p className="mt-2 text-12 text-secondary" role="status">
              Loading current version…
            </p>
          )}
        </div>
      </header>
      <div className="space-y-7 px-5 py-6 sm:px-6">
        <section aria-labelledby="curve-initiative-problem-title">
          <h3 id="curve-initiative-problem-title" className="text-13 font-semibold text-primary">
            Problem and intended outcome
          </h3>
          <p className="mt-2 max-w-prose text-13 leading-6 break-words whitespace-pre-wrap text-secondary">
            {initiative.description.body}
          </p>
        </section>
        <PrdReviewPanel workspaceSlug={workspaceSlug} initiative={initiative} viewerId={viewerId} />
        <ManualControlEntry
          target={{
            workspaceSlug,
            workspaceId: initiative.workspace_id,
            productId: initiative.product_id,
            initiativeId: initiative.id,
          }}
          initiativeVersion={initiative.version}
          viewerId={viewerId}
          state={initiative.state}
        />
        <section aria-labelledby="curve-initiative-gates-title" className="border-t border-subtle pt-5">
          <h3 id="curve-initiative-gates-title" className="text-13 font-semibold text-primary">
            Review responsibilities
          </h3>
          <p className="mt-1 text-12 text-secondary">
            Assignments identify reviewers. They are not approval decisions.
          </p>
          <ul className="mt-4 divide-y divide-subtle">
            {initiativeApproverRoles.map((role) => {
              const assignment = initiative.gate_assignments.find(
                (entry) => entry.gate_type === role.gate && !entry.valid_until
              );
              const member = assignment ? members.get(assignment.approver.actor_id) : undefined;
              return (
                <li key={role.gate} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
                  <InitiativeAvatar member={member} />
                  <div className="min-w-0">
                    <p className="text-12 font-semibold text-primary">{role.label}</p>
                    <p className="mt-1 text-12 break-words text-secondary">
                      {assignment
                        ? member
                          ? memberDisplayName(member)
                          : "Assigned member unavailable"
                        : "No current assignment"}
                    </p>
                    <p className="mt-1 text-12 leading-5 text-secondary">{role.responsibility}</p>
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
        <details className="border-t border-subtle pt-4">
          <summary className="focus-visible:outline-accent-primary cursor-pointer rounded-sm py-1 text-12 font-medium text-primary focus-visible:outline-2">
            Initiative details and activity
          </summary>
          <dl className="mt-4 grid gap-4 text-12 sm:grid-cols-2" aria-label="Initiative metadata">
            <div>
              <dt className="text-secondary">Business intent</dt>
              <dd className="mt-1 text-primary">{initiativeBusinessIntentLabel(initiative.business_intent)}</dd>
            </div>
            <div>
              <dt className="text-secondary">Creator</dt>
              <dd className="mt-1 text-primary">{memberDisplayName(members.get(initiative.creator.actor_id))}</dd>
            </div>
            <div>
              <dt className="text-secondary">Record version</dt>
              <dd className="mt-1 text-primary">v{initiative.version}</dd>
              <dd className="mt-1 text-secondary">Prevents overwriting a newer update.</dd>
            </div>
            <div>
              <dt className="text-secondary">External resource</dt>
              <dd className="mt-1 text-primary">
                {initiative.first_external_resource_at
                  ? "Resource recorded; document access not verified"
                  : "None recorded"}
              </dd>
            </div>
            <div>
              <dt className="text-secondary">Delivery projects</dt>
              <dd className="mt-1 text-primary">Links are not loaded in this view</dd>
            </div>
          </dl>
          <h3 className="mt-5 text-12 font-semibold text-primary">Lifecycle activity</h3>
          <p className="mt-2 text-12 text-secondary">
            Last updated {calculateTimeAgo(initiative.updated_at)} · Created {calculateTimeAgo(initiative.created_at)}
          </p>
        </details>
        {initiative.state !== "CANCELLED" && (
          <details className="border-t border-subtle pt-4">
            <summary className="focus-visible:outline-accent-primary cursor-pointer rounded-sm py-1 text-12 font-medium text-primary focus-visible:outline-2">
              Manage Initiative
            </summary>
            <p className="mt-3 text-12 leading-5 text-secondary">
              Pause to keep the work recoverable. Cancellation is permanent for this Initiative. Both require a reason.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {(isDraft || initiative.state === "ALIGNING") && (
                <Button size="lg" variant="neutral-primary" disabled={!canMutate} onClick={() => onAction("pause")}>
                  Pause
                </Button>
              )}
              <Button size="lg" variant="neutral-primary" disabled={!canMutate} onClick={() => onAction("cancel")}>
                Cancel
              </Button>
            </div>
          </details>
        )}
      </div>
    </article>
  );
}

function InitiativeEditDialog({
  initiative,
  isSubmitting,
  onClose,
  onUpdate,
}: {
  initiative: ICurveInitiative;
  isSubmitting: boolean;
  onClose: () => void;
  onUpdate: (payload: ICurveInitiativeDraftUpdateRequest) => Promise<boolean>;
}) {
  const [title, setTitle] = useState(initiative.title);
  const [keyword, setKeyword] = useState(initiative.keyword);
  const [riskTier, setRiskTier] = useState<TCurveInitiativeRiskTier>(initiative.risk_tier);
  const [businessIntent, setBusinessIntent] = useState<TCurveInitiativeBusinessIntent | "">(
    initiative.business_intent ?? ""
  );
  const [description, setDescription] = useState(initiative.description.body);
  const [errors, setErrors] = useState<Partial<Record<"title" | "keyword" | "description", string>>>({});
  const titleRef = useRef<HTMLInputElement>(null);

  const submit = async () => {
    const nextErrors: typeof errors = {};
    if (!title.trim()) nextErrors.title = "Enter a title.";
    if (!initiativeKeywordPattern.test(keyword.trim())) {
      nextErrors.keyword = "Use letters, digits, and hyphens only, starting with a letter or digit.";
    }
    if (!description.trim()) nextErrors.description = "Describe the problem and intended outcome.";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) {
      if (nextErrors.title) titleRef.current?.focus();
      return;
    }

    const succeeded = await onUpdate({
      title: title.trim(),
      keyword: keyword.trim(),
      risk_tier: riskTier,
      business_intent: businessIntent || null,
      description: { schema_version: "1.0", format: "MARKDOWN", body: description.trim() },
    });
    if (succeeded) onClose();
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Panel initialFocus={titleRef} width={EDialogWidth.LG}>
        <div className="p-5 sm:p-6">
          <Dialog.Title>Edit Initiative</Dialog.Title>
          <p className="mt-2 text-12 leading-5 text-secondary">
            Update the definition while this Initiative remains in Draft.
          </p>

          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <label className="block text-12 font-semibold text-primary sm:col-span-2">
              Title
              <input
                ref={titleRef}
                value={title}
                onChange={(event) => {
                  setTitle(event.target.value);
                  setErrors((current) => ({ ...current, title: undefined }));
                }}
                className={cn(
                  filterClassName,
                  "mt-1 w-full",
                  errors.title && "border-danger-strong focus:border-danger-strong focus:ring-danger-subtle"
                )}
                maxLength={255}
                aria-invalid={!!errors.title}
                aria-describedby={errors.title ? "curve-initiative-edit-title-error" : undefined}
              />
              {errors.title && (
                <span
                  id="curve-initiative-edit-title-error"
                  role="alert"
                  className="mt-1 block text-12 text-danger-primary"
                >
                  {errors.title}
                </span>
              )}
            </label>

            <label className="block text-12 font-semibold text-primary">
              Keyword
              <input
                value={keyword}
                onChange={(event) => {
                  setKeyword(event.target.value);
                  setErrors((current) => ({ ...current, keyword: undefined }));
                }}
                className={cn(
                  filterClassName,
                  "mt-1 w-full",
                  errors.keyword && "border-danger-strong focus:border-danger-strong focus:ring-danger-subtle"
                )}
                maxLength={50}
                aria-invalid={!!errors.keyword}
                aria-describedby="curve-initiative-edit-keyword-help"
              />
              <span
                id="curve-initiative-edit-keyword-help"
                className={cn(
                  "font-normal mt-1 block text-11",
                  errors.keyword ? "text-danger-primary" : "text-secondary"
                )}
              >
                {errors.keyword ?? "Letters, digits, and hyphens; up to 50 characters."}
              </span>
            </label>

            <label className="block text-12 font-semibold text-primary">
              Risk tier
              <select
                value={riskTier}
                onChange={(event) => setRiskTier(event.target.value as TCurveInitiativeRiskTier)}
                className={`${filterClassName} mt-1 w-full`}
              >
                <option value="LOW">Low</option>
                <option value="STANDARD">Standard</option>
                <option value="HIGH">High</option>
              </select>
            </label>

            <label className="block text-12 font-semibold text-primary sm:col-span-2">
              Business intent
              <select
                value={businessIntent}
                onChange={(event) => setBusinessIntent(event.target.value as TCurveInitiativeBusinessIntent | "")}
                className={`${filterClassName} mt-1 w-full`}
              >
                <option value="">Not set</option>
                {initiativeBusinessIntentOptions.map(({ value, label }) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              <span className="font-normal mt-1 block text-11 text-secondary">Required before alignment starts.</span>
            </label>

            <label className="block text-12 font-semibold text-primary sm:col-span-2">
              Problem and intended outcome
              <textarea
                value={description}
                onChange={(event) => {
                  setDescription(event.target.value);
                  setErrors((current) => ({ ...current, description: undefined }));
                }}
                className={cn(
                  filterClassName,
                  "mt-1 min-h-28 w-full resize-y py-2",
                  errors.description && "border-danger-strong focus:border-danger-strong focus:ring-danger-subtle"
                )}
                maxLength={10000}
                aria-invalid={!!errors.description}
                aria-describedby={errors.description ? "curve-initiative-edit-description-error" : undefined}
              />
              {errors.description && (
                <span
                  id="curve-initiative-edit-description-error"
                  role="alert"
                  className="mt-1 block text-12 text-danger-primary"
                >
                  {errors.description}
                </span>
              )}
            </label>
          </div>

          <div className="mt-6 flex justify-end gap-2">
            <Button size="lg" variant="neutral-primary" disabled={isSubmitting} onClick={onClose}>
              Cancel
            </Button>
            <Button size="lg" loading={isSubmitting} onClick={() => void submit()}>
              Save changes
            </Button>
          </div>
        </div>
      </Dialog.Panel>
    </Dialog>
  );
}

export const InitiativeWorkspace = observer(function InitiativeWorkspace({ workspaceSlug }: { workspaceSlug: string }) {
  const userStore = useUser();
  const viewerId = userStore.isAuthenticated ? userStore.data?.id : undefined;
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
    updateInitiativeDraft,
    acceptRefinement,
    pauseInitiative,
    resumeInitiative,
    cancelInitiative,
    refreshSelected,
    refresh,
  } = useCurveInitiatives(workspaceSlug);
  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState<"ALL" | TCurveInitiativeListState>(() =>
    initialInitiativeFilter("state", ["ALL", "DRAFT", "ALIGNING", "PAUSED", "CANCELLED"] as const, "ALL")
  );
  const [riskFilter, setRiskFilter] = useState<"ALL" | TCurveInitiativeRiskTier>("ALL");
  const [summaryFilter, setSummaryFilter] = useState<TSummaryFilter | undefined>(initialSummaryFilter);
  const [createOpen, setCreateOpen] = useState(false);
  const [createRevision, setCreateRevision] = useState(0);
  const [editOpen, setEditOpen] = useState(false);
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
      [
        initiative.title,
        initiative.keyword,
        initiative.description.body,
        product?.name,
        initiativeBusinessIntentLabel(initiative.business_intent),
      ]
        .filter(Boolean)
        .some((value) => value?.toLowerCase().includes(normalizedSearch));
    const matchesState = stateFilter === "ALL" || initiative.state === stateFilter;
    const matchesRisk = riskFilter === "ALL" || initiative.risk_tier === riskFilter;
    const matchesSummary =
      !summaryFilter ||
      (summaryFilter === "ACTIVE" && ["DRAFT", "ALIGNING"].includes(initiative.state)) ||
      (summaryFilter === "PAUSED" && initiative.state === "PAUSED") ||
      (summaryFilter === "NEEDS_ATTENTION" &&
        initiative.risk_tier === "HIGH" &&
        ["DRAFT", "ALIGNING"].includes(initiative.state));
    return matchesSearch && matchesState && matchesRisk && matchesSummary;
  });
  const visibleSelected = visibleInitiatives.find(({ id }) => id === selectedInitiative?.id);
  const filtered = !!normalizedSearch || stateFilter !== "ALL" || riskFilter !== "ALL" || !!summaryFilter;
  const activeCount = initiatives.filter(({ state }) => state === "DRAFT" || state === "ALIGNING").length;
  const pausedCount = initiatives.filter(({ state }) => state === "PAUSED").length;
  const needsAttentionCount = initiatives.filter(
    ({ risk_tier, state }) => risk_tier === "HIGH" && ["DRAFT", "ALIGNING"].includes(state)
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
      reasonRef.current?.focus();
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
    if (succeeded) {
      setAnnouncement("Initiative created in Draft state.");
      setCreateRevision((revision) => revision + 1);
    }
    return succeeded;
  };

  const handleAcceptRefinement = async () => {
    const succeeded = await acceptRefinement();
    if (succeeded) setAnnouncement("Initiative refinement accepted. State changed to Aligning.");
  };

  const handleUpdateDraft = async (payload: ICurveInitiativeDraftUpdateRequest) => {
    const succeeded = await updateInitiativeDraft(payload);
    if (succeeded) setAnnouncement("Initiative changes saved.");
    return succeeded;
  };

  const toggleSummaryFilter = (filter: TSummaryFilter) => {
    setSummaryFilter((current) => (current === filter ? undefined : filter));
    setStateFilter("ALL");
    setRiskFilter("ALL");
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
            <span className="rounded-full bg-layer-1 px-2 py-1 text-10 font-medium text-secondary">Manual-first</span>
          </div>
          <h1 className="mt-1 text-32 leading-tight font-semibold tracking-[-0.025em] text-primary">Initiatives</h1>
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

      <section className="mt-5 flex flex-wrap gap-2" aria-label="Loaded Initiative portfolio summary">
        {[
          { id: "ACTIVE" as const, label: "Active", value: activeCount, detail: "Draft or aligning" },
          { id: "PAUSED" as const, label: "Paused", value: pausedCount, detail: "Explicitly recoverable" },
          {
            id: "NEEDS_ATTENTION" as const,
            label: "Needs attention",
            value: needsAttentionCount,
            detail: "High-risk active work",
          },
        ].map(({ id, label, value, detail }) => (
          <button
            type="button"
            key={label}
            onClick={() => toggleSummaryFilter(id)}
            className={cn(
              "min-h-10 rounded-md border border-subtle px-3 py-2 text-left transition-colors hover:bg-layer-1 focus-visible:ring-2 focus-visible:ring-accent-strong focus-visible:outline-none",
              summaryFilter === id && "bg-accent-subtle"
            )}
            title={detail}
            aria-label={`Filter Initiatives: ${label}`}
            aria-pressed={summaryFilter === id}
          >
            <div className="flex items-baseline gap-2">
              <p className="text-12 font-semibold text-primary tabular-nums">{value}</p>
              <p className="text-12 text-secondary">{label}</p>
            </div>
          </button>
        ))}
      </section>

      {problem && (
        <div
          role={isConflict ? "status" : "alert"}
          aria-label={isConflict ? "Initiative refresh notice" : undefined}
          className={cn(
            "mt-5 flex flex-col justify-between gap-3 rounded-lg border p-4 sm:flex-row sm:items-center",
            isConflict ? "border-warning-subtle bg-warning-subtle" : "border-danger-subtle bg-danger-subtle"
          )}
        >
          <div className="flex items-start gap-3">
            <TriangleAlert
              className={cn("mt-0.5 size-4 shrink-0", isConflict ? "text-warning-primary" : "text-danger-primary")}
              aria-hidden="true"
            />
            <div>
              <p className={cn("text-13 font-semibold", isConflict ? "text-warning-primary" : "text-danger-primary")}>
                {problem.title}
              </p>
              {isConflict ? (
                <p className="mt-1 text-11 text-warning-primary">
                  Refresh to load the latest confirmed details. Your current view has not changed.
                </p>
              ) : (
                <p className="mt-1 text-11 text-danger-secondary">
                  The last confirmed workspace state remains visible.
                  {problem.correlation_id ? ` Reference ${problem.correlation_id}.` : ""}
                </p>
              )}
            </div>
          </div>
          <Button
            size="lg"
            variant="neutral-primary"
            prependIcon={<RefreshCw />}
            onClick={() => void (isConflict ? refreshSelected() : refresh())}
          >
            {isConflict ? "Refresh Initiative" : "Try again"}
          </Button>
        </div>
      )}

      <section className="mt-4 border-b border-subtle" aria-label="Initiative filters">
        <div className="grid gap-3 pb-4 md:grid-cols-[minmax(0,1fr)_10rem_10rem_auto]">
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
              onChange={(event) => {
                setStateFilter(event.target.value as typeof stateFilter);
                setSummaryFilter(undefined);
              }}
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
              onChange={(event) => {
                setRiskFilter(event.target.value as typeof riskFilter);
                setSummaryFilter(undefined);
              }}
              className={`${filterClassName} w-full`}
            >
              <option value="ALL">All risk tiers</option>
              <option value="LOW">Low risk</option>
              <option value="STANDARD">Standard risk</option>
              <option value="HIGH">High risk</option>
            </select>
          </label>
          <p className="self-center text-12 text-secondary md:text-right" role="status">
            Showing {visibleInitiatives.length} of {initiatives.length}
            {nextCursor ? " · more available" : ""}
            {filtered && (
              <button
                type="button"
                className="focus-visible:outline-accent-primary ml-2 min-h-10 rounded-sm px-1 font-medium text-accent-primary focus-visible:outline-2"
                onClick={() => {
                  setSearch("");
                  setStateFilter("ALL");
                  setRiskFilter("ALL");
                  setSummaryFilter(undefined);
                }}
              >
                Clear filters
              </button>
            )}
          </p>
        </div>
      </section>

      <div className="mt-4 grid overflow-hidden rounded-xl border border-subtle bg-surface-1 shadow-raised-100 lg:grid-cols-[minmax(16rem,0.65fr)_minmax(0,1.35fr)]">
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
              workspaceSlug={workspaceSlug}
              viewerId={viewerId}
              key={visibleSelected.id}
              initiative={visibleSelected}
              product={productMap.get(visibleSelected.product_id)}
              members={memberMap}
              etag={selectedEtag}
              isMutating={isMutating}
              onAccept={() => void handleAcceptRefinement()}
              onEdit={() => setEditOpen(true)}
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

      <InitiativeCreateDrawer
        key={createRevision}
        open={createOpen}
        products={products}
        members={activeMembers}
        isSubmitting={isMutating}
        onClose={closeCreate}
        onCreate={handleCreate}
      />

      {editOpen && selectedInitiative?.state === "DRAFT" && !selectedInitiative.first_external_resource_at && (
        <InitiativeEditDialog
          key={`${selectedInitiative.id}:${selectedInitiative.version}`}
          initiative={selectedInitiative}
          isSubmitting={isMutating}
          onClose={() => setEditOpen(false)}
          onUpdate={handleUpdateDraft}
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
