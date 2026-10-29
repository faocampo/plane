/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent } from "react";
import { FileText, GitBranch, Plus } from "lucide-react";
import { Button } from "@makeplane/propel/components/button";
import type { TCurveInitiativeRiskTier } from "@plane/types";

type Choice = { id: string; name: string };
export type RoadmapItemDraft = {
  title: string;
  milestoneId: string;
  featureId: string;
  productReviewerId: string;
  technicalReviewerId: string;
  riskTier: TCurveInitiativeRiskTier;
};
export type ItemCreationState =
  | "ready"
  | "saving"
  | "unknown"
  | "failed"
  | "created"
  | "cancelled"
  | "checking"
  | "cancelling";
type Props = {
  milestones: Choice[];
  features: Choice[];
  reviewers: Choice[];
  selectedMilestoneId: string;
  canCreate: boolean;
  checkingAccess?: boolean;
  canRecover?: boolean;
  canCancel?: boolean;
  onCancel?: () => Promise<void>;
  state: ItemCreationState;
  onCreate: (draft: RoadmapItemDraft) => Promise<void>;
  onRetry: () => Promise<void>;
};
const inputClass =
  "mt-2 min-h-11 w-full rounded-md border border-subtle bg-surface-1 px-3 py-2 text-14 text-primary outline-none focus:border-accent-primary focus:ring-2 focus:ring-accent-subtle disabled:cursor-not-allowed disabled:bg-layer-1 disabled:text-tertiary";
const roles = [
  { field: "productReviewerId", label: "Product reviewer", hint: "Approves the PRD", Icon: FileText },
  {
    field: "technicalReviewerId",
    label: "Technical reviewer",
    hint: "Approves the implementation plan",
    Icon: GitBranch,
  },
] as const;

/** Mount with a new key when the actor or Roadmap changes so draft input stays scoped. */
export function RoadmapItemCreateForm({
  milestones,
  features,
  reviewers,
  selectedMilestoneId,
  canCreate,
  checkingAccess = false,
  canRecover = canCreate,
  canCancel = false,
  onCancel,
  state,
  onCreate,
  onRetry,
}: Props) {
  const prefix = useId();
  const form = useRef<HTMLFormElement>(null);
  const inFlight = useRef(false);
  const [pending, setPending] = useState(false);
  const [unexpectedFailure, setUnexpectedFailure] = useState(false);
  const [errors, setErrors] = useState<Partial<Record<keyof RoadmapItemDraft, string>>>({});
  const [draft, setDraft] = useState<RoadmapItemDraft>({
    title: "",
    milestoneId: selectedMilestoneId,
    featureId: features.length === 1 ? features[0].id : "",
    productReviewerId: "",
    technicalReviewerId: "",
    riskTier: "STANDARD",
  });
  const busy = pending || state === "saving" || state === "checking" || state === "cancelling";
  useEffect(() => {
    if (state === "cancelled" && canCreate && !busy)
      form.current?.querySelector<HTMLInputElement>('input[name="title"]')?.focus();
  }, [state, canCreate, busy]);
  const locked = busy || state === "unknown" || state === "created" || !canCreate;
  useEffect(() => {
    if (!busy && state !== "unknown" && !unexpectedFailure) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [busy, state, unexpectedFailure]);
  const update = <K extends keyof RoadmapItemDraft>(field: K, value: RoadmapItemDraft[K]) => {
    setDraft((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: undefined }));
  };
  const error = (field: keyof RoadmapItemDraft) =>
    errors[field] ? (
      <p id={`${prefix}-${field}-error`} className="mt-2 text-12 text-danger-primary">
        {errors[field]}
      </p>
    ) : null;
  const describedBy = (field: keyof RoadmapItemDraft) => (errors[field] ? `${prefix}-${field}-error` : undefined);
  const run = async (work: () => Promise<void>) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    setUnexpectedFailure(false);
    try {
      await work();
    } catch {
      setUnexpectedFailure(true);
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (locked || unexpectedFailure || inFlight.current) return;
    const next: typeof errors = {};
    if (!draft.title.trim()) next.title = "Give this item a name.";
    if (!milestones.some(({ id }) => id === draft.milestoneId)) next.milestoneId = "Choose an available milestone.";
    if (!features.some(({ id }) => id === draft.featureId)) next.featureId = "Choose an available Feature.";
    for (const { field } of roles)
      if (!reviewers.some(({ id }) => id === draft[field])) next[field] = "Choose an active reviewer.";
    if (draft.riskTier !== "LOW" && draft.productReviewerId && draft.productReviewerId === draft.technicalReviewerId)
      next.technicalReviewerId = "Choose a different person for Technical review at Standard or High risk.";
    setErrors(next);
    const first = Object.keys(next)[0];
    if (first) {
      form.current?.querySelector<HTMLElement>(`[name="${first}"]`)?.focus();
      return;
    }
    await run(() => onCreate({ ...draft, title: draft.title.trim() }));
  };
  const uncertain = state === "unknown" || state === "checking" || state === "cancelling" || unexpectedFailure;
  return (
    <form
      ref={form}
      onSubmit={submit}
      noValidate
      aria-busy={busy}
      className="space-y-7 text-primary [&_button]:min-h-11"
    >
      <div>
        <h2 className="text-20 font-semibold">Create item</h2>
        <p className="mt-2 max-w-prose text-14 text-secondary">
          Name the work and choose its two reviewers. Add your PRD after creation.
        </p>
      </div>
      <div aria-live="polite">
        {state === "cancelled" && (
          <p role="status" className="text-14 text-secondary">
            The previous attempt was cancelled. Review your details and create the item when you’re ready.
          </p>
        )}
        {state === "created" && (
          <p role="status" className="text-14 text-success-primary">
            Item created. Add your PRD next.
          </p>
        )}
        {uncertain && (
          <div role="alert" className="space-y-3 rounded-md bg-warning-subtle p-4 text-14 text-primary">
            <p>
              We couldn’t confirm whether this item was created. Use Recover creation to check the original request. New
              creation stays locked until its outcome is confirmed.
            </p>
            <Button
              type="button"
              variant="primary"
              size="lg"
              stretch="auto"
              disabled={busy || !canRecover}
              onClick={() => {
                void run(onRetry);
              }}
              label={state === "checking" ? "Checking creation…" : "Recover creation"}
            />
            {canCancel && onCancel && (
              <div className="space-y-2">
                <p>To start again, cancel this attempt. If the item was already created, we’ll open it.</p>
                <Button
                  type="button"
                  variant="secondary"
                  size="lg"
                  stretch="auto"
                  disabled={busy}
                  onClick={() => {
                    void run(onCancel);
                  }}
                  label={state === "cancelling" ? "Cancelling attempt…" : "Cancel attempt"}
                />
              </div>
            )}
          </div>
        )}
        {state === "failed" && !uncertain && (
          <p role="alert" className="text-14 text-danger-primary">
            The item could not be created. Review your selections and try again.
          </p>
        )}
        {!canCreate && !uncertain && (
          <p role="status" className="text-14 text-secondary">
            {checkingAccess
              ? "Checking your access…"
              : "Creation requires current access as the Roadmap owner. Refresh the Roadmap to check your access."}
          </p>
        )}
      </div>
      <fieldset disabled={locked || uncertain} className="space-y-6">
        <legend className="sr-only">Item details and reviewers</legend>
        <div>
          <label htmlFor={`${prefix}-title`} className="text-14 font-semibold">
            Item name
          </label>
          <input
            id={`${prefix}-title`}
            name="title"
            value={draft.title}
            maxLength={255}
            required
            onChange={(e) => update("title", e.target.value)}
            className={inputClass}
            aria-invalid={!!errors.title}
            aria-describedby={describedBy("title")}
          />
          {error("title")}
        </div>
        <div className="grid gap-6 sm:grid-cols-2">
          {(
            [
              { field: "milestoneId", label: "Milestone", choices: milestones },
              { field: "featureId", label: "Feature", choices: features },
            ] as const
          ).map(({ field, label, choices }) => (
            <div key={field}>
              <label htmlFor={`${prefix}-${field}`} className="text-14 font-semibold">
                {label}
              </label>
              <select
                id={`${prefix}-${field}`}
                name={field}
                value={draft[field]}
                required
                onChange={(e) => update(field, e.target.value)}
                className={inputClass}
                aria-invalid={!!errors[field]}
                aria-describedby={describedBy(field)}
              >
                <option value="">Choose a {label.toLowerCase()}</option>
                {choices.map(({ id, name }) => (
                  <option key={id} value={id}>
                    {name}
                  </option>
                ))}
              </select>
              {error(field)}
            </div>
          ))}
        </div>
        <div className="border-t border-subtle pt-6">
          <h3 className="text-16 font-semibold">Two approval stages</h3>
          <div className="mt-5 grid gap-6 sm:grid-cols-2">
            {roles.map(({ field, label, hint, Icon }) => (
              <div key={field}>
                <label htmlFor={`${prefix}-${field}`} className="flex items-center gap-2 text-14 font-semibold">
                  <Icon aria-hidden="true" className="size-4 text-accent-primary" />
                  {label}
                </label>
                <p id={`${prefix}-${field}-hint`} className="mt-1 text-12 text-secondary">
                  {hint}
                </p>
                <select
                  id={`${prefix}-${field}`}
                  name={field}
                  required
                  value={draft[field]}
                  onChange={(e) => update(field, e.target.value)}
                  className={inputClass}
                  aria-invalid={!!errors[field]}
                  aria-describedby={[`${prefix}-${field}-hint`, describedBy(field)].filter(Boolean).join(" ")}
                >
                  <option value="">Choose a reviewer</option>
                  {reviewers.map(({ id, name }) => (
                    <option key={id} value={id}>
                      {name}
                    </option>
                  ))}
                </select>
                {error(field)}
              </div>
            ))}
          </div>
        </div>
        <details>
          <summary className="focus-visible:outline-accent-primary min-h-11 cursor-pointer py-3 text-14 font-medium text-secondary focus-visible:outline-2">
            Risk level · {draft.riskTier.toLowerCase()}
          </summary>
          <label htmlFor={`${prefix}-riskTier`} className="text-14 font-semibold">
            Risk level
          </label>
          <select
            id={`${prefix}-riskTier`}
            name="riskTier"
            className={inputClass}
            value={draft.riskTier}
            onChange={(e) => update("riskTier", e.target.value as TCurveInitiativeRiskTier)}
          >
            <option value="LOW">Low</option>
            <option value="STANDARD">Standard</option>
            <option value="HIGH">High</option>
          </select>
          <p className="mt-2 text-12 text-secondary">Standard and High risk require two different reviewers.</p>
        </details>
      </fieldset>
      {!uncertain && state !== "created" && (
        <Button
          type="submit"
          variant="primary"
          size="lg"
          stretch="auto"
          disabled={locked}
          icon={<Plus aria-hidden="true" className="size-4" />}
          label={busy ? "Creating item…" : "Create item"}
        />
      )}
    </form>
  );
}
