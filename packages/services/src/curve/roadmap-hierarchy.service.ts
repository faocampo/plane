/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import type {
  CurveExistingWorkProductScope,
  CurveFeaturePage,
  CurveMilestonePage,
  CurveRoadmapPage,
} from "@plane/types";
import { CurveExistingWorkTransport, curveExistingWorkRoot, curveExistingWorkEtag } from "./existing-work-transport";
import {
  CurveExistingWorkError,
  isCurveUuid,
  isCurveVersion,
  requireCurve,
  validateCurveScope,
} from "./existing-work-validation";
import { closed } from "./roadmap-items.validation";

type ReadOptions = { pageSize?: number; cursor?: string; signal?: AbortSignal };
const metadataKeys = ["id", "version", "name", "created_at", "updated_at"];
const hierarchyKeys = [...metadataKeys, "schema_version", "workspace_id", "product_id"];
function detached(input: unknown): unknown {
  try {
    const value: unknown = structuredClone(input);
    requireCurve(new TextEncoder().encode(JSON.stringify(value)).byteLength <= 262144);
    return value;
  } catch {
    throw new CurveExistingWorkError();
  }
}
function timestamp(value: unknown) {
  requireCurve(
    typeof value === "string" &&
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/.test(value) &&
      Number.isFinite(Date.parse(value))
  );
  date((value as string).slice(0, 10));
}
function date(value: unknown): asserts value is string | null {
  if (value === null) return;
  requireCurve(typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && !value.startsWith("0000"));
  const parsed = new Date(value + "T00:00:00Z");
  requireCurve(Number.isFinite(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value);
}
function schedule(start: unknown, end: unknown) {
  date(start);
  date(end);
  if (start !== null && end !== null) requireCurve(start <= end);
}
function metadata(row: Record<string, unknown>) {
  requireCurve(isCurveUuid(row.id) && isCurveVersion(row.version));
  requireCurve(
    typeof row.name === "string" &&
      row.name.trim().length > 0 &&
      [...row.name].length <= 255 &&
      !row.name.includes("\0")
  );
  requireCurve(new TextDecoder("utf-8", { fatal: true }).decode(new TextEncoder().encode(row.name)) === row.name);
  timestamp(row.created_at);
  timestamp(row.updated_at);
}
function scoped(row: Record<string, unknown>, scope: CurveExistingWorkProductScope) {
  metadata(row);
  requireCurve(
    row.schema_version === "1.0" && row.workspace_id === scope.workspaceId && row.product_id === scope.productId
  );
}
function page(input: unknown, keys: string[], pageSize: number) {
  const value = detached(input);
  closed(value, keys);
  requireCurve(Array.isArray(value.results) && value.results.length <= pageSize);
  requireCurve(
    value.next_cursor === null || (typeof value.next_cursor === "string" && value.results.length === pageSize)
  );
  return value as Record<string, unknown> & { results: unknown[]; next_cursor: string | null };
}
function uuidOrder(rows: unknown[], after?: string) {
  let previous = after ?? "";
  for (const row of rows) {
    const id = (row as { id: string }).id;
    requireCurve(id > previous);
    previous = id;
  }
  return previous;
}
function milestoneCursor(value: string) {
  const match = /^([1-9][0-9]*):(0|[1-9][0-9]*):([0-9a-f-]{36})$/.exec(value);
  requireCurve(
    match !== null &&
      isCurveVersion(Number(match[1])) &&
      Number.isSafeInteger(Number(match[2])) &&
      isCurveUuid(match[3])
  );
  return { version: Number(match[1]), position: Number(match[2]), id: match[3] };
}
function options(input: ReadOptions, milestones = false) {
  const { pageSize = 50, cursor, signal } = input;
  requireCurve(Number.isInteger(pageSize) && pageSize >= 1 && pageSize <= 100);
  if (cursor !== undefined) {
    if (milestones) milestoneCursor(cursor);
    else requireCurve(isCurveUuid(cursor));
  }
  return { pageSize, cursor, signal };
}
function root(slug: string, scope: CurveExistingWorkProductScope) {
  return `${curveExistingWorkRoot(slug)}products/${scope.productId}/`;
}
/** Metadata-only choices for the Roadmap screen. Protected Feature detail is deliberately a separate API. */
export class CurveRoadmapHierarchyService extends CurveExistingWorkTransport {
  listRoadmaps(slug: string, scope: CurveExistingWorkProductScope, input: ReadOptions = {}): Promise<CurveRoadmapPage> {
    return this.safely(async () => {
      const expected = validateCurveScope(scope);
      const { pageSize, cursor, signal } = options(input);
      const query = new URLSearchParams({ page_size: String(pageSize), ...(cursor ? { cursor } : {}) });
      const response = await this.read(`${root(slug, expected)}roadmaps/?${query}`, signal);
      const value = page(response.data, ["results", "next_cursor"], pageSize);
      for (const row of value.results) {
        closed(row, [...hierarchyKeys, "owner_user_id", "horizon_start", "horizon_end"]);
        scoped(row, expected);
        requireCurve(isCurveUuid(row.owner_user_id));
        schedule(row.horizon_start, row.horizon_end);
      }
      const last = uuidOrder(value.results, cursor);
      requireCurve(value.next_cursor === null || value.next_cursor === last);
      return value as unknown as CurveRoadmapPage;
    });
  }
  listMilestones(
    slug: string,
    scope: CurveExistingWorkProductScope & { roadmapId: string },
    input: ReadOptions = {}
  ): Promise<CurveMilestonePage> {
    return this.safely(async () => {
      const expected = validateCurveScope(scope);
      requireCurve(isCurveUuid(expected.roadmapId));
      const { pageSize, cursor, signal } = options(input, true);
      const query = new URLSearchParams({ page_size: String(pageSize), ...(cursor ? { cursor } : {}) });
      const response = await this.read(
        `${root(slug, expected)}roadmaps/${expected.roadmapId}/milestones/?${query}`,
        signal
      );
      const value = page(response.data, ["results", "next_cursor", "roadmap_version"], pageSize);
      requireCurve(isCurveVersion(value.roadmap_version));
      curveExistingWorkEtag(response, `"curve-roadmap:${expected.roadmapId}:v${value.roadmap_version}"`);
      let previous = cursor ? milestoneCursor(cursor) : undefined;
      if (previous) requireCurve(previous.version === value.roadmap_version);
      for (const row of value.results) {
        closed(row, [...hierarchyKeys, "roadmap_id", "type", "position", "target_start", "target_end"]);
        scoped(row, expected);
        requireCurve(
          row.roadmap_id === expected.roadmapId && Number.isSafeInteger(row.position) && (row.position as number) >= 0
        );
        requireCurve(
          ["RELEASE_VERSION", "CALENDAR_PERIOD", "PRODUCT_OUTCOME", "INTERNAL_DEVELOPMENT_PHASE"].includes(
            row.type as string
          )
        );
        schedule(row.target_start, row.target_end);
        requireCurve(
          !previous ||
            (row.position as number) > previous.position ||
            (row.position === previous.position && (row.id as string) > previous.id)
        );
        previous = { version: value.roadmap_version, position: row.position as number, id: row.id as string };
      }
      requireCurve(
        value.next_cursor === null ||
          (previous && value.next_cursor === `${previous.version}:${previous.position}:${previous.id}`)
      );
      return value as unknown as CurveMilestonePage;
    });
  }
  listFeatures(slug: string, scope: CurveExistingWorkProductScope, input: ReadOptions = {}): Promise<CurveFeaturePage> {
    return this.safely(async () => {
      const expected = validateCurveScope(scope);
      const { pageSize, cursor, signal } = options(input);
      const query = new URLSearchParams({ page_size: String(pageSize), ...(cursor ? { after: cursor } : {}) });
      const response = await this.read(`${root(slug, expected)}features/?${query}`, signal);
      const value = page(response.data, ["results", "next_cursor", "is_editor"], pageSize);
      requireCurve(typeof value.is_editor === "boolean");
      for (const row of value.results) {
        closed(row, metadataKeys);
        metadata(row);
      }
      const last = uuidOrder(value.results, cursor);
      requireCurve(value.next_cursor === null || value.next_cursor === last);
      return value as unknown as CurveFeaturePage;
    });
  }
}
