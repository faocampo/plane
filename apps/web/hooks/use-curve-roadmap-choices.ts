/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { CurveExistingWorkError } from "@plane/services";
import type { CurveExistingWorkReadState } from "@plane/services";
import type {
  CurveExistingWorkProductScope,
  CurveFeaturePage,
  CurveMilestonePage,
  CurveRoadmapPage,
} from "@plane/types";
import hierarchy from "@/services/curve-roadmap-hierarchy.service";
import native from "@/services/curve-project-read.service";

type Choices = {
  roadmaps: CurveRoadmapPage;
  milestones: CurveMilestonePage | null;
  features: CurveFeaturePage;
  reviewers: { id: string; name: string }[];
};
type Cursors = { roadmaps?: string; milestones?: string; features?: string };
const empty: CurveExistingWorkReadState<Choices> = { status: "IDLE", data: null };
/** Explicit bounded pages: the screen must expose each returned next_cursor rather than infer completeness. */
export function useCurveRoadmapChoices(
  workspaceSlug: string,
  actorId: string | undefined,
  scope: CurveExistingWorkProductScope,
  roadmapId?: string,
  cursors: Cursors = {}
) {
  const { workspaceId, productId } = scope;
  const { roadmaps, milestones, features } = cursors;
  const key = JSON.stringify([
    workspaceSlug,
    actorId ?? null,
    workspaceId,
    productId,
    roadmapId ?? null,
    roadmaps ?? null,
    milestones ?? null,
    features ?? null,
  ]);
  const identity = useRef<{ key: string; controller?: AbortController }>({ key });
  if (identity.current.key !== key) identity.current = { key };
  const session = identity.current;
  const [state, setState] = useState<{ session: object; value: CurveExistingWorkReadState<Choices> }>();
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => {
    identity.current.controller?.abort();
    setState(undefined);
    setRevision((value) => value + 1);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    session.controller = controller;
    if (!actorId || !workspaceSlug || !workspaceId || !productId) return () => controller.abort();
    setState({ session, value: { status: "LOADING", data: null } });
    const expected = { workspaceId, productId };
    const valid = () => identity.current === session && !controller.signal.aborted;
    void Promise.all([
      hierarchy.listRoadmaps(workspaceSlug, expected, { pageSize: 100, cursor: roadmaps, signal: controller.signal }),
      roadmapId
        ? hierarchy.listMilestones(
            workspaceSlug,
            { ...expected, roadmapId },
            { pageSize: 100, cursor: milestones, signal: controller.signal }
          )
        : Promise.resolve(null),
      hierarchy.listFeatures(workspaceSlug, expected, { pageSize: 100, cursor: features, signal: controller.signal }),
      native.listMembers(workspaceSlug, controller.signal),
    ])
      .then(([roadmapPage, milestonePage, featurePage, members]) => {
        if (!valid()) return;
        const reviewers = members
          .filter(
            (row) =>
              row.is_active !== false &&
              row.member &&
              (!("is_active" in row.member) || row.member.is_active !== false) &&
              row.member.is_bot !== true
          )
          .map(({ member }) => ({
            id: member.id,
            name:
              member.display_name ||
              [member.first_name, member.last_name].filter(Boolean).join(" ") ||
              "Name unavailable",
          }));
        setState({
          session,
          value: {
            status: "READY",
            data: { roadmaps: roadmapPage, milestones: milestonePage, features: featurePage, reviewers },
          },
        });
      })
      .catch((error: unknown) => {
        if (!valid()) return;
        // One denied source invalidates the complete choice set; never leave an old roster visible.
        controller.abort();
        const status = (error as { response?: { status?: number } })?.response?.status;
        const code =
          error instanceof CurveExistingWorkError
            ? error.code
            : [401, 403, 404].includes(status ?? 0)
              ? "UNAVAILABLE"
              : "TRANSPORT";
        setState({ session, value: { status: "UNAVAILABLE", data: null, code } });
      });
    return () => controller.abort();
  }, [session, actorId, workspaceSlug, workspaceId, productId, roadmapId, roadmaps, milestones, features, revision]);
  useEffect(() => {
    window.addEventListener("focus", refresh);
    window.addEventListener("online", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      window.removeEventListener("online", refresh);
    };
  }, [refresh]);
  return { choices: state?.session === session ? state.value : empty, refresh };
}
