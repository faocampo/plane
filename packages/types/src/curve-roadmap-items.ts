/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import type {
  ICurveRichTextDocument,
  TCurveInitiativeBusinessIntent,
  TCurveInitiativeRiskTier,
  TCurveInitiativeState,
} from "./curve";

export type CurveRoadmapScope = { productId: string; roadmapId: string };
export type CurveItemStatus = "PROPOSED" | "COMMITTED" | "IN_PROGRESS" | "PAUSED" | "DELIVERED" | "CANCELLED";
export type CurveItemPriority = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
export type CurveItemConfidence = "HIGH" | "MEDIUM" | "LOW";
export type CurveItemHealth = "ON_TRACK" | "AT_RISK" | "OFF_TRACK" | "UNKNOWN";
export type CurveItemScopeReference = {
  object_id: string;
  digest: string;
  size_bytes: number;
  media_type: string;
  editor_schema_version: string;
};
export type CurveItemReviewer = { gate_type: "PRD_APPROVAL" | "PLAN_APPROVAL"; approver_user_id: string };
export type CurveItemCreate = {
  initiative: {
    keyword: string;
    title: string;
    description: ICurveRichTextDocument;
    risk_tier: TCurveInitiativeRiskTier;
    business_intent: TCurveInitiativeBusinessIntent | null;
    gate_assignments: [CurveItemReviewer, CurveItemReviewer];
  };
  milestone_id: string;
  feature_id: string;
  scope_body: CurveItemScopeReference;
  priority: CurveItemPriority;
  confidence: CurveItemConfidence;
  health: CurveItemHealth;
  planned_start: string | null;
  planned_end: string | null;
};
export type CurveItemCreationResult = {
  resource_ref: {
    resource_type: "ROADMAP_ITEM";
    resource_id: string;
    resource_version: 1;
    initiative_ref: { resource_type: "INITIATIVE"; resource_id: string; resource_version: 1 };
  };
  etag: string;
  replayed: boolean;
};
export type CurveItemMetadata = {
  id: string;
  version: number;
  roadmap_id: string;
  milestone_id: string;
  feature_id: string;
  owner_user_id: string;
  status: CurveItemStatus;
  priority: CurveItemPriority;
  confidence: CurveItemConfidence;
  health: CurveItemHealth;
  planned_start: string | null;
  planned_end: string | null;
  declared_progress: number;
  initiative: { id: string; version: number; keyword: string; title: string; state: TCurveInitiativeState };
  approval_stages: [
    { role: "PRODUCT"; gate_type: "PRD_APPROVAL"; approver_user_id: string | null },
    { role: "TECHNICAL"; gate_type: "PLAN_APPROVAL"; approver_user_id: string | null },
  ];
};
export type CurveItemPage = {
  results: CurveItemMetadata[];
  next_cursor: string | null;
  roadmap_version: number;
  can_create: boolean;
};

export type CurveItemScopePreparationResult = {
  resource_ref: {
    resource_type: "PREPARED_ITEM_SCOPE";
    resource_id: string;
    resource_version: 1;
    scope_body: CurveItemScopeReference;
  };
  replayed: boolean;
};

export type CurveItemRecoveryResult =
  | { state: "UNRESOLVED" }
  | { state: "COMPLETED"; resource_ref: CurveItemCreationResult["resource_ref"] };

export type CurveItemCancellationResult = CurveItemRecoveryResult | { state: "CANCELLED" };
