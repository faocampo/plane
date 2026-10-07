/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 */
import type {
  ManualPlanApi,
  ManualPlanCommand,
  ManualPlanResult,
  ManualPlanRevision,
  ManualPlanSave,
  ManualPlanStatus,
  ManualPlanTarget,
} from "./manual-plan-draft.types";
export type {
  ManualPlanApi,
  ManualPlanCommand,
  ManualPlanResult,
  ManualPlanRevision,
  ManualPlanSave,
  ManualPlanStatus,
  ManualPlanTarget,
} from "./manual-plan-draft.types";

export class ManualPlanClientError extends Error {
  constructor(readonly code: "INVALID" | "CONFLICT" | "UNAVAILABLE" | "CANCELLED" | "UNKNOWN") {
    super("The manual draft request could not be verified.");
    this.name = "ManualPlanClientError";
  }
}
const edition = "LOCAL_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2";
const uuid = (v: unknown): v is string =>
  typeof v === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(v);
const digest = (v: unknown): v is string => typeof v === "string" && /^sha256:[0-9a-f]{64}$/.test(v);
const version = (v: unknown, min = 1): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min;
function requireValue(value: unknown): asserts value {
  if (!value) throw new ManualPlanClientError("INVALID");
}
function closed(value: unknown, fields: string): Record<string, unknown> {
  requireValue(value && typeof value === "object" && !Array.isArray(value));
  const result = value as Record<string, unknown>;
  requireValue(Object.keys(result).toSorted().join(",") === fields.split(",").toSorted().join(","));
  return result;
}
function ref(value: unknown) {
  const r = closed(value, "entity_id,digest");
  requireValue(uuid(r.entity_id) && digest(r.digest));
}
function shared(value: Record<string, unknown>) {
  requireValue(value.policy_edition === edition);
  ref(value.approved_subject_ref);
  ref(value.manual_profile_ref);
  const profile = value.manual_profile_ref as Record<string, unknown>;
  requireValue(
    profile.entity_id === "20000000-0000-4000-8000-000000000201" &&
      profile.digest === "sha256:16ddfbb742fb06e370e1c2db3723eb98c826e1454bf237d97f678656649314a4"
  );
  const d = closed(value.definition_ref, "object_id,digest,size_bytes,media_type");
  requireValue(
    uuid(d.object_id) &&
      digest(d.digest) &&
      version(d.size_bytes) &&
      d.size_bytes <= 5242880 &&
      d.media_type === "application/json"
  );
}
export function decodeManualPlanSave(input: unknown): ManualPlanSave {
  const data = closed(
    structuredClone(input),
    "schema_version,policy_edition,expected_draft_revision,approved_subject_ref,definition_ref,manual_profile_ref"
  );
  requireValue(
    data.schema_version === "curve.manual-plan-draft.save/v2-candidate" && version(data.expected_draft_revision, 0)
  );
  shared(data);
  return data as ManualPlanSave;
}
function scope(target: ManualPlanTarget): ManualPlanTarget {
  const copy = { ...target };
  requireValue(uuid(copy.workspaceId) && uuid(copy.productId) && uuid(copy.initiativeId));
  requireValue(typeof copy.workspaceSlug === "string" && /^[a-zA-Z0-9_-]{1,255}$/.test(copy.workspaceSlug));
  return copy;
}
function root(target: ManualPlanTarget) {
  return `/api/v1/workspaces/${encodeURIComponent(target.workspaceSlug)}/curve/initiatives/${target.initiativeId}/manual-plan-drafts/v2/`;
}
function etag(target: ManualPlanTarget, value: number) {
  return `"curve-initiative:${target.initiativeId}:v${value}"`;
}
function responseVersion(target: ManualPlanTarget, response: Response) {
  const header = response.headers.get("etag");
  const match = /^"curve-initiative:([0-9a-f-]+):v([1-9][0-9]*)"$/.exec(header ?? "");
  requireValue(match && match[1] === target.initiativeId && version(Number(match[2])));
  return Number(match[2]);
}
export function decodeManualPlanStatus(
  input: unknown,
  target: ManualPlanTarget,
  currentVersion: number
): ManualPlanStatus {
  scope(target);
  const data = closed(
    input,
    "schema_version,policy_edition,workspace_id,initiative_id,initiative_version,draft_status,current_revision_id,expected_draft_revision"
  );
  requireValue(
    data.schema_version === "curve.manual-plan-draft.status/v2-candidate" && data.policy_edition === edition
  );
  requireValue(
    data.workspace_id === target.workspaceId &&
      data.initiative_id === target.initiativeId &&
      version(data.initiative_version) &&
      data.initiative_version === currentVersion
  );
  requireValue(
    ["ABSENT", "CURRENT", "STALE"].includes(String(data.draft_status)) && version(data.expected_draft_revision, 0)
  );
  requireValue(
    data.draft_status === "ABSENT"
      ? data.current_revision_id === null && data.expected_draft_revision === 0
      : uuid(data.current_revision_id) && data.expected_draft_revision > 0
  );
  return structuredClone(data) as ManualPlanStatus;
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object")
    return `{${Object.entries(value)
      .toSorted(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`)
      .join(",")}}`;
  return JSON.stringify(value);
}
export async function decodeManualPlanRevision(
  input: unknown,
  target: ManualPlanTarget,
  currentVersion: number
): Promise<ManualPlanRevision> {
  scope(target);
  const data = closed(
    input,
    "schema_version,policy_edition,id,workspace_id,product_id,initiative_id,draft_id,revision,initiative_version,predecessor_id,approved_subject_ref,definition_ref,manual_profile_ref,created_by,recorded_at,digest,controlling"
  );
  requireValue(data.schema_version === "curve.manual-plan-draft.revision/v2-candidate" && data.controlling === false);
  shared(data);
  requireValue(
    data.workspace_id === target.workspaceId &&
      data.product_id === target.productId &&
      data.initiative_id === target.initiativeId
  );
  requireValue(
    uuid(data.id) &&
      uuid(data.draft_id) &&
      uuid(data.created_by) &&
      version(data.revision) &&
      version(data.initiative_version) &&
      version(currentVersion) &&
      data.initiative_version <= currentVersion
  );
  requireValue(
    data.revision === 1 ? data.predecessor_id === null : uuid(data.predecessor_id) && data.predecessor_id !== data.id
  );
  requireValue(
    typeof data.recorded_at === "string" &&
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(data.recorded_at) &&
      Number.isFinite(Date.parse(data.recorded_at))
  );
  requireValue(digest(data.digest));
  const { digest: expected, ...metadata } = data;
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(metadata)));
  requireValue(
    expected === `sha256:${Array.from(new Uint8Array(hash), (b) => b.toString(16).padStart(2, "0")).join("")}`
  );
  return structuredClone(data) as ManualPlanRevision;
}
/** Same-origin session transport, inert until a caller mounts the qualified candidate. */
export class ManualPlanDraftService implements ManualPlanApi {
  constructor(private readonly send: typeof fetch = (...args) => fetch(...args)) {}
  private async read(path: string, signal?: AbortSignal) {
    if (signal?.aborted) throw new ManualPlanClientError("CANCELLED");
    try {
      const response = await this.send(path, {
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        signal,
        headers: { Accept: "application/json" },
      });
      if (signal?.aborted) throw new ManualPlanClientError("CANCELLED");
      if (response.status !== 200) throw new ManualPlanClientError("UNAVAILABLE");
      return response;
    } catch (error) {
      throw error instanceof ManualPlanClientError
        ? error
        : new ManualPlanClientError(signal?.aborted ? "CANCELLED" : "UNAVAILABLE");
    }
  }
  private async json(response: Response) {
    // Bound the stream before parsing; never retain raw error bodies.
    requireValue(response.headers.get("content-type")?.split(";")[0] === "application/json");
    const reader = response.body?.getReader();
    requireValue(reader);
    let size = 0;
    const chunks: Uint8Array[] = [];
    try {
      for (;;) {
        // Each read consumes the same stream; the byte bound must precede the next read.
        // eslint-disable-next-line no-await-in-loop
        const { done, value } = await reader.read();
        if (done) break;
        size += value.length;
        requireValue(size <= 65536);
        chunks.push(value);
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.length;
      }
      return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown;
    } catch {
      throw new ManualPlanClientError("INVALID");
    } finally {
      await reader.cancel().catch(() => undefined);
      reader.releaseLock();
    }
  }
  async status(target: ManualPlanTarget, signal?: AbortSignal) {
    const expected = scope(target);
    const response = await this.read(root(expected) + "status/", signal);
    const currentVersion = responseVersion(expected, response);
    const data = decodeManualPlanStatus(await this.json(response), expected, currentVersion);
    if (signal?.aborted) throw new ManualPlanClientError("CANCELLED");
    return { data, etag: etag(expected, currentVersion), currentVersion };
  }
  private async readRevision(target: ManualPlanTarget, suffix: string, id: string | undefined, signal?: AbortSignal) {
    const expected = scope(target);
    const response = await this.read(root(expected) + suffix, signal);
    const currentVersion = responseVersion(expected, response);
    const data = await decodeManualPlanRevision(await this.json(response), expected, currentVersion);
    requireValue(id === undefined || data.id === id);
    if (signal?.aborted) throw new ManualPlanClientError("CANCELLED");
    return { data, etag: etag(expected, currentVersion), currentVersion };
  }
  current(target: ManualPlanTarget, signal?: AbortSignal) {
    return this.readRevision(target, "current/", undefined, signal);
  }
  revision(target: ManualPlanTarget, id: string, signal?: AbortSignal) {
    requireValue(uuid(id));
    return this.readRevision(target, `revisions/${id}/`, id, signal);
  }
  async save(
    target: ManualPlanTarget,
    command: ManualPlanCommand,
    signal?: AbortSignal
  ): Promise<ManualPlanResult<ManualPlanRevision>> {
    const expected = scope(target);
    const payload = decodeManualPlanSave(command.payload);
    const expectedVersion = command.expectedVersion;
    const key = command.idempotencyKey;
    requireValue(version(expectedVersion) && typeof key === "string" && /^[\x20-\x7e]{1,500}$/.test(key));
    const csrf = await this.json(await this.read("/auth/get-csrf-token/", signal));
    requireValue(
      csrf &&
        typeof csrf === "object" &&
        "csrf_token" in csrf &&
        typeof csrf.csrf_token === "string" &&
        /^[a-zA-Z0-9]{32,64}$/.test(csrf.csrf_token)
    );
    if (signal?.aborted) throw new ManualPlanClientError("CANCELLED");
    let response: Response;
    try {
      response = await this.send(root(expected), {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        signal,
        headers: {
          "Content-Type": "application/json",
          "X-CSRFTOKEN": csrf.csrf_token,
          "If-Match": etag(expected, expectedVersion),
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
      const currentVersion = responseVersion(expected, response);
      const data = await decodeManualPlanRevision(await this.json(response), expected, currentVersion);
      requireValue(
        data.revision === payload.expected_draft_revision + 1 && data.initiative_version === expectedVersion + 1
      );
      requireValue(
        canonical(data.definition_ref) === canonical(payload.definition_ref) &&
          canonical(data.approved_subject_ref) === canonical(payload.approved_subject_ref) &&
          canonical(data.manual_profile_ref) === canonical(payload.manual_profile_ref)
      );
      requireValue(response.status !== 201 || currentVersion === expectedVersion + 1);
      requireValue(response.headers.get("location") === root(expected) + `revisions/${data.id}/` && !signal?.aborted);
      return { data, etag: etag(expected, currentVersion), currentVersion };
    } catch {
      throw new ManualPlanClientError("UNKNOWN");
    }
  }
}
