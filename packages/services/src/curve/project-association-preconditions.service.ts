/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import type {
  CurveExistingWorkProductScope,
  CurveExistingWorkResult,
  CurveProjectAssociationPreconditionsV1,
} from "@plane/types";
import { validateCurveProjectAssociationPreconditionsV1 } from "./existing-work-contracts/validators.mjs";
import {
  CurveExistingWorkTransport,
  curveExistingWorkEtag,
  curveExistingWorkId,
  curveExistingWorkRoot,
} from "./existing-work-transport";
import { isCurveUuid, requireCurve, validateCurveScope, validateCurveWire } from "./existing-work-validation";

export function decodeCurveProjectAssociationPreconditionsV1(
  input: unknown,
  scope: CurveExistingWorkProductScope,
  sourceProjectId: string
): CurveProjectAssociationPreconditionsV1 {
  const expected = validateCurveScope(scope);
  requireCurve(isCurveUuid(sourceProjectId));
  const data = validateCurveWire(validateCurveProjectAssociationPreconditionsV1, input);
  requireCurve(
    data.workspace_id === expected.workspaceId &&
      data.product_id === expected.productId &&
      data.source_project_id === sourceProjectId
  );
  return data;
}
/** Minimal LOCAL native read; no mutation, role inference, source expansion or retry. */
export class CurveProjectAssociationPreconditionsService extends CurveExistingWorkTransport {
  retrieve(
    workspaceSlug: string,
    scope: CurveExistingWorkProductScope,
    sourceProjectId: string,
    signal?: AbortSignal
  ): Promise<CurveExistingWorkResult<CurveProjectAssociationPreconditionsV1>> {
    return this.safely(async () => {
      const expected = validateCurveScope(scope);
      requireCurve(isCurveUuid(sourceProjectId));
      const path = `${curveExistingWorkRoot(workspaceSlug)}products/${curveExistingWorkId(expected.productId)}/project-association-preconditions/?source_project_id=${curveExistingWorkId(sourceProjectId)}`;
      const response = await this.read(path, signal);
      const data = decodeCurveProjectAssociationPreconditionsV1(response.data, expected, sourceProjectId);
      return {
        data,
        etag: curveExistingWorkEtag(response, `"curve-product:${data.product_id}:v${data.product_version}"`),
      };
    });
  }
}
