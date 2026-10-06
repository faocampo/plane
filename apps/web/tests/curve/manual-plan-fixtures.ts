import f0 from "../../../../candidates/curve-manual-plan-v2/overlay/manual_plan_v2/contract_snapshot/fixtures/revision.valid.json";
import f1 from "../../../../candidates/curve-manual-plan-v2/overlay/manual_plan_v2/contract_snapshot/fixtures/save.valid.json";
import f2 from "../../../../candidates/curve-manual-plan-v2/overlay/manual_plan_v2/contract_snapshot/fixtures/status-current.valid.json";
import f3 from "../../../../candidates/curve-manual-plan-v2/overlay/manual_plan_v2/contract_snapshot/fixtures/status-absent.valid.json";
import type {
  ManualPlanRevision,
  ManualPlanSave,
  ManualPlanStatus,
  ManualPlanTarget,
} from "../../../../packages/services/src/curve/manual-plan-draft.types";
const fixtures: Record<string, unknown> = {
  "revision.valid": f0,
  "save.valid": f1,
  "status-current.valid": f2,
  "status-absent.valid": f3,
};
export function fixture<T>(name: string): T {
  return structuredClone(fixtures[name]) as T;
}
export const revision = fixture<ManualPlanRevision>("revision.valid");
export const payload = fixture<ManualPlanSave>("save.valid");
export const status = fixture<ManualPlanStatus>("status-current.valid");
export const target: ManualPlanTarget = {
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
