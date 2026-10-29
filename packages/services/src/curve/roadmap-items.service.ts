/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import type {
  CurveExistingWorkMutation,
  CurveItemCreate,
  CurveItemCreationResult,
  CurveItemScopePreparationResult,
  CurveItemPage,
  CurveItemRecoveryResult,
  CurveItemCancellationResult,
  CurveRoadmapScope,
} from "@plane/types";
import {
  CurveExistingWorkTransport,
  curveExistingWorkEtag,
  curveExistingWorkMutation,
  curveExistingWorkRoot,
} from "./existing-work-transport";
import { isCurveUuid, requireCurve } from "./existing-work-validation";
import { closed, decodeItemCreate, decodeItemPage, itemScope } from "./roadmap-items.validation";

function root(workspaceSlug: string, scope: CurveRoadmapScope) {
  const checked = itemScope(scope);
  return `${curveExistingWorkRoot(workspaceSlug)}products/${checked.productId}/roadmaps/${checked.roadmapId}/items/`;
}

function decodeRecovery(value: unknown): CurveItemRecoveryResult {
  requireCurve(value !== null && typeof value === "object" && !Array.isArray(value) && "state" in value);
  if (value.state === "UNRESOLVED") {
    closed(value, ["state"]);
    return { state: "UNRESOLVED" };
  }
  closed(value, ["state", "resource_ref"]);
  requireCurve(value.state === "COMPLETED" && "resource_ref" in value);
  const ref = value.resource_ref;
  closed(ref, ["resource_type", "resource_id", "resource_version", "initiative_ref"]);
  requireCurve(ref.resource_type === "ROADMAP_ITEM" && ref.resource_version === 1 && isCurveUuid(ref.resource_id));
  closed(ref.initiative_ref, ["resource_type", "resource_id", "resource_version"]);
  requireCurve(
    ref.initiative_ref.resource_type === "INITIATIVE" &&
      ref.initiative_ref.resource_version === 1 &&
      isCurveUuid(ref.initiative_ref.resource_id) &&
      ref.initiative_ref.resource_id !== ref.resource_id
  );
  return { state: "COMPLETED", resource_ref: structuredClone(ref) as CurveItemCreationResult["resource_ref"] };
}
export class CurveRoadmapItemService extends CurveExistingWorkTransport {
  cancelCreation(
    workspaceSlug: string,
    scope: CurveRoadmapScope,
    commandKey: string,
    signal?: AbortSignal
  ): Promise<CurveItemCancellationResult> {
    return this.safely(async () => {
      const checked = itemScope(scope);
      requireCurve(isCurveUuid(commandKey));
      const path = `${curveExistingWorkRoot(workspaceSlug)}products/${checked.productId}/roadmaps/${checked.roadmapId}/item-creation-receipts/cancel/`;
      const response = await this.mutate(path, {}, { idempotencyKey: commandKey, signal });
      return this.verifyMutation(signal, () => {
        requireCurve(response.status === 200);
        if (response.data?.state === "CANCELLED") {
          closed(response.data, ["state"]);
          return { state: "CANCELLED" };
        }
        return decodeRecovery(response.data);
      });
    });
  }

  reconcileCreation(
    workspaceSlug: string,
    scope: CurveRoadmapScope,
    commandKey: string,
    signal?: AbortSignal
  ): Promise<CurveItemRecoveryResult> {
    return this.safely(async () => {
      const checked = itemScope(scope);
      requireCurve(isCurveUuid(commandKey));
      const path = `${curveExistingWorkRoot(workspaceSlug)}products/${checked.productId}/roadmaps/${checked.roadmapId}/item-creation-receipts/`;
      const response = await this.read(path, signal, { "Idempotency-Key": commandKey });
      return decodeRecovery(response.data);
    });
  }

  prepareScope(
    workspaceSlug: string,
    scope: CurveRoadmapScope,
    payload: { body: string },
    options: CurveExistingWorkMutation
  ): Promise<CurveItemScopePreparationResult> {
    return this.safely(async () => {
      const checked = itemScope(scope);
      closed(payload, ["body"]);
      const body = payload.body;
      requireCurve(
        typeof body === "string" && body.trim().length > 0 && [...body].length <= 20000 && !body.includes("\0")
      );
      requireCurve(new TextDecoder("utf-8", { fatal: true }).decode(new TextEncoder().encode(body)) === body);
      const command = curveExistingWorkMutation(options);
      const path = `${curveExistingWorkRoot(workspaceSlug)}products/${checked.productId}/roadmaps/${checked.roadmapId}/item-scopes/`;
      const response = await this.mutate(
        path,
        { body },
        command,
        `"curve-roadmap:${checked.roadmapId}:v${command.expectedVersion}"`
      );
      return this.verifyMutation(command.signal, () => {
        requireCurve(response.status === 201);
        closed(response.data, ["resource_ref"]);
        const ref = response.data.resource_ref;
        closed(ref, ["resource_type", "resource_id", "resource_version", "scope_body"]);
        requireCurve(
          ref.resource_type === "PREPARED_ITEM_SCOPE" && isCurveUuid(ref.resource_id) && ref.resource_version === 1
        );
        const document = ref.scope_body;
        closed(document, ["object_id", "digest", "size_bytes", "media_type", "editor_schema_version"]);
        requireCurve(
          document.object_id === ref.resource_id &&
            typeof document.digest === "string" &&
            /^sha256:[a-f0-9]{64}$/.test(document.digest)
        );
        requireCurve(
          Number.isSafeInteger(document.size_bytes) &&
            (document.size_bytes as number) > 0 &&
            (document.size_bytes as number) <= 131072
        );
        requireCurve(
          document.media_type === "application/json" &&
            document.editor_schema_version === "curve.item-scope-markdown/v1-candidate"
        );
        const replay = response.headers["idempotent-replay"];
        requireCurve(replay === "true" || replay === "false");
        return {
          resource_ref: structuredClone(ref) as CurveItemScopePreparationResult["resource_ref"],
          replayed: replay === "true",
        };
      });
    });
  }

  list(
    workspaceSlug: string,
    scope: CurveRoadmapScope,
    options: { pageSize?: number; after?: string; signal?: AbortSignal } = {}
  ): Promise<CurveItemPage> {
    return this.safely(async () => {
      const expected = itemScope(scope);
      const { pageSize = 50, after, signal } = options;
      requireCurve(Number.isInteger(pageSize) && pageSize >= 1 && pageSize <= 100);
      requireCurve(after === undefined || isCurveUuid(after));
      const query = new URLSearchParams({ page_size: String(pageSize), ...(after ? { after } : {}) });
      const response = await this.read(`${root(workspaceSlug, expected)}?${query}`, signal);
      return decodeItemPage(response.data, expected, pageSize, after);
    });
  }
  create(
    workspaceSlug: string,
    scope: CurveRoadmapScope,
    payload: CurveItemCreate,
    options: CurveExistingWorkMutation
  ): Promise<CurveItemCreationResult> {
    return this.safely(async () => {
      const path = root(workspaceSlug, scope);
      const body = decodeItemCreate(payload);
      const command = curveExistingWorkMutation(options);
      const response = await this.mutate(
        path,
        body,
        command,
        `"curve-roadmap:${scope.roadmapId}:v${command.expectedVersion}"`
      );
      return this.verifyMutation(command.signal, () => {
        requireCurve(response.status === 201);
        closed(response.data, ["resource_ref"]);
        const ref = response.data.resource_ref;
        closed(ref, ["resource_type", "resource_id", "resource_version", "initiative_ref"]);
        requireCurve(
          ref.resource_type === "ROADMAP_ITEM" && ref.resource_version === 1 && isCurveUuid(ref.resource_id)
        );
        closed(ref.initiative_ref, ["resource_type", "resource_id", "resource_version"]);
        requireCurve(
          ref.initiative_ref.resource_type === "INITIATIVE" &&
            ref.initiative_ref.resource_version === 1 &&
            isCurveUuid(ref.initiative_ref.resource_id) &&
            ref.initiative_ref.resource_id !== ref.resource_id
        );
        const replay = response.headers["idempotent-replay"];
        requireCurve(replay === "true" || replay === "false");
        const etag = curveExistingWorkEtag(response, `"curve-roadmap-item:${ref.resource_id}:v1"`);
        return {
          resource_ref: structuredClone(ref) as CurveItemCreationResult["resource_ref"],
          etag,
          replayed: replay === "true",
        };
      });
    });
  }
}
