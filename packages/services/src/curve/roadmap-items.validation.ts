/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import type { CurveItemCreate, CurveItemMetadata, CurveItemPage, CurveRoadmapScope } from "@plane/types";
import { CurveExistingWorkError, isCurveUuid, isCurveVersion, requireCurve } from "./existing-work-validation";

export function closed(value: unknown, keys: string[]): asserts value is Record<string, unknown> {
  requireCurve(value !== null && typeof value === "object" && !Array.isArray(value));
  requireCurve(Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key)));
}
function text(value: unknown, maximum: number): asserts value is string {
  requireCurve(typeof value === "string" && value.length > 0 && [...value].length <= maximum && !value.includes("\0"));
  requireCurve(new TextDecoder("utf-8", { fatal: true }).decode(new TextEncoder().encode(value)) === value);
}
function member(value: unknown, values: readonly unknown[]) {
  requireCurve(values.includes(value));
}
function calendar(value: unknown): asserts value is string | null {
  if (value === null) return;
  requireCurve(typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value));
  const date = new Date(value + "T00:00:00Z");
  requireCurve(
    Number.isFinite(date.valueOf()) && date.toISOString().slice(0, 10) === value && value.slice(0, 4) !== "0000"
  );
}
function schedule(value: Record<string, unknown>) {
  calendar(value.planned_start);
  calendar(value.planned_end);
  requireCurve((value.planned_start === null) === (value.planned_end === null));
  if (value.planned_start !== null && value.planned_end !== null)
    requireCurve(value.planned_start <= value.planned_end);
}
function keyword(value: unknown) {
  text(value, 50);
  requireCurve(/^[A-Za-z0-9][A-Za-z0-9-]{0,49}$/.test(value));
}
function dimensions(value: Record<string, unknown>) {
  member(value.priority, ["CRITICAL", "HIGH", "MEDIUM", "LOW"]);
  member(value.confidence, ["HIGH", "MEDIUM", "LOW"]);
  member(value.health, ["ON_TRACK", "AT_RISK", "OFF_TRACK", "UNKNOWN"]);
  schedule(value);
}
function detached(value: unknown): unknown {
  try {
    const result: unknown = structuredClone(value);
    requireCurve(new TextEncoder().encode(JSON.stringify(result)).byteLength <= 262144);
    return result;
  } catch {
    throw new CurveExistingWorkError();
  }
}
export function itemScope(scope: CurveRoadmapScope): CurveRoadmapScope {
  requireCurve(isCurveUuid(scope.productId) && isCurveUuid(scope.roadmapId));
  return { productId: scope.productId, roadmapId: scope.roadmapId };
}
export function decodeItemCreate(input: unknown): CurveItemCreate {
  const value = detached(input);
  closed(value, [
    "initiative",
    "milestone_id",
    "feature_id",
    "scope_body",
    "priority",
    "confidence",
    "health",
    "planned_start",
    "planned_end",
  ]);
  requireCurve(isCurveUuid(value.milestone_id) && isCurveUuid(value.feature_id));
  dimensions(value);
  const draft = value.initiative;
  closed(draft, ["keyword", "title", "description", "risk_tier", "business_intent", "gate_assignments"]);
  keyword(draft.keyword);
  text(draft.title, 255);
  member(draft.risk_tier, ["LOW", "STANDARD", "HIGH"]);
  member(draft.business_intent, [null, "STRATEGIC", "CUSTOMER_COMMITMENT", "BUSINESS_IMPROVEMENT", "MANDATORY"]);
  closed(draft.description, ["schema_version", "format", "body"]);
  requireCurve(draft.description.schema_version === "1.0" && draft.description.format === "MARKDOWN");
  text(draft.description.body, 20000);
  requireCurve(Array.isArray(draft.gate_assignments) && draft.gate_assignments.length === 2);
  const gates = new Set();
  const people = new Set();
  for (const assignment of draft.gate_assignments) {
    closed(assignment, ["gate_type", "approver_user_id"]);
    member(assignment.gate_type, ["PRD_APPROVAL", "PLAN_APPROVAL"]);
    requireCurve(isCurveUuid(assignment.approver_user_id));
    gates.add(assignment.gate_type);
    people.add(assignment.approver_user_id);
  }
  requireCurve(gates.size === 2 && (draft.risk_tier === "LOW" || people.size === 2));
  const scope = value.scope_body;
  closed(scope, ["object_id", "digest", "size_bytes", "media_type", "editor_schema_version"]);
  requireCurve(
    isCurveUuid(scope.object_id) && typeof scope.digest === "string" && /^sha256:[a-f0-9]{64}$/.test(scope.digest)
  );
  requireCurve(Number.isSafeInteger(scope.size_bytes) && (scope.size_bytes as number) >= 0);
  text(scope.media_type, 255);
  text(scope.editor_schema_version, 100);
  return value as unknown as CurveItemCreate;
}
function metadata(value: unknown, scope: CurveRoadmapScope): asserts value is CurveItemMetadata {
  closed(value, [
    "id",
    "version",
    "roadmap_id",
    "milestone_id",
    "feature_id",
    "owner_user_id",
    "status",
    "priority",
    "confidence",
    "health",
    "planned_start",
    "planned_end",
    "declared_progress",
    "initiative",
    "approval_stages",
  ]);
  for (const field of ["id", "roadmap_id", "milestone_id", "feature_id", "owner_user_id"])
    requireCurve(isCurveUuid(value[field]));
  requireCurve(value.roadmap_id === scope.roadmapId && isCurveVersion(value.version));
  requireCurve(
    Number.isInteger(value.declared_progress) &&
      (value.declared_progress as number) >= 0 &&
      (value.declared_progress as number) <= 100
  );
  member(value.status, ["PROPOSED", "COMMITTED", "IN_PROGRESS", "PAUSED", "DELIVERED", "CANCELLED"]);
  dimensions(value);
  closed(value.initiative, ["id", "version", "keyword", "title", "state"]);
  requireCurve(
    isCurveUuid(value.initiative.id) && value.initiative.id !== value.id && isCurveVersion(value.initiative.version)
  );
  keyword(value.initiative.keyword);
  text(value.initiative.title, 255);
  member(value.initiative.state, [
    "DRAFT",
    "ALIGNING",
    "PRD_REVIEW",
    "PLANNING",
    "PLAN_REVIEW",
    "EXECUTING",
    "READY_FOR_REPOSITORY_REVIEW",
    "PAUSED",
    "FAILED",
    "CANCELLED",
  ]);
  requireCurve(Array.isArray(value.approval_stages) && value.approval_stages.length === 2);
  for (const [index, stage] of value.approval_stages.entries()) {
    closed(stage, ["role", "gate_type", "approver_user_id"]);
    requireCurve(stage.role === (index === 0 ? "PRODUCT" : "TECHNICAL"));
    requireCurve(stage.gate_type === (index === 0 ? "PRD_APPROVAL" : "PLAN_APPROVAL"));
    requireCurve(stage.approver_user_id === null || isCurveUuid(stage.approver_user_id));
  }
}
export function decodeItemPage(
  input: unknown,
  scope: CurveRoadmapScope,
  pageSize: number,
  after?: string
): CurveItemPage {
  const expected = itemScope(scope);
  const value = detached(input);
  closed(value, ["results", "next_cursor", "roadmap_version", "can_create"]);
  requireCurve(isCurveVersion(value.roadmap_version) && typeof value.can_create === "boolean");
  requireCurve(Array.isArray(value.results) && value.results.length <= pageSize);
  let previous = after;
  for (const row of value.results) {
    metadata(row, expected);
    requireCurve(previous === undefined || previous < row.id);
    previous = row.id;
  }
  requireCurve(
    value.next_cursor === null ||
      (isCurveUuid(value.next_cursor) && value.results.length === pageSize && value.next_cursor === previous)
  );
  return value as unknown as CurveItemPage;
}
