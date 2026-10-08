/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { type FormEvent, useRef, useState } from "react";
import { X } from "lucide-react";

import { Drawer, DrawerPanel, DrawerTitle } from "@makeplane/propel/components/drawer";
import type {
  ICurveInitiativeCreateRequest,
  ICurveProduct,
  IWorkspaceMember,
  TCurveInitiativeBusinessIntent,
  TCurveInitiativeRiskTier,
} from "@plane/types";
import { Button } from "@makeplane/propel/components/button";
import { cn } from "@plane/utils";
import { initiativeApproverRoles, initiativeBusinessIntentOptions, memberDisplayName } from "./initiative-ui";

type TFormField =
  | "title"
  | "product"
  | "keyword"
  | "description"
  | "productApprover"
  | "technicalApprover"
  | "codeApprover";
type TFormErrors = Partial<Record<TFormField, string>>;
const approverFields = ["productApprover", "technicalApprover", "codeApprover"] as const;
const inputClassName =
  "mt-1 min-h-10 w-full rounded-md border border-subtle bg-surface-1 px-3 py-2 text-13 text-primary outline-none transition focus:border-accent-primary focus:ring-2 focus:ring-accent-subtle disabled:cursor-not-allowed disabled:bg-layer-1 disabled:text-tertiary";
const fieldLabelClassName = "text-12 font-semibold text-primary";
const errorTextClassName = "mt-1 text-12 font-medium text-danger-primary";
const fieldClassName = (hasError: boolean) =>
  cn(inputClassName, hasError && "border-danger-strong focus:border-danger-strong focus:ring-danger-subtle");

export function InitiativeCreateDrawer({
  open,
  products,
  members,
  isSubmitting,
  onClose,
  onCreate,
}: {
  open: boolean;
  products: ICurveProduct[];
  members: IWorkspaceMember[];
  isSubmitting: boolean;
  onClose: () => void;
  onCreate: (payload: ICurveInitiativeCreateRequest) => Promise<boolean>;
}) {
  const [step, setStep] = useState<"definition" | "reviewers">("definition");
  const [title, setTitle] = useState("");
  const [productId, setProductId] = useState(products.length === 1 ? products[0].id : "");
  const [keyword, setKeyword] = useState("");
  const [keywordEdited, setKeywordEdited] = useState(false);
  const [description, setDescription] = useState("");
  const [riskTier, setRiskTier] = useState<TCurveInitiativeRiskTier>("STANDARD");
  const [businessIntent, setBusinessIntent] = useState<TCurveInitiativeBusinessIntent | "">("");
  const [approverIds, setApproverIds] = useState(["", "", ""]);
  const [errors, setErrors] = useState<TFormErrors>({});
  const [submissionFailed, setSubmissionFailed] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);
  const formRef = useRef<HTMLFormElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const stepTitleRef = useRef<HTMLHeadingElement>(null);
  const busy = isSubmitting || pending;
  const selectedBusinessIntent = initiativeBusinessIntentOptions.find(({ value }) => value === businessIntent);

  const focusField = (field: TFormField) => {
    window.setTimeout(() => formRef.current?.querySelector<HTMLElement>(`#curve-initiative-${field}`)?.focus(), 0);
  };
  const definitionErrors = (): TFormErrors => {
    const result: TFormErrors = {};
    if (!title.trim()) result.title = "Enter a title.";
    if (!products.some(({ id }) => id === productId)) result.product = "Choose an active Product.";
    if (!description.trim()) result.description = "Describe the problem and intended outcome.";
    if (!/^[A-Za-z0-9][A-Za-z0-9-]{0,49}$/.test(keyword))
      result.keyword = "Use 1–50 letters, numbers, or hyphens, starting with a letter or number.";
    return result;
  };
  const showErrors = (nextErrors: TFormErrors) => {
    setErrors(nextErrors);
    const first = Object.keys(nextErrors)[0] as TFormField | undefined;
    if (!first) return false;
    if (![...approverFields].includes(first as (typeof approverFields)[number])) setStep("definition");
    if (nextErrors.keyword) setDetailsOpen(true);
    focusField(first);
    return true;
  };
  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy || inFlight.current) return;
    setSubmissionFailed(false);
    const nextErrors = definitionErrors();
    if (step === "definition") {
      if (showErrors(nextErrors)) return;
      setStep("reviewers");
      window.setTimeout(() => {
        stepTitleRef.current?.focus({ preventScroll: true });
        if (panelRef.current) panelRef.current.scrollTop = 0;
      }, 0);
      return;
    }
    approverIds.forEach((id, index) => {
      if (!members.some(({ member }) => member.id === id))
        nextErrors[approverFields[index]] = "Choose an active human.";
    });
    if (riskTier !== "LOW" && approverIds.every(Boolean) && new Set(approverIds).size !== 3) {
      approverFields.forEach((field) => {
        nextErrors[field] = "Choose three distinct active humans for Standard or High risk.";
      });
    }
    if (showErrors(nextErrors)) return;
    inFlight.current = true;
    setPending(true);
    try {
      const succeeded = await onCreate({
        product_id: productId,
        mode: "STANDALONE",
        roadmap_item_id: null,
        keyword,
        title: title.trim(),
        description: { schema_version: "1.0", format: "MARKDOWN", body: description.trim() },
        risk_tier: riskTier,
        business_intent: businessIntent || null,
        gate_assignments: initiativeApproverRoles.map((role, index) => ({
          gate_type: role.gate,
          approver_user_id: approverIds[index],
        })),
      });
      if (succeeded) onClose();
      else setSubmissionFailed(true);
    } catch {
      setSubmissionFailed(true);
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  };
  const errorFor = (field: TFormField) =>
    errors[field] ? (
      <p id={`curve-initiative-${field}-error`} className={errorTextClassName}>
        {errors[field]}
      </p>
    ) : null;
  const clearError = (field: TFormField) => setErrors((current) => ({ ...current, [field]: undefined }));

  return (
    <Drawer modal swipeDirection="right" open={open} onOpenChange={(nextOpen) => !nextOpen && !busy && onClose()}>
      <DrawerPanel initialFocus={titleRef} side="end" size="md" variant="overlay" backdrop>
        <div ref={panelRef} data-testid="initiative-creation-scroll" className="h-full overflow-y-auto">
          <form ref={formRef} noValidate onSubmit={handleSubmit} className="flex min-h-full flex-col" aria-busy={busy}>
            <header className="sticky top-0 z-10 border-b border-subtle bg-surface-1 px-5 py-5 sm:px-6">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <DrawerTitle>New Initiative</DrawerTitle>
                  <p className="mt-1 text-12 text-secondary">Define an outcome, then choose who reviews it.</p>
                </div>
                <button
                  type="button"
                  onClick={onClose}
                  disabled={busy}
                  className="focus-visible:outline-accent-primary grid size-10 shrink-0 place-items-center rounded-md text-secondary hover:bg-layer-1 focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50"
                  aria-label="Close new Initiative"
                >
                  <X className="size-4" aria-hidden="true" />
                </button>
              </div>
              <ol className="mt-5 flex gap-6 text-12" aria-label="Creation steps">
                <li
                  aria-current={step === "definition" ? "step" : undefined}
                  className={step === "definition" ? "font-semibold text-primary" : "text-secondary"}
                >
                  1. Define outcome
                </li>
                <li
                  aria-current={step === "reviewers" ? "step" : undefined}
                  className={step === "reviewers" ? "font-semibold text-primary" : "text-secondary"}
                >
                  2. Assign reviewers
                </li>
              </ol>
            </header>
            <div className="flex-1 space-y-5 px-5 py-6 sm:px-6">
              <p className="sr-only" role="alert">
                {Object.values(errors).some(Boolean) ? "Review the highlighted fields." : ""}
              </p>
              {submissionFailed && (
                <div
                  role="alert"
                  className="rounded-md border border-danger-subtle bg-danger-subtle p-3 text-12 text-danger-primary"
                >
                  The Initiative could not be created. Your input remains available. Check your connection or refresh
                  the workspace, then try again.
                </div>
              )}
              {step === "definition" ? (
                <>
                  <p className="text-12 text-secondary">
                    Title, Product and outcome are required. You can refine this Draft before alignment.
                  </p>
                  <div>
                    <label htmlFor="curve-initiative-title" className={fieldLabelClassName}>
                      Title
                    </label>
                    <input
                      ref={titleRef}
                      id="curve-initiative-title"
                      required
                      value={title}
                      onChange={(event) => {
                        setTitle(event.target.value);
                        clearError("title");
                        if (!keywordEdited)
                          setKeyword(
                            event.target.value
                              .toLowerCase()
                              .replace(/[^a-z0-9]+/g, "-")
                              .replace(/^-|-$/g, "")
                              .slice(0, 50)
                          );
                      }}
                      className={fieldClassName(!!errors.title)}
                      maxLength={255}
                      aria-invalid={!!errors.title}
                      aria-describedby={errors.title ? "curve-initiative-title-error" : undefined}
                    />
                    {errorFor("title")}
                  </div>
                  <div>
                    <label htmlFor="curve-initiative-product" className={fieldLabelClassName}>
                      Product
                    </label>
                    <select
                      id="curve-initiative-product"
                      required
                      value={productId}
                      onChange={(event) => {
                        setProductId(event.target.value);
                        clearError("product");
                      }}
                      className={fieldClassName(!!errors.product)}
                      aria-invalid={!!errors.product}
                      aria-describedby={errors.product ? "curve-initiative-product-error" : undefined}
                    >
                      <option value="">Choose a Product</option>
                      {products.map((product) => (
                        <option key={product.id} value={product.id}>
                          {product.name}
                        </option>
                      ))}
                    </select>
                    {errorFor("product")}
                  </div>
                  <div>
                    <label htmlFor="curve-initiative-description" className={fieldLabelClassName}>
                      Problem and intended outcome
                    </label>
                    <textarea
                      id="curve-initiative-description"
                      required
                      value={description}
                      onChange={(event) => {
                        setDescription(event.target.value);
                        clearError("description");
                      }}
                      className={`${fieldClassName(!!errors.description)} min-h-32 resize-y`}
                      maxLength={20000}
                      aria-invalid={!!errors.description}
                      aria-describedby={
                        errors.description ? "curve-initiative-description-error" : "curve-initiative-description-help"
                      }
                    />
                    <p id="curve-initiative-description-help" className="mt-1 text-12 leading-5 text-secondary">
                      What needs to change, and what would a good result look like?
                    </p>
                    {errorFor("description")}
                  </div>
                  <details
                    open={detailsOpen}
                    onToggle={(event) => setDetailsOpen(event.currentTarget.open)}
                    className="border-t border-subtle pt-4"
                  >
                    <summary className="focus-visible:outline-accent-primary cursor-pointer rounded-sm py-1 text-12 font-medium text-primary focus-visible:outline-2">
                      Keyword and business intent
                    </summary>
                    <div className="mt-4 space-y-4">
                      <div>
                        <label htmlFor="curve-initiative-keyword" className={fieldLabelClassName}>
                          Keyword
                        </label>
                        <input
                          id="curve-initiative-keyword"
                          required
                          value={keyword}
                          onChange={(event) => {
                            setKeyword(event.target.value);
                            setKeywordEdited(true);
                            clearError("keyword");
                          }}
                          className={fieldClassName(!!errors.keyword)}
                          maxLength={50}
                          aria-invalid={!!errors.keyword}
                          aria-describedby={
                            errors.keyword ? "curve-initiative-keyword-error" : "curve-initiative-keyword-help"
                          }
                        />
                        <p id="curve-initiative-keyword-help" className="mt-1 text-12 text-secondary">
                          Suggested from the title. Use letters, numbers and hyphens.
                        </p>
                        {errorFor("keyword")}
                      </div>
                      <div>
                        <label htmlFor="curve-initiative-business-intent" className={fieldLabelClassName}>
                          Business intent
                        </label>
                        <select
                          id="curve-initiative-business-intent"
                          value={businessIntent}
                          onChange={(event) =>
                            setBusinessIntent(event.target.value as TCurveInitiativeBusinessIntent | "")
                          }
                          className={inputClassName}
                          aria-describedby="curve-initiative-business-intent-help"
                        >
                          <option value="">Decide during Draft</option>
                          {initiativeBusinessIntentOptions.map(({ value, label }) => (
                            <option key={value} value={value}>
                              {label}
                            </option>
                          ))}
                        </select>
                        <p id="curve-initiative-business-intent-help" className="mt-1 text-12 leading-5 text-secondary">
                          {selectedBusinessIntent?.description ?? "Optional now. Required before starting alignment."}
                        </p>
                      </div>
                    </div>
                  </details>
                </>
              ) : (
                <>
                  <div>
                    <h2 ref={stepTitleRef} tabIndex={-1} className="text-16 font-semibold text-primary outline-none">
                      Who reviews this Initiative?
                    </h2>
                    <p className="mt-2 text-12 leading-5 text-secondary">
                      Choose a person for each required role. Assigning a reviewer does not approve any work.
                    </p>
                    <p className="mt-3 text-13 font-medium break-words text-primary">{title}</p>
                    <p className="mt-1 text-12 text-secondary">{products.find(({ id }) => id === productId)?.name}</p>
                  </div>
                  <div>
                    <label htmlFor="curve-initiative-risk" className={fieldLabelClassName}>
                      Risk tier
                    </label>
                    <select
                      id="curve-initiative-risk"
                      value={riskTier}
                      onChange={(event) => {
                        setRiskTier(event.target.value as TCurveInitiativeRiskTier);
                        setErrors({});
                      }}
                      className={inputClassName}
                      aria-describedby="curve-initiative-reviewer-rule"
                    >
                      <option value="LOW">Low</option>
                      <option value="STANDARD">Standard</option>
                      <option value="HIGH">High</option>
                    </select>
                    <p id="curve-initiative-reviewer-rule" className="mt-2 text-12 leading-5 text-secondary">
                      {riskTier === "LOW"
                        ? "One person can hold multiple roles at Low risk. All three roles still need an assignment."
                        : "Standard and High risk require three different people. Choose each reviewer explicitly."}
                    </p>
                  </div>
                  <fieldset className="space-y-5 border-t border-subtle pt-5" disabled={busy}>
                    <legend className="sr-only">Required reviewers</legend>
                    {initiativeApproverRoles.map((role, index) => {
                      const field = approverFields[index];
                      return (
                        <div key={field}>
                          <label htmlFor={`curve-initiative-${field}`} className={fieldLabelClassName}>
                            {role.label}
                          </label>
                          <p id={`curve-initiative-${field}-help`} className="mt-1 text-12 text-secondary">
                            {role.responsibility}
                          </p>
                          <select
                            id={`curve-initiative-${field}`}
                            required
                            value={approverIds[index]}
                            onChange={(event) => {
                              setApproverIds((current) =>
                                current.map((id, i) => (i === index ? event.target.value : id))
                              );
                              setErrors({});
                            }}
                            className={fieldClassName(!!errors[field])}
                            aria-invalid={!!errors[field]}
                            aria-describedby={`curve-initiative-${field}-help${errors[field] ? ` curve-initiative-${field}-error` : ""}`}
                          >
                            <option value="">Choose a reviewer</option>
                            {members.map((member) => (
                              <option key={member.member.id} value={member.member.id}>
                                {memberDisplayName(member)}
                              </option>
                            ))}
                          </select>
                          {errorFor(field)}
                        </div>
                      );
                    })}
                  </fieldset>
                  <p className="border-t border-subtle pt-4 text-12 leading-5 text-secondary">
                    Creates a Draft. Alignment and PRD approval happen separately.
                  </p>
                </>
              )}
            </div>
            <footer className="sticky bottom-0 flex flex-wrap items-center justify-end gap-2 border-t border-subtle bg-surface-1 px-5 py-4 sm:px-6">
              <Button
                type="button"
                size="lg"
                variant="secondary"
                disabled={busy}
                onClick={() => {
                  if (step === "reviewers") {
                    setStep("definition");
                    window.setTimeout(() => {
                      titleRef.current?.focus({ preventScroll: true });
                      if (panelRef.current) panelRef.current.scrollTop = 0;
                    }, 0);
                  } else onClose();
                }}
                stretch="auto"
                label={step === "reviewers" ? "Back" : "Close"}
              />
              <Button
                type="submit"
                size="lg"
                loading={busy}
                variant="primary"
                stretch="auto"
                label={step === "definition" ? "Continue to reviewers" : "Create Initiative"}
              />
            </footer>
          </form>
        </div>
      </DrawerPanel>
    </Drawer>
  );
}
