/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import {
  CurveExistingWorkError,
  CurveProjectAssociationService,
  CurveProjectAssociationPreconditionsService,
  isCurveUuid,
  isCurveVersion,
} from "@plane/services";
import type { AssociationPort, AssociationProduct } from "@/components/curve/projects/project-association-model";
import curveService from "@/services/curve.service";

const association = new CurveProjectAssociationService();
const preconditions = new CurveProjectAssociationPreconditionsService();
const checkAbort = (signal: AbortSignal) => {
  if (signal.aborted) throw new CurveExistingWorkError("CANCELLED");
};

/** Validate only the bounded Product projection this screen consumes. No owner or role is authority. */
export function readAssociationProduct(value: unknown, workspaceId: string): AssociationProduct {
  if (!value || typeof value !== "object") throw new CurveExistingWorkError("INVALID");
  const item = value as Record<string, unknown>;
  if (
    !isCurveUuid(item.id) ||
    item.workspace_id !== workspaceId ||
    item.state !== "ACTIVE" ||
    !isCurveVersion(item.version) ||
    typeof item.name !== "string" ||
    !item.name.trim() ||
    typeof item.key !== "string" ||
    !item.key.trim()
  )
    throw new CurveExistingWorkError("INVALID");
  return {
    id: item.id,
    workspace_id: workspaceId,
    state: "ACTIVE",
    name: item.name,
    key: item.key,
    version: item.version,
  };
}

/** Production adapter contains only authenticated services. Synthetic data lives in tests. */
export const curveProjectAssociationPort: AssociationPort = {
  async listProducts(slug, workspaceId, signal) {
    if (!isCurveUuid(workspaceId)) throw new CurveExistingWorkError("INVALID");
    const products: AssociationProduct[] = [];
    const ids = new Set<string>();
    const cursors = new Set<string>();
    let cursor: string | undefined;
    let pageCount = 0;
    do {
      checkAbort(signal);
      // Bound provider pagination; exceeding the limit is unavailable, never a partial success.
      if (pageCount >= 100) throw new CurveExistingWorkError("UNAVAILABLE");
      pageCount += 1;
      // Existing Product pages are cursor-dependent. Never infer an empty source from a failed page.
      // oxlint-disable-next-line no-await-in-loop
      const page = await curveService.listProducts(slug, { state: "ACTIVE", pageSize: 100, cursor });
      checkAbort(signal);
      if (!page || !Array.isArray(page.results) || page.results.length > 100)
        throw new CurveExistingWorkError("INVALID");
      for (const item of page.results) {
        const product = readAssociationProduct(item, workspaceId);
        if (ids.has(product.id)) throw new CurveExistingWorkError("INVALID");
        ids.add(product.id);
        products.push(product);
      }
      const next = page.next_cursor;
      if (next !== null && next !== undefined && (typeof next !== "string" || !next.trim()))
        throw new CurveExistingWorkError("INVALID");
      if (next && cursors.has(next)) throw new CurveExistingWorkError("INVALID");
      if (next) cursors.add(next);
      cursor = next ?? undefined;
    } while (cursor);
    return products;
  },
  async discover(slug, scope, sourceProjectId, signal) {
    const result = await preconditions.retrieve(slug, scope, sourceProjectId, signal);
    return result.data;
  },
  create: (slug, scope, payload, options) => association.create(slug, scope, payload, options),
};
