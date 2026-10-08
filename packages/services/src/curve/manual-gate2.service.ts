// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
/* eslint-disable unicorn/no-array-sort -- These are fresh arrays; keep ES2022 browser compatibility. */
import { ManualPlanClientError } from "./manual-plan-draft.service";
import type { ManualPlanTarget } from "./manual-plan-draft.types";
import type {
  ManualGate2Api,
  ManualGate2Command,
  ManualGate2Material,
  ManualGate2Object,
  ManualGate2Record,
  ManualGate2Status,
  ManualPlanPreparation,
} from "./manual-gate2.types";
import schemas from "./manual-gate2.schemas.json";
export type * from "./manual-gate2.types";

type Schema = {
  type?: string;
  const?: unknown;
  enum?: unknown[];
  anyOf?: Schema[];
  allOf?: Schema[];
  properties?: Record<string, Schema>;
  required?: string[];
  additionalProperties?: boolean;
  items?: Schema;
  maxItems?: number;
  minItems?: number;
  uniqueItems?: boolean;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  pattern?: string;
  format?: string;
};
const canonical = (value: unknown): string =>
  Array.isArray(value)
    ? `[${value.map(canonical).join(",")}]`
    : value !== null && typeof value === "object"
      ? `{${Object.keys(value)
          .sort()
          .map((k) => `${JSON.stringify(k)}:${canonical((value as Record<string, unknown>)[k])}`)
          .join(",")}}`
      : JSON.stringify(value);
const uuid = (value: unknown): value is string =>
  typeof value === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(value);
const integer = (value: unknown): value is number =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0;
function requireValue(value: unknown): asserts value {
  if (!value) throw new ManualPlanClientError("INVALID");
}
function shape(value: unknown, schema: Schema, depth = 0): boolean {
  if (depth > 40) return false;
  if ("const" in schema && canonical(value) !== canonical(schema.const)) return false;
  if (schema.enum && !schema.enum.some((x) => canonical(x) === canonical(value))) return false;
  if (schema.anyOf && !schema.anyOf.some((x) => shape(value, x, depth + 1))) return false;
  if (schema.allOf && !schema.allOf.every((x) => shape(value, x, depth + 1))) return false;
  if (schema.type === "null") return value === null;
  if (schema.type === "boolean" && typeof value !== "boolean") return false;
  if (schema.type === "integer" && (typeof value !== "number" || !Number.isSafeInteger(value))) return false;
  if (schema.type === "string" && typeof value !== "string") return false;
  if (schema.type === "object" && (value === null || typeof value !== "object" || Array.isArray(value))) return false;
  if (schema.type === "array" && !Array.isArray(value)) return false;
  if (typeof value === "string") {
    if (value.length < (schema.minLength ?? 0) || value.length > (schema.maxLength ?? Infinity)) return false;
    if (schema.pattern && !new RegExp(schema.pattern).test(value)) return false;
    if (schema.format === "uuid" && !uuid(value)) return false;
    if (schema.format === "date-time" && !Number.isFinite(Date.parse(value))) return false;
  }
  if (typeof value === "number" && (value < (schema.minimum ?? -Infinity) || value > (schema.maximum ?? Infinity)))
    return false;
  if (Array.isArray(value)) {
    if (value.length < (schema.minItems ?? 0) || value.length > (schema.maxItems ?? Infinity)) return false;
    if (schema.uniqueItems && new Set(value.map(canonical)).size !== value.length) return false;
    if (schema.items && !value.every((x) => shape(x, schema.items!, depth + 1))) return false;
  } else if (value && typeof value === "object") {
    const object = value as Record<string, unknown>;
    if (schema.required?.some((k) => !Object.hasOwn(object, k))) return false;
    if (
      schema.additionalProperties === false &&
      Object.keys(object).some((k) => !Object.hasOwn(schema.properties ?? {}, k))
    )
      return false;
    if (
      Object.entries(schema.properties ?? {}).some(
        ([k, s]) => Object.hasOwn(object, k) && !shape(object[k], s, depth + 1)
      )
    )
      return false;
  }
  return true;
}
async function sha(raw: Uint8Array) {
  const result = await crypto.subtle.digest("SHA-256", new Uint8Array(raw).buffer);
  return "sha256:" + Array.from(new Uint8Array(result), (x) => x.toString(16).padStart(2, "0")).join("");
}
function root(target: ManualPlanTarget) {
  requireValue(
    uuid(target.workspaceId) &&
      uuid(target.productId) &&
      uuid(target.initiativeId) &&
      /^[a-zA-Z0-9_-]{1,255}$/.test(target.workspaceSlug)
  );
  return `/api/v1/workspaces/${encodeURIComponent(target.workspaceSlug)}/curve/initiatives/${target.initiativeId}/manual-gate2/v2/`;
}
function scoped(value: unknown, target: ManualPlanTarget, currentVersion: number, schema: Schema) {
  requireValue(shape(value, schema));
  const data = value as Record<string, unknown>;
  requireValue(
    data.workspace_id === target.workspaceId &&
      data.product_id === target.productId &&
      data.initiative_id === target.initiativeId &&
      integer(data.initiative_version) &&
      data.initiative_version <= currentVersion
  );
}
export class ManualGate2Service implements ManualGate2Api {
  constructor(private readonly send: typeof fetch = (...args) => fetch(...args)) {}
  private async read(url: string, signal?: AbortSignal) {
    try {
      const response = await this.send(url, {
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        signal,
      });
      if (response.status !== 200) throw new ManualPlanClientError("UNAVAILABLE");
      return response;
    } catch (error) {
      if (error instanceof ManualPlanClientError) throw error;
      throw new ManualPlanClientError(signal?.aborted ? "CANCELLED" : "UNAVAILABLE");
    }
  }
  private async json(response: Response, limit = 131072) {
    requireValue(response.headers.get("content-type")?.split(";", 1)[0] === "application/json");
    const reader = response.body?.getReader();
    requireValue(reader);
    const chunks: Uint8Array[] = [];
    let size = 0;
    try {
      for (;;) {
        // Consume and bound each stream chunk before requesting the next one.
        // eslint-disable-next-line no-await-in-loop
        const chunk = await reader.read();
        if (chunk.done) break;
        size += chunk.value.length;
        requireValue(size <= limit);
        chunks.push(chunk.value);
      }
      const raw = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) {
        raw.set(chunk, offset);
        offset += chunk.length;
      }
      return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)) as unknown;
    } finally {
      await reader.cancel().catch(() => undefined);
      reader.releaseLock();
    }
  }
  private version(response: Response, target: ManualPlanTarget) {
    const match = /^"curve-initiative:([0-9a-f-]+):v([1-9][0-9]*)"$/.exec(response.headers.get("etag") ?? "");
    requireValue(match && match[1] === target.initiativeId && integer(Number(match[2])));
    return Number(match[2]);
  }
  private async metadata<T>(target: ManualPlanTarget, route: string, schema: Schema, signal?: AbortSignal) {
    const response = await this.read(root(target) + route, signal);
    const currentVersion = this.version(response, target);
    const data = await this.json(response);
    scoped(data, target, currentVersion, schema);
    requireValue((data as { initiative_version: number }).initiative_version === currentVersion && !signal?.aborted);
    return { data: data as T, currentVersion };
  }
  preparation(target: ManualPlanTarget, signal?: AbortSignal) {
    return this.metadata<ManualPlanPreparation>(target, "preparation/", schemas.preparation as Schema, signal);
  }
  async status(target: ManualPlanTarget, signal?: AbortSignal) {
    const result = await this.metadata<ManualGate2Status>(target, "status/", schemas.status as Schema, signal);
    const d = result.data;
    if (d.current_record) {
      scoped(d.current_record, target, result.currentVersion, schemas.projection as Schema);
      requireValue(
        d.subject_ref?.entity_id === d.current_record.subject_id &&
          d.subject_ref.digest === d.current_record.subject_digest
      );
    }
    requireValue(
      d.claims.every((c) => c.initiative_id === target.initiativeId && c.subject_id === d.subject_ref?.entity_id)
    );
    requireValue(new Set(d.claims.map((c) => c.claim_id)).size === d.claims.length);
    return result;
  }
  async material(target: ManualPlanTarget, reference: ManualGate2Object, signal?: AbortSignal) {
    requireValue(uuid(reference.object_id));
    const response = await this.read(root(target) + `materials/${reference.object_id}/`, signal);
    const currentVersion = this.version(response, target);
    const value = await this.json(response, 32 * 1024 * 1024);
    scoped(value, target, currentVersion, schemas.material as Schema);
    const data = value as ManualGate2Material;
    const raw = new TextEncoder().encode(data.content);
    requireValue(
      data.initiative_version === currentVersion &&
        canonical(data.reference) === canonical(reference) &&
        raw.length === reference.size_bytes &&
        (await sha(raw)) === reference.digest &&
        !signal?.aborted
    );
    return { data, currentVersion };
  }
  async execute(target: ManualPlanTarget, command: ManualGate2Command, signal?: AbortSignal) {
    const url = root(target) + "commands/";
    const payload = structuredClone(command.payload);
    const expectedVersion = command.expectedVersion;
    const key = command.idempotencyKey;
    requireValue(
      shape(payload, schemas.command as Schema) && integer(expectedVersion) && /^[\x20-\x7e]{1,500}$/.test(key)
    );
    const requestDigest = await sha(
      new TextEncoder().encode(
        canonical({ initiative_id: target.initiativeId, expected_version: expectedVersion, payload })
      )
    );
    const token = (await this.json(await this.read("/auth/get-csrf-token/", signal))) as { csrf_token?: unknown };
    requireValue(
      token && typeof token.csrf_token === "string" && /^[a-zA-Z0-9]{32,64}$/.test(token.csrf_token) && !signal?.aborted
    );
    let response: Response;
    try {
      response = await this.send(url, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        signal,
        headers: {
          "Content-Type": "application/json",
          "X-CSRFTOKEN": token.csrf_token,
          "If-Match": `"curve-initiative:${target.initiativeId}:v${expectedVersion}"`,
          "Idempotency-Key": key,
        },
        body: JSON.stringify(payload),
      });
    } catch {
      throw new ManualPlanClientError("UNKNOWN");
    }
    if (response.status >= 400 && response.status < 500)
      throw new ManualPlanClientError([409, 412].includes(response.status) ? "CONFLICT" : "UNAVAILABLE");
    try {
      requireValue(response.status === 200 || response.status === 201);
      const currentVersion = this.version(response, target);
      const value = await this.json(response);
      scoped(value, target, currentVersion, schemas.projection as Schema);
      const data = value as ManualGate2Record;
      requireValue(
        data.initiative_version === expectedVersion + 1 &&
          data.request_digest === requestDigest &&
          data.action === payload.action &&
          data.draft_revision_id === payload.draft_revision_id
      );
      requireValue(
        payload.subject_ref === null
          ? data.subject_id === data.id
          : data.subject_id === payload.subject_ref.entity_id && data.subject_digest === payload.subject_ref.digest
      );
      requireValue(
        canonical(data.rationale_ref) === canonical(payload.rationale_ref) &&
          data.reconciliation_id === (payload.reconciliation_ref?.entity_id ?? null)
      );
      requireValue(response.status !== 201 || currentVersion === expectedVersion + 1);
      requireValue(!signal?.aborted);
      return { data, currentVersion };
    } catch {
      throw new ManualPlanClientError("UNKNOWN");
    }
  }
}
