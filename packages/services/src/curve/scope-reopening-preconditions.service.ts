/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import type {
  CurveExistingWorkResult,
  CurveScopeReopeningPreconditionsV1,
  CurveScopeReopeningReadTarget,
} from "@plane/types";
import { validateCurveScopeReopeningPreconditionsV1 } from "./existing-work-contracts/validators.mjs";
import {
  CurveExistingWorkTransport,
  curveExistingWorkEtag,
  curveExistingWorkId,
  curveExistingWorkRoot,
} from "./existing-work-transport";
import { isCurveUuid, isCurveVersion, requireCurve, validateCurveWire } from "./existing-work-validation";

function snapshotTarget(target: CurveScopeReopeningReadTarget): CurveScopeReopeningReadTarget {
  const snapshot = {
    workspaceId: target.workspaceId,
    initiativeId: target.initiativeId,
    expectedInitiativeVersion: target.expectedInitiativeVersion,
  };
  requireCurve(isCurveUuid(snapshot.workspaceId) && isCurveUuid(snapshot.initiativeId));
  requireCurve(snapshot.expectedInitiativeVersion === undefined || isCurveVersion(snapshot.expectedInitiativeVersion));
  return snapshot;
}
export function decodeCurveScopeReopeningPreconditionsV1(
  input: unknown,
  target: CurveScopeReopeningReadTarget
): CurveScopeReopeningPreconditionsV1 {
  const expected = snapshotTarget(target);
  const data = validateCurveWire(validateCurveScopeReopeningPreconditionsV1, input);
  requireCurve(data.workspace_id === expected.workspaceId && data.initiative_id === expected.initiativeId);
  requireCurve(
    expected.expectedInitiativeVersion === undefined || data.initiative_version === expected.expectedInitiativeVersion
  );
  return data;
}
/** Minimal default-off Product-Approver read; no old-source lookup, write, or capability inference. */
export class CurveScopeReopeningPreconditionsService extends CurveExistingWorkTransport {
  retrieve(
    workspaceSlug: string,
    target: CurveScopeReopeningReadTarget,
    signal?: AbortSignal
  ): Promise<CurveExistingWorkResult<CurveScopeReopeningPreconditionsV1>> {
    return this.safely(async () => {
      const expected = snapshotTarget(target);
      const path = `${curveExistingWorkRoot(workspaceSlug)}initiatives/${curveExistingWorkId(expected.initiativeId)}/scope-reopening/v1/preconditions/`;
      const response = await this.read(path, signal);
      const data = decodeCurveScopeReopeningPreconditionsV1(response.data, expected);
      return { data, etag: curveExistingWorkEtag(response, `"${data.initiative_version}"`) };
    });
  }
}
