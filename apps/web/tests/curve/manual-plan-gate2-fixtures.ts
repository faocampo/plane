// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
/* eslint-disable unicorn/no-array-sort -- These are fresh arrays; keep ES2022 browser compatibility. */
import { createHash } from "node:crypto";
import { target, revision } from "./manual-plan-fixtures";
import type {
  ManualGate2Command,
  ManualGate2Material,
  ManualGate2Object,
  ManualGate2Record,
  ManualGate2Status,
} from "../../../../packages/services/src/curve/manual-gate2.types";
export { target };
export const id = (n: number) => `40000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
export const hash = (text: string) => "sha256:" + createHash("sha256").update(text).digest("hex");
export const canonical = (v: unknown): string =>
  Array.isArray(v)
    ? `[${v.map(canonical).join(",")}]`
    : v && typeof v === "object"
      ? `{${Object.keys(v)
          .sort()
          .map((k) => `${JSON.stringify(k)}:${canonical((v as Record<string, unknown>)[k])}`)
          .join(",")}}`
      : JSON.stringify(v);
export const definition = JSON.stringify({ slices: [{ user_outcome: "A synthetic user can review the local plan." }] });
export const rationale = JSON.stringify({ text: "Synthetic approval evidence." });
export const object = (content: string, n: number): ManualGate2Object => ({
  object_id: id(n),
  digest: hash(content),
  size_bytes: new TextEncoder().encode(content).length,
  media_type: "application/json",
});
export const definitionRef = object(definition, 7),
  rationaleRef = object(rationale, 8);
export const record: ManualGate2Record = {
  schema_version: "curve.manual-gate2.record/v2-candidate",
  policy_edition: "LOCAL_MANUAL_GATE2_RECONSTRUCTION_V2",
  id: id(1),
  workspace_id: target.workspaceId,
  product_id: target.productId,
  initiative_id: target.initiativeId,
  sequence: 1,
  initiative_version: 10,
  action: "PREPARE",
  actor_id: revision.created_by,
  subject_id: id(1),
  subject_digest: hash("subject"),
  draft_revision_id: revision.id,
  rationale_ref: null,
  reconciliation_id: null,
  claims: [],
  recorded_at: "2026-10-06T19:00:00.000000Z",
  digest: hash("record"),
  request_digest: hash("request"),
};
export const status: ManualGate2Status = {
  schema_version: "curve.manual-gate2.status/v2-candidate",
  workspace_id: target.workspaceId,
  product_id: target.productId,
  initiative_id: target.initiativeId,
  initiative_version: 10,
  state: "PLAN_REVIEW",
  effective_hold: null,
  current_record: record,
  subject_ref: { entity_id: record.id, digest: record.subject_digest },
  draft_revision_id: revision.id,
  definition_ref: definitionRef,
  claims: [],
  allowed_actions: ["APPROVE", "REQUEST_CHANGES"],
  rationales: [{ reference: rationaleRef, intent: "APPROVE" }],
  execution_authorized: false,
  completion_credit: false,
};
export const result = <T>(data: T, currentVersion = 10) => ({ data, currentVersion });
export const material = (kind: "DEFINITION" | "RATIONALE"): ManualGate2Material => ({
  schema_version: "curve.manual-gate2.material/v2-candidate",
  workspace_id: target.workspaceId,
  product_id: target.productId,
  initiative_id: target.initiativeId,
  initiative_version: 10,
  kind,
  reference: kind === "DEFINITION" ? definitionRef : rationaleRef,
  content: kind === "DEFINITION" ? definition : rationale,
});
export const command = (): ManualGate2Command => ({
  payload: {
    schema_version: "curve.manual-gate2.command/v2-candidate",
    action: "APPROVE",
    draft_revision_id: revision.id,
    subject_ref: status.subject_ref,
    rationale_ref: rationaleRef,
    claims: [],
    reconciliation_ref: null,
  },
  expectedVersion: 10,
  idempotencyKey: "synthetic-gate2-command",
});
export function completed(c = command()): ManualGate2Record {
  return {
    ...record,
    id: id(2),
    sequence: 2,
    initiative_version: 11,
    action: c.payload.action,
    rationale_ref: c.payload.rationale_ref,
    request_digest: hash(
      canonical({ initiative_id: target.initiativeId, expected_version: c.expectedVersion, payload: c.payload })
    ),
  };
}
export const response = (body: unknown, code = 200, version = 10) =>
  new Response(JSON.stringify(body), {
    status: code,
    headers: { "Content-Type": "application/json", ETag: `"curve-initiative:${target.initiativeId}:v${version}"` },
  });
