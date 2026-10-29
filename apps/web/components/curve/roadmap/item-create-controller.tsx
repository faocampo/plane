/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { useEffect, useRef } from "react";
import type { CurveItemCreate, CurveItemCreationResult, CurveRoadmapScope } from "@plane/types";
import { useCurveRoadmapItems } from "@/hooks/use-curve-roadmap-items";
import { ItemNavigationGuard } from "./item-navigation-guard";
import { RoadmapItemCreateForm } from "./item-create-form";
import type { ItemCreationState, RoadmapItemDraft } from "./item-create-form";

type Choice = { id: string; name: string };
type Props = {
  workspaceSlug: string;
  actorId: string | undefined;
  scope: CurveRoadmapScope;
  milestones: Choice[];
  features: Choice[];
  reviewers: Choice[];
  selectedMilestoneId: string;
  choicesAvailable?: boolean;
  onPendingChange?: (pending: boolean) => void;
  guardNavigation?: boolean;
  onCreated: (result: Pick<CurveItemCreationResult, "resource_ref">) => void;
};
const states: Record<string, ItemCreationState> = {
  IDLE: "ready",
  SAVING: "saving",
  CANCELLING: "cancelling",
  RECOVERING: "checking",
  UNKNOWN: "unknown",
  FAILED: "failed",
  CREATED: "created",
  RECOVERED: "created",
  CANCELLED: "cancelled",
};

/** Starting metadata only: Product and Technical approval results remain unset. */
export function roadmapItemDraftPayload(draft: RoadmapItemDraft, keyword: string): Omit<CurveItemCreate, "scope_body"> {
  return {
    initiative: {
      keyword,
      title: draft.title.trim(),
      description: { schema_version: "1.0", format: "MARKDOWN", body: draft.title.trim() },
      risk_tier: draft.riskTier,
      business_intent: null,
      gate_assignments: [
        { gate_type: "PRD_APPROVAL", approver_user_id: draft.productReviewerId },
        { gate_type: "PLAN_APPROVAL", approver_user_id: draft.technicalReviewerId },
      ],
    },
    milestone_id: draft.milestoneId,
    feature_id: draft.featureId,
    priority: "MEDIUM",
    confidence: "MEDIUM",
    health: "UNKNOWN",
    planned_start: null,
    planned_end: null,
  };
}

/** The parent supplies current paginated choices and routes the committed result to its PRD. */
export function RoadmapItemCreateController({
  workspaceSlug,
  actorId,
  scope,
  onCreated,
  choicesAvailable = true,
  onPendingChange,
  guardNavigation = false,
  ...choices
}: Props) {
  const items = useCurveRoadmapItems(workspaceSlug, actorId, scope);
  const sessionKey = JSON.stringify([workspaceSlug, actorId ?? null, scope.productId, scope.roadmapId]);
  const delivered = useRef<string | undefined>(undefined);
  const command = items.command;
  const pending = ["SAVING", "CANCELLING", "RECOVERING", "UNKNOWN"].includes(command.status);
  useEffect(() => {
    onPendingChange?.(pending);
  }, [pending, onPendingChange]);
  useEffect(() => {
    if (command.status !== "CREATED" && command.status !== "RECOVERED") return;
    const identity = JSON.stringify([sessionKey, command.result.resource_ref.resource_id]);
    if (delivered.current === identity) return;
    delivered.current = identity;
    onCreated(command.result);
  }, [command, onCreated, sessionKey]);
  return (
    <>
      {guardNavigation && <ItemNavigationGuard pending={pending} />}
      <RoadmapItemCreateForm
        key={sessionKey}
        {...choices}
        canCreate={choicesAvailable && items.page.status === "READY" && items.page.data.can_create}
        checkingAccess={items.page.status === "IDLE" || items.page.status === "LOADING"}
        canRecover={items.canRecover}
        canCancel={items.canCancel}
        onCancel={items.cancel}
        state={states[command.status]}
        onCreate={async (draft) => {
          await items.createDraft(roadmapItemDraftPayload(draft, `ITEM-${crypto.randomUUID()}`));
        }}
        onRetry={items.retry}
      />
    </>
  );
}
