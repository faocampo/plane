/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import type {
  CurveExistingWorkInitiativeScope,
  CurveExistingWorkProductScope,
  CurveProjectAssociation,
  CurveScopeProposalRevision,
  CurveScopedPrdCheckpointV1,
  CurveScopedPrdObservationV1,
  CurveScopedPrdOperationAcceptance,
  CurveScopedPrdScopeV1,
  CurveScopedPrdSubjectV1,
} from "@plane/types";
import {
  validateCurveProjectAssociation,
  validateCurveScopeProposalRevision,
  validateCurveScopedPrdObservationV1,
  validateCurveScopedPrdSubjectV1,
} from "./existing-work-contracts/validators.mjs";

export type CurveExistingWorkErrorCode =
  | "INVALID"
  | "UNAVAILABLE"
  | "CONFLICT"
  | "CANCELLED"
  | "TRANSPORT"
  | "MUTATION_OUTCOME_UNKNOWN";
/** Intentionally contains no cause, HTTP body, request config, rationale or validator diagnostics. */
export class CurveExistingWorkError extends Error {
  constructor(
    readonly code: CurveExistingWorkErrorCode = "INVALID",
    readonly status?: number
  ) {
    super("Curve existing-work data or command could not be verified. Refresh before continuing.");
    this.name = "CurveExistingWorkError";
  }
}
export function requireCurve(condition: unknown): asserts condition {
  if (!condition) throw new CurveExistingWorkError();
}
export const isCurveUuid = (value: unknown): value is string =>
  typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
export const isCurveVersion = (value: unknown): value is number =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0;
export function validateCurveScope<T extends CurveExistingWorkProductScope>(scope: T): T {
  requireCurve(isCurveUuid(scope.workspaceId) && isCurveUuid(scope.productId));
  if ("initiativeId" in scope) requireCurve(isCurveUuid(scope.initiativeId));
  return { ...scope };
}
function requireUtf8Strings(value: unknown): void {
  if (typeof value === "string") {
    requireCurve(new TextDecoder("utf-8", { fatal: true }).decode(new TextEncoder().encode(value)) === value);
  } else if (Array.isArray(value)) {
    value.forEach(requireUtf8Strings);
  } else if (value !== null && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      requireUtf8Strings(key);
      requireUtf8Strings(item);
    }
  }
}
type Validator<T> = { (input: unknown): input is T; errors?: unknown };
export function validateCurveWire<T>(validate: Validator<T>, input: unknown, maxBytes = 262144): T {
  try {
    requireCurve(validate(input));
    const snapshot: unknown = structuredClone(input);
    // Validate the detached snapshot too: inherited fields/accessors are not trusted wire data.
    requireCurve(validate(snapshot));
    requireUtf8Strings(snapshot);
    requireCurve(new TextEncoder().encode(JSON.stringify(snapshot)).byteLength <= maxBytes);
    return snapshot;
  } catch {
    throw new CurveExistingWorkError();
  } finally {
    // Ajv diagnostic keys may themselves be sensitive; do not keep them after validation.
    validate.errors = null;
  }
}
export function requireCurveMatches(value: object, expected: object) {
  for (const [key, item] of Object.entries(expected)) {
    requireCurve(item !== undefined && (value as Record<string, unknown>)[key] === item);
  }
}
function requireProduct(value: { workspace_id: string; product_id: string }, scope: CurveExistingWorkProductScope) {
  validateCurveScope(scope);
  requireCurve(value.workspace_id === scope.workspaceId && value.product_id === scope.productId);
}
function requireInitiative(
  value: { workspace_id: string; product_id: string; initiative_id: string },
  scope: CurveExistingWorkInitiativeScope
) {
  requireProduct(value, scope);
  requireCurve(value.initiative_id === scope.initiativeId);
}
function requireOrderedMembers(items: Array<{ source_issue_id: string }>) {
  const ids = items.map((item) => item.source_issue_id);
  requireCurve(ids.every((id, i) => i === 0 || ids[i - 1]! < id));
}
function canonicalCurveMetadata(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalCurveMetadata).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.entries(value)
      // oxlint-disable-next-line unicorn/no-array-sort -- Sort a fresh entries array; keep ES2022 consumer compatibility.
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonicalCurveMetadata(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}
async function requireCurveDigest(value: unknown, expected: string) {
  try {
    const bytes = new TextEncoder().encode(canonicalCurveMetadata(value));
    const hash = await globalThis.crypto.subtle.digest("SHA-256", bytes);
    requireCurve(
      `sha256:${Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("")}` === expected
    );
  } catch {
    throw new CurveExistingWorkError();
  }
}
function requireScopedExpectation(expected: CurveScopedPrdScopeV1) {
  requireCurve(
    isCurveUuid(expected.proposal_id) &&
      isCurveUuid(expected.scope_revision_id) &&
      isCurveVersion(expected.scope_revision)
  );
  requireCurve(
    typeof expected.membership_digest === "string" && /^sha256:[0-9a-f]{64}$/.test(expected.membership_digest)
  );
}
export function decodeCurveProjectAssociation(
  input: unknown,
  scope: CurveExistingWorkProductScope,
  expected: Partial<
    Pick<CurveProjectAssociation, "id" | "version" | "provider_installation_id" | "source_project_id" | "state">
  > = {}
): CurveProjectAssociation {
  const data = validateCurveWire(validateCurveProjectAssociation, input);
  requireProduct(data, scope);
  requireCurveMatches(data, expected);
  requireCurve(data.state === "ACTIVE" ? data.version === 1 : data.version === 2);
  return data;
}
export async function decodeCurveScopeProposal(
  input: unknown,
  scope: CurveExistingWorkInitiativeScope,
  expected: Partial<
    Pick<CurveScopeProposalRevision, "id" | "version" | "initiative_version" | "proposal_id" | "membership_digest">
  > = {}
): Promise<CurveScopeProposalRevision> {
  const data = validateCurveWire(validateCurveScopeProposalRevision, input);
  requireInitiative(data, scope);
  requireCurveMatches(data, expected);
  requireOrderedMembers(data.items);
  requireCurve(
    data.item_count === data.items.length &&
      data.delivery_count === data.items.filter((item) => item.purpose === "PROPOSED_DELIVERY").length
  );
  requireCurve((data.version === 1) === (data.predecessor_id === null));
  await requireCurveDigest(data.items, data.membership_digest);
  return data;
}
export async function decodeCurveScopedPrdObservationV1(
  input: unknown,
  scope: CurveExistingWorkInitiativeScope,
  expected: CurveScopedPrdScopeV1 & Partial<Pick<CurveScopedPrdObservationV1, "id" | "digest" | "initiative_version">>
): Promise<CurveScopedPrdObservationV1> {
  requireScopedExpectation(expected);
  const data = validateCurveWire(validateCurveScopedPrdObservationV1, input);
  requireInitiative(data, scope);
  requireCurveMatches(data, expected);
  requireOrderedMembers(data.members);
  requireCurve(data.reviewers.map((item) => item.gate_type).join(",") === "CODE_READINESS,PLAN_APPROVAL,PRD_APPROVAL");
  requireCurve(new Set(data.reviewers.map((item) => item.gate_assignment_id)).size === 3);
  const { digest, ...metadata } = data;
  await requireCurveDigest(metadata, digest);
  return data;
}
export async function decodeCurveScopedPrdSubjectV1(
  input: unknown,
  scope: CurveExistingWorkInitiativeScope,
  expected: CurveScopedPrdScopeV1 &
    CurveScopedPrdCheckpointV1 &
    Partial<Pick<CurveScopedPrdSubjectV1, "id" | "digest" | "observation_set_id" | "observation_digest">>
): Promise<CurveScopedPrdSubjectV1> {
  requireScopedExpectation(expected);
  requireCurve(
    isCurveUuid(expected.checkpoint_id) &&
      isCurveUuid(expected.artifact_version_id) &&
      isCurveUuid(expected.evidence_snapshot_id)
  );
  requireCurve(typeof expected.content_digest === "string" && /^sha256:[0-9a-f]{64}$/.test(expected.content_digest));
  requireCurve(typeof expected.provider_version === "string" && expected.provider_version.length > 0);
  const data = validateCurveWire(validateCurveScopedPrdSubjectV1, input);
  requireInitiative(data, scope);
  requireCurveMatches(data, expected);
  requireOrderedMembers(data.members);
  const { digest, ...metadata } = data;
  await requireCurveDigest(metadata, digest);
  return data;
}
export function decodeCurveScopedPrdAcceptance(input: unknown, workspaceId: string): CurveScopedPrdOperationAcceptance {
  requireCurve(typeof input === "object" && input !== null && !Array.isArray(input));
  const data = input as Record<string, unknown>;
  requireCurve(
    // oxlint-disable-next-line unicorn/no-array-sort -- Object.keys creates a new array.
    Object.keys(data).sort().join(",") === "id,operation_type,schema_version,status,version,workspace_id"
  );
  requireCurve(
    data.schema_version === "1.0" &&
      isCurveUuid(data.id) &&
      data.workspace_id === workspaceId &&
      data.operation_type === "WORKFLOW_COMMAND" &&
      isCurveVersion(data.version)
  );
  requireCurve(
    typeof data.status === "string" &&
      [
        "PENDING",
        "QUEUED",
        "RUNNING",
        "WAITING_FOR_HUMAN",
        "CANCEL_REQUESTED",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
      ].includes(data.status)
  );
  return structuredClone(data) as CurveScopedPrdOperationAcceptance;
}
