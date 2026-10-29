/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { useEffect, useRef, useState } from "react";
import type { CurveItemMetadata } from "@plane/types";
import type { DocumentApprovalStatus } from "@/components/curve/initiatives/document-review-stages";
import prd from "@/services/curve-local-prd.service";
import plan from "@/services/curve-local-plan.service";
export type RoadmapApprovals = [DocumentApprovalStatus, DocumentApprovalStatus];
const unavailable: RoadmapApprovals = ["UNAVAILABLE", "UNAVAILABLE"];
export async function readRoadmapApprovals(
  slug: string,
  workspaceId: string,
  productId: string,
  item: CurveItemMetadata,
  signal: AbortSignal
): Promise<RoadmapApprovals> {
  const scope = { workspaceId, productId, initiativeId: item.initiative.id };
  const current = await prd.retrieveReview(slug, scope, signal);
  if (current.initiative_version !== item.initiative.version) return unavailable;
  if (!current.source) return ["EMPTY", "LOCKED"];
  if (!current.submission_is_current) return ["READY", "LOCKED"];
  if (current.decision?.state === "CHANGES_REQUESTED") return ["CHANGES", "LOCKED"];
  if (current.decision?.state !== "APPROVED") return ["REVIEW", "LOCKED"];
  const reopening = await prd.retrieveReopening(slug, scope, current, signal);
  if (reopening.reopening?.source_id === current.source.id) return ["UPDATING", "LOCKED"];
  const technical = await plan.retrieveReview(slug, scope, signal);
  if (
    technical.initiative_version !== current.initiative_version ||
    technical.prd_submission.id !== current.submission?.id ||
    technical.prd_submission.digest !== current.submission.digest ||
    technical.prd_approval.id !== current.decision.id ||
    technical.prd_approval.digest !== current.decision.digest
  )
    return unavailable;
  const status = !technical.revision
    ? "EMPTY"
    : !technical.revision_is_current
      ? "UPDATING"
      : !technical.submission
        ? "READY"
        : technical.decision?.state === "APPROVED"
          ? "APPROVED"
          : technical.decision?.state === "CHANGES_REQUESTED"
            ? "CHANGES"
            : "REVIEW";
  return ["APPROVED", status];
}
/** Current metadata only; never loads document bodies or feedback. Four concurrent reads maximum. */
export function useCurveRoadmapApprovals(
  slug: string,
  workspaceId: string,
  productId: string,
  actorId: string | undefined,
  items: CurveItemMetadata[]
) {
  const key = JSON.stringify([
    slug,
    workspaceId,
    productId,
    actorId,
    items.map((item) => [item.id, item.initiative.id, item.initiative.version]),
  ]);
  const identity = useRef({ key });
  if (identity.current.key !== key) identity.current = { key };
  const session = identity.current;
  const [state, setState] = useState<{ session: object; values: Record<string, RoadmapApprovals> }>();
  useEffect(() => {
    const controller = new AbortController();
    let index = 0;
    const valid = () => !controller.signal.aborted && identity.current === session;
    const set = (id: string, statuses: RoadmapApprovals) => {
      if (valid())
        setState((previous) => ({
          session,
          values: { ...(previous?.session === session ? previous.values : {}), [id]: statuses },
        }));
    };
    setState(undefined);
    if (!actorId) return () => controller.abort();
    if (items.length > 1000) {
      setState({ session, values: Object.fromEntries(items.map((item) => [item.id, unavailable])) });
      return () => controller.abort();
    }
    async function worker() {
      while (valid() && index < items.length) {
        const item = items[index++];
        try {
          set(item.id, await readRoadmapApprovals(slug, workspaceId, productId, item, controller.signal));
        } catch {
          set(item.id, unavailable);
        }
      }
    }
    for (let i = 0; i < 4; i += 1) void worker();
    return () => controller.abort();
    // Identity includes the exact item/version list; array allocation cannot restart these reads.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);
  return state?.session === session ? state.values : {};
}
