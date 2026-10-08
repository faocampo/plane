/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import type {
  CurveExistingWorkMutation,
  CurveExistingWorkProductScope,
  CurveExistingWorkResult,
  CurveProjectAssociation,
  CurveProjectAssociationCreate,
  CurveProjectAssociationEnd,
} from "@plane/types";
import {
  validateCurveProjectAssociationCreate,
  validateCurveProjectAssociationEnd,
} from "./existing-work-contracts/validators.mjs";
import {
  CurveExistingWorkTransport,
  curveExistingWorkEtag,
  curveExistingWorkId,
  curveExistingWorkMutation,
  curveExistingWorkRoot,
} from "./existing-work-transport";
import {
  decodeCurveProjectAssociation,
  requireCurve,
  validateCurveScope,
  validateCurveWire,
} from "./existing-work-validation";

/** Default-off candidate transport. Reads never grant authority; END currently fails closed server-side. */
export class CurveProjectAssociationService extends CurveExistingWorkTransport {
  retrieve(
    workspaceSlug: string,
    scope: CurveExistingWorkProductScope,
    associationId: string,
    signal?: AbortSignal
  ): Promise<CurveExistingWorkResult<CurveProjectAssociation>> {
    return this.safely(async () => {
      const expected = validateCurveScope(scope);
      const response = await this.read(
        `${curveExistingWorkRoot(workspaceSlug)}project-associations/${curveExistingWorkId(associationId)}/`,
        signal
      );
      const data = decodeCurveProjectAssociation(response.data, expected, { id: associationId });
      return { data, etag: curveExistingWorkEtag(response, `"curve-project-association:${data.id}:v${data.version}"`) };
    });
  }
  create(
    workspaceSlug: string,
    scope: CurveExistingWorkProductScope,
    payload: CurveProjectAssociationCreate,
    options: CurveExistingWorkMutation
  ): Promise<CurveExistingWorkResult<CurveProjectAssociation>> {
    return this.safely(async () => {
      const expected = validateCurveScope(scope);
      const body = validateCurveWire(validateCurveProjectAssociationCreate, payload, 65536);
      const command = curveExistingWorkMutation(options);
      const response = await this.mutate(
        `${curveExistingWorkRoot(workspaceSlug)}products/${curveExistingWorkId(expected.productId)}/project-associations/`,
        body,
        command,
        `"curve-product:${expected.productId}:v${command.expectedVersion}"`
      );
      return this.verifyMutation(command.signal, async () => {
        requireCurve(response.status === 201);
        const data = decodeCurveProjectAssociation(response.data, expected, { ...body, state: "ACTIVE", version: 1 });
        return {
          data,
          etag: curveExistingWorkEtag(response, `"curve-project-association:${data.id}:v${data.version}"`),
        };
      });
    });
  }
  /** No optimistic end or fallback: dependency reconciliation is unavailable in the current runtime. */
  end(
    workspaceSlug: string,
    scope: CurveExistingWorkProductScope,
    associationId: string,
    payload: CurveProjectAssociationEnd,
    options: CurveExistingWorkMutation
  ): Promise<CurveExistingWorkResult<CurveProjectAssociation>> {
    return this.safely(async () => {
      const expected = validateCurveScope(scope);
      const body = validateCurveWire(validateCurveProjectAssociationEnd, payload, 65536);
      const command = curveExistingWorkMutation(options);
      requireCurve(command.expectedVersion < Number.MAX_SAFE_INTEGER);
      const response = await this.mutate(
        `${curveExistingWorkRoot(workspaceSlug)}project-associations/${curveExistingWorkId(associationId)}/end/`,
        body,
        command,
        `"curve-project-association:${associationId}:v${command.expectedVersion}"`
      );
      return this.verifyMutation(command.signal, async () => {
        requireCurve(response.status === 200);
        const data = decodeCurveProjectAssociation(response.data, expected, {
          id: associationId,
          state: "ENDED",
          version: command.expectedVersion + 1,
        });
        requireCurve(data.end_reason === body.reason);
        return {
          data,
          etag: curveExistingWorkEtag(response, `"curve-project-association:${data.id}:v${data.version}"`),
        };
      });
    });
  }
}
