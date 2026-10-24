/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { useId, useRef, useState, type ReactNode } from "react";
import { FileText, ListChecks, CheckCircle2 } from "lucide-react";
// oxlint-disable-next-line import/no-unassigned-import -- Load the scoped review styles.
import "./document-review-stages.css";

const stages = [
  { title: "Product requirements", reviewer: "Product approval", Icon: FileText },
  { title: "Implementation plan", reviewer: "Technical approval", Icon: ListChecks },
] as const;

export type DocumentApprovalStatus =
  | "LOADING"
  | "EMPTY"
  | "READY"
  | "REVIEW"
  | "UPDATING"
  | "CHANGES"
  | "APPROVED"
  | "UNAVAILABLE"
  | "LOCKED";
const statusLabels: Record<DocumentApprovalStatus, string> = {
  LOADING: "Checking status…",
  EMPTY: "Document needed",
  READY: "Ready for review",
  REVIEW: "Waiting for approval",
  CHANGES: "Changes requested",
  UPDATING: "Update needed",
  APPROVED: "Approved",
  UNAVAILABLE: "Status unavailable",
  LOCKED: "After Product approval",
};

/** Stage selection is navigation only; each panel resolves its own current authority. */
export function DocumentReviewStages({
  prd,
  plan,
  statuses,
}: {
  prd: ReactNode;
  plan: ReactNode;
  statuses?: [DocumentApprovalStatus, DocumentApprovalStatus];
}) {
  const id = useId();
  const [stage, setStage] = useState(0);
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);
  return (
    <section className="curve-document-review" aria-label="Document approvals">
      <div className="curve-document-review__tabs" role="tablist" aria-label="Approval stages">
        {stages.map(({ title, reviewer, Icon }, index) => (
          <button
            key={title}
            ref={(element) => {
              buttons.current[index] = element;
            }}
            type="button"
            role="tab"
            id={`${id}-tab-${index}`}
            aria-selected={stage === index}
            aria-controls={`${id}-panel-${index}`}
            tabIndex={stage === index ? 0 : -1}
            onClick={() => setStage(index)}
            onKeyDown={(event) => {
              const next =
                event.key === "Home"
                  ? 0
                  : event.key === "End"
                    ? 1
                    : event.key === "ArrowRight" || event.key === "ArrowLeft"
                      ? 1 - stage
                      : null;
              if (next === null) return;
              event.preventDefault();
              setStage(next);
              buttons.current[next]?.focus();
            }}
          >
            <span className="curve-document-review__icon">
              {statuses?.[index] === "APPROVED" ? (
                <CheckCircle2 size={22} aria-hidden="true" />
              ) : (
                <Icon size={22} aria-hidden="true" />
              )}
            </span>
            <span>
              <strong>{title}</strong>
              <span>{reviewer}</span>
              {statuses && (
                <span className="curve-document-review__status" data-status={statuses[index]}>
                  {statusLabels[statuses[index]]}
                </span>
              )}
            </span>
            <span className="curve-document-review__step" aria-label={`Stage ${index + 1} of 2`}>
              {index + 1}
            </span>
          </button>
        ))}
      </div>
      {stages.map(({ title }, index) => (
        <div
          key={title}
          id={`${id}-panel-${index}`}
          role="tabpanel"
          aria-labelledby={`${id}-tab-${index}`}
          hidden={stage !== index}
          tabIndex={0}
          className="curve-document-review__panel"
        >
          {index === 0 ? prd : plan}
        </div>
      ))}
    </section>
  );
}
