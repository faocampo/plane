/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { type FormEvent, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";

import { Dialog, EDialogWidth } from "@plane/propel/dialog";
import type {
  ICurveInitiativeCreateRequest,
  ICurveProduct,
  IWorkspaceMember,
  TCurveInitiativeRiskTier,
} from "@plane/types";
import { Button } from "@plane/ui";
import { memberDisplayName } from "./initiative-ui";

type TFormField =
  | "title"
  | "product"
  | "keyword"
  | "description"
  | "productApprover"
  | "technicalApprover"
  | "codeApprover";

type TFormErrors = Partial<Record<TFormField, string>>;

const inputClassName =
  "mt-1 min-h-10 w-full rounded-md border border-subtle bg-surface-1 px-3 py-2 text-13 text-primary outline-none transition focus:border-accent-primary focus:ring-2 focus:ring-accent-subtle disabled:cursor-not-allowed disabled:bg-layer-1 disabled:text-tertiary";

const fieldLabelClassName = "text-12 font-semibold text-primary";

const defaultApproverIds = (members: IWorkspaceMember[]) => [0, 1, 2].map((index) => members[index]?.member.id ?? "");

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
  const initialApprovers = useMemo(() => defaultApproverIds(members), [members]);
  const [title, setTitle] = useState("");
  const [productId, setProductId] = useState(products[0]?.id ?? "");
  const [keyword, setKeyword] = useState("");
  const [description, setDescription] = useState("");
  const [riskTier, setRiskTier] = useState<TCurveInitiativeRiskTier>("STANDARD");
  const [approverIds, setApproverIds] = useState(initialApprovers);
  const [errors, setErrors] = useState<TFormErrors>({});
  const [submissionFailed, setSubmissionFailed] = useState(false);
  const titleRef = useRef<HTMLInputElement>(null);
  const productRef = useRef<HTMLSelectElement>(null);
  const keywordRef = useRef<HTMLInputElement>(null);
  const descriptionRef = useRef<HTMLTextAreaElement>(null);
  const approverRefs = [
    useRef<HTMLSelectElement>(null),
    useRef<HTMLSelectElement>(null),
    useRef<HTMLSelectElement>(null),
  ];

  const focusField = (field: TFormField) => {
    const target =
      field === "title"
        ? titleRef.current
        : field === "product"
          ? productRef.current
          : field === "keyword"
            ? keywordRef.current
            : field === "description"
              ? descriptionRef.current
              : field === "productApprover"
                ? approverRefs[0].current
                : field === "technicalApprover"
                  ? approverRefs[1].current
                  : approverRefs[2].current;
    target?.focus();
  };

  const validate = () => {
    const nextErrors: TFormErrors = {};
    if (!title.trim()) nextErrors.title = "Enter a title.";
    if (!productId) nextErrors.product = "Choose an active Product.";
    if (!/^[A-Za-z0-9][A-Za-z0-9-]{0,49}$/.test(keyword))
      nextErrors.keyword = "Use 1–50 letters, numbers, or hyphens, starting with a letter or number.";
    if (!description.trim()) nextErrors.description = "Describe the problem and intended outcome.";

    const approverFields: TFormField[] = ["productApprover", "technicalApprover", "codeApprover"];
    approverIds.forEach((approverId, index) => {
      if (!approverId) nextErrors[approverFields[index] as TFormField] = "Choose an active human.";
    });
    if (riskTier !== "LOW" && new Set(approverIds.filter(Boolean)).size !== 3) {
      approverFields.forEach((field) => {
        nextErrors[field] = "Choose three distinct active humans for Standard or High risk.";
      });
    }

    setErrors(nextErrors);
    const firstError = Object.keys(nextErrors)[0] as TFormField | undefined;
    if (firstError) focusField(firstError);
    return Object.keys(nextErrors).length === 0;
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmissionFailed(false);
    if (!validate()) return;
    const succeeded = await onCreate({
      product_id: productId,
      mode: "STANDALONE",
      roadmap_item_id: null,
      keyword,
      title: title.trim(),
      description: {
        schema_version: "1.0",
        format: "MARKDOWN",
        body: description.trim(),
      },
      risk_tier: riskTier,
      gate_assignments: [
        { gate_type: "PRD_APPROVAL", approver_user_id: approverIds[0] ?? "" },
        { gate_type: "PLAN_APPROVAL", approver_user_id: approverIds[1] ?? "" },
        { gate_type: "CODE_READINESS", approver_user_id: approverIds[2] ?? "" },
      ],
    });
    if (succeeded) onClose();
    else setSubmissionFailed(true);
  };

  const setApprover = (index: number, value: string) => {
    setApproverIds((current) =>
      current.map((approverId, currentIndex) => (currentIndex === index ? value : approverId))
    );
    setErrors((current) => ({
      ...current,
      productApprover: undefined,
      technicalApprover: undefined,
      codeApprover: undefined,
    }));
  };

  const approverFields: Array<{ label: string; key: TFormField }> = [
    { label: "Product Approver", key: "productApprover" },
    { label: "Technical Approver", key: "technicalApprover" },
    { label: "Code Approver", key: "codeApprover" },
  ];
  const errorCount = Object.keys(errors).filter((field) => !!errors[field as TFormField]).length;

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => !nextOpen && onClose()}>
      <Dialog.Panel
        initialFocus={titleRef}
        width={EDialogWidth.XXL}
        className="!top-0 !right-0 !bottom-0 !left-auto h-dvh w-full !max-w-none !translate-x-0 !translate-y-0 overflow-y-auto rounded-none border-y-0 border-r-0 sm:w-[36rem]"
      >
        <form noValidate onSubmit={handleSubmit} className="flex min-h-full flex-col">
          <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-subtle bg-surface-1 px-5 py-5 sm:px-6">
            <div>
              <Dialog.Title className="text-20 leading-6">New Initiative</Dialog.Title>
              <p className="mt-1 text-12 text-secondary">
                Create one governed standalone Initiative under an active Product.
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="focus-visible:outline-accent-primary grid size-10 shrink-0 place-items-center rounded-md text-secondary hover:bg-layer-1 focus-visible:outline-2 focus-visible:outline-offset-2"
              aria-label="Close new Initiative"
            >
              <X className="size-4" aria-hidden="true" />
            </button>
          </div>

          <div className="flex-1 space-y-5 px-5 py-5 sm:px-6">
            <p className="sr-only" role="alert" aria-live="assertive">
              {errorCount > 0 ? `Review ${errorCount} invalid ${errorCount === 1 ? "field" : "fields"}.` : ""}
            </p>
            {submissionFailed && (
              <div
                role="alert"
                className="rounded-md border border-danger-subtle bg-danger-subtle p-3 text-12 text-danger-primary"
              >
                The Initiative could not be created. Your input remains available; review the message in the workspace
                and try again.
              </div>
            )}

            <div>
              <label htmlFor="curve-initiative-title" className={fieldLabelClassName}>
                Title <span className="text-danger-primary">*</span>
              </label>
              <input
                ref={titleRef}
                id="curve-initiative-title"
                value={title}
                onChange={(event) => {
                  setTitle(event.target.value);
                  setErrors((current) => ({ ...current, title: undefined }));
                }}
                className={inputClassName}
                maxLength={255}
                aria-invalid={!!errors.title}
                aria-describedby={errors.title ? "curve-initiative-title-error" : undefined}
              />
              {errors.title && (
                <p id="curve-initiative-title-error" className="mt-1 text-11 text-danger-primary">
                  {errors.title}
                </p>
              )}
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="curve-initiative-product" className={fieldLabelClassName}>
                  Product <span className="text-danger-primary">*</span>
                </label>
                <select
                  ref={productRef}
                  id="curve-initiative-product"
                  value={productId}
                  onChange={(event) => {
                    setProductId(event.target.value);
                    setErrors((current) => ({ ...current, product: undefined }));
                  }}
                  className={inputClassName}
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
                {errors.product && (
                  <p id="curve-initiative-product-error" className="mt-1 text-11 text-danger-primary">
                    {errors.product}
                  </p>
                )}
              </div>
              <div>
                <label htmlFor="curve-initiative-keyword" className={fieldLabelClassName}>
                  Keyword <span className="text-danger-primary">*</span>
                </label>
                <input
                  ref={keywordRef}
                  id="curve-initiative-keyword"
                  value={keyword}
                  onChange={(event) => {
                    setKeyword(event.target.value);
                    setErrors((current) => ({ ...current, keyword: undefined }));
                  }}
                  className={inputClassName}
                  maxLength={50}
                  aria-invalid={!!errors.keyword}
                  aria-describedby={errors.keyword ? "curve-initiative-keyword-error" : undefined}
                />
                {errors.keyword && (
                  <p id="curve-initiative-keyword-error" className="mt-1 text-11 text-danger-primary">
                    {errors.keyword}
                  </p>
                )}
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="curve-initiative-risk" className={fieldLabelClassName}>
                  Risk tier
                </label>
                <select
                  id="curve-initiative-risk"
                  value={riskTier}
                  onChange={(event) => {
                    setRiskTier(event.target.value as TCurveInitiativeRiskTier);
                    setErrors((current) => ({
                      ...current,
                      productApprover: undefined,
                      technicalApprover: undefined,
                      codeApprover: undefined,
                    }));
                  }}
                  className={inputClassName}
                >
                  <option value="LOW">Low</option>
                  <option value="STANDARD">Standard</option>
                  <option value="HIGH">High</option>
                </select>
              </div>
              <div>
                <label htmlFor="curve-initiative-mode" className={fieldLabelClassName}>
                  Mode
                </label>
                <select id="curve-initiative-mode" value="STANDALONE" disabled className={inputClassName}>
                  <option value="STANDALONE">Standalone</option>
                </select>
              </div>
            </div>

            <div>
              <label htmlFor="curve-initiative-description" className={fieldLabelClassName}>
                Problem and intended outcome <span className="text-danger-primary">*</span>
              </label>
              <textarea
                ref={descriptionRef}
                id="curve-initiative-description"
                value={description}
                onChange={(event) => {
                  setDescription(event.target.value);
                  setErrors((current) => ({ ...current, description: undefined }));
                }}
                className={`${inputClassName} min-h-32 resize-y`}
                maxLength={20000}
                aria-invalid={!!errors.description}
                aria-describedby={errors.description ? "curve-initiative-description-error" : undefined}
              />
              {errors.description && (
                <p id="curve-initiative-description-error" className="mt-1 text-11 text-danger-primary">
                  {errors.description}
                </p>
              )}
            </div>

            <fieldset className="space-y-4">
              <legend className="text-13 font-semibold text-primary">Mandatory human gates</legend>
              <div className="grid gap-4 sm:grid-cols-2">
                {approverFields.map(({ label, key }, index) => (
                  <div key={key} className={index === 2 ? "sm:col-span-2" : undefined}>
                    <label htmlFor={`curve-initiative-${key}`} className={fieldLabelClassName}>
                      {label}
                    </label>
                    <select
                      ref={approverRefs[index]}
                      id={`curve-initiative-${key}`}
                      value={approverIds[index] ?? ""}
                      onChange={(event) => setApprover(index, event.target.value)}
                      className={inputClassName}
                      aria-invalid={!!errors[key]}
                      aria-describedby={errors[key] ? `curve-initiative-${key}-error` : undefined}
                    >
                      <option value="">Choose an active human</option>
                      {members.map((member) => (
                        <option key={member.member.id} value={member.member.id}>
                          {memberDisplayName(member)}
                        </option>
                      ))}
                    </select>
                    {errors[key] && (
                      <p id={`curve-initiative-${key}-error`} className="mt-1 text-11 text-danger-primary">
                        {errors[key]}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </fieldset>

            <p className="rounded-md bg-layer-1 p-3 text-11 leading-5 text-secondary">
              Standard and High risk require three distinct active humans. The backend verifies workspace membership and
              remains authoritative.
            </p>
          </div>

          <div className="sticky bottom-0 flex justify-end gap-2 border-t border-subtle bg-surface-1 px-5 py-4 sm:px-6">
            <Button type="button" size="lg" variant="neutral-primary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" size="lg" loading={isSubmitting}>
              Create Initiative
            </Button>
          </div>
        </form>
      </Dialog.Panel>
    </Dialog>
  );
}
