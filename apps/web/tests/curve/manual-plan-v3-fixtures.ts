// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import f0 from "./manual-plan-v3-fixtures/revision.valid.json";
import f1 from "./manual-plan-v3-fixtures/save.valid.json";
import f2 from "./manual-plan-v3-fixtures/status-current.valid.json";
import f3 from "./manual-plan-v3-fixtures/status-absent.valid.json";
import type {
  ManualPlanRevisionV3,
  ManualPlanSaveV3,
  ManualPlanStatusV3,
  ManualPlanTargetV3,
} from "../../../../packages/services/src/curve/manual-plan-draft-v3.types";
const fixtures: Record<string, unknown> = {
  "revision.valid": f0,
  "save.valid": f1,
  "status-current.valid": f2,
  "status-absent.valid": f3,
};
export function fixture<T>(name: string): T {
  return structuredClone(fixtures[name]) as T;
}
export const revision = fixture<ManualPlanRevisionV3>("revision.valid");
export const payload = fixture<ManualPlanSaveV3>("save.valid");
export const status = fixture<ManualPlanStatusV3>("status-current.valid");
export const target: ManualPlanTargetV3 = {
  workspaceSlug: "synthetic",
  workspaceId: revision.workspace_id,
  productId: revision.product_id,
  initiativeId: revision.initiative_id,
};
export const result = <T>(data: T, currentVersion = 10) => ({
  data,
  currentVersion,
  etag: `"curve-initiative:${target.initiativeId}:v${currentVersion}"`,
});
export const response = (data: unknown, code = 200, headers = {}) =>
  new Response(JSON.stringify(data), {
    status: code,
    headers: { "Content-Type": "application/json", ETag: result(null).etag, ...headers },
  });
