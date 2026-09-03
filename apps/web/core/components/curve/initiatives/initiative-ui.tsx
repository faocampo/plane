/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type {
  IWorkspaceMember,
  TCurveInitiativeBusinessIntent,
  TCurveInitiativeRiskTier,
  TCurveInitiativeState,
} from "@plane/types";
import { cn } from "@plane/utils";

export const initiativeStateLabel: Record<TCurveInitiativeState, string> = {
  DRAFT: "Draft",
  ALIGNING: "Aligning",
  PRD_REVIEW: "PRD review",
  PLANNING: "Planning",
  PLAN_REVIEW: "Plan review",
  EXECUTING: "Executing",
  CODE_READINESS_REVIEW: "Code readiness",
  READY_FOR_REPOSITORY_REVIEW: "Repository review",
  PAUSED: "Paused",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

export const initiativeBusinessIntentOptions: Array<{
  value: TCurveInitiativeBusinessIntent;
  label: string;
  description: string;
}> = [
  {
    value: "STRATEGIC",
    label: "Strategic",
    description: "Company or Product objective, differentiation, growth, or a new market.",
  },
  {
    value: "CUSTOMER_COMMITMENT",
    label: "Customer commitment",
    description: "A material customer promise, commercial outcome, retention risk, or strategic-customer need.",
  },
  {
    value: "BUSINESS_IMPROVEMENT",
    label: "Business improvement",
    description: "BAU, reliability, efficiency, maintenance, or capabilities that enable future Initiatives.",
  },
  {
    value: "MANDATORY",
    label: "Mandatory",
    description: "Regulation, security, legal obligation, or platform end-of-life work.",
  },
];

export const initiativeBusinessIntentLabel = (intent: TCurveInitiativeBusinessIntent | null | undefined) =>
  initiativeBusinessIntentOptions.find(({ value }) => value === intent)?.label ?? "Not set";

export const memberDisplayName = (member?: IWorkspaceMember | null) => {
  if (!member?.member) return "Unknown member";
  return (
    member.member.display_name ||
    [member.member.first_name, member.member.last_name].filter(Boolean).join(" ") ||
    member.member.email ||
    "Unknown member"
  );
};

export const memberInitials = (member?: IWorkspaceMember | null) => {
  const name = memberDisplayName(member);
  const tokens = name.replace(/@.*/, "").trim().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return "?";
  return `${tokens[0]?.[0] ?? ""}${tokens.length > 1 ? (tokens.at(-1)?.[0] ?? "") : ""}`.toUpperCase();
};

export function InitiativeAvatar({ member, size = "md" }: { member?: IWorkspaceMember | null; size?: "sm" | "md" }) {
  const name = memberDisplayName(member);
  return (
    <span
      className={cn(
        "inline-grid shrink-0 place-items-center rounded-full bg-accent-subtle leading-none font-semibold text-accent-primary",
        size === "sm" ? "size-6 text-9" : "size-8 text-10"
      )}
      aria-label={name}
      title={name}
    >
      <span aria-hidden="true" className="block leading-none">
        {memberInitials(member)}
      </span>
    </span>
  );
}

export function InitiativeStateBadge({ state }: { state: TCurveInitiativeState }) {
  return (
    <span
      className={cn(
        "inline-flex min-h-6 min-w-20 items-center justify-center rounded-full border px-2 py-0.5 text-10 leading-none font-semibold whitespace-nowrap",
        state === "ALIGNING" && "border-accent-subtle bg-accent-subtle text-accent-primary",
        state === "DRAFT" && "border-subtle bg-layer-2 text-secondary",
        state === "PAUSED" && "border-warning-subtle bg-warning-subtle text-warning-primary",
        state === "CANCELLED" && "border-danger-subtle bg-danger-subtle text-danger-primary",
        state === "FAILED" && "border-danger-subtle bg-danger-subtle text-danger-primary",
        !["ALIGNING", "DRAFT", "PAUSED", "CANCELLED", "FAILED"].includes(state) &&
          "border-success-subtle bg-success-subtle text-success-primary"
      )}
    >
      {initiativeStateLabel[state]}
    </span>
  );
}

export function InitiativeRiskBadge({ risk }: { risk: TCurveInitiativeRiskTier }) {
  return (
    <span
      className={cn(
        "text-9 font-semibold tracking-[0.08em] uppercase",
        risk === "HIGH" ? "text-danger-primary" : risk === "STANDARD" ? "text-secondary" : "text-success-primary"
      )}
    >
      {risk.toLowerCase()} risk
    </span>
  );
}
