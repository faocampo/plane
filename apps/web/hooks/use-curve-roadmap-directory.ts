/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { CurveExistingWorkError } from "@plane/services";
import type { CurveItemMetadata, CurveRoadmapScope } from "@plane/types";
import { curveProjectAssociationPort } from "@/services/curve-project-association.service";
import type { AssociationProduct } from "@/components/curve/projects/project-association-model";
import items from "@/services/curve-roadmap-items.service";

type Read<T> = { status: "LOADING" | "UNAVAILABLE"; data: null } | { status: "READY"; data: T };
function useDirectory<T>(identity: string, enabled: boolean, loader: (signal: AbortSignal) => Promise<T>) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{ identity: object; value: Read<T> }>();
  const active = useRef<{ key: string; controller?: AbortController }>({ key: identity });
  if (active.current.key !== identity) active.current = { key: identity };
  const session = active.current;
  const refresh = useCallback(() => {
    active.current.controller?.abort();
    setState(undefined);
    setRevision((value) => value + 1);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    session.controller = controller;
    setState(undefined);
    if (enabled)
      void loader(controller.signal)
        .then((data) => {
          if (active.current === session && !controller.signal.aborted)
            setState({ identity: session, value: { status: "READY", data } });
        })
        .catch(() => {
          if (active.current === session && !controller.signal.aborted)
            setState({ identity: session, value: { status: "UNAVAILABLE", data: null } });
        });
    return () => controller.abort();
  }, [session, enabled, loader, revision]);
  useEffect(() => {
    window.addEventListener("focus", refresh);
    window.addEventListener("online", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      window.removeEventListener("online", refresh);
    };
  }, [refresh]);
  return { read: state?.identity === session ? state.value : ({ status: "LOADING", data: null } as Read<T>), refresh };
}
export function useCurveRoadmapProducts(slug: string, workspaceId: string, actorId?: string) {
  const load = useCallback(
    (signal: AbortSignal) => curveProjectAssociationPort.listProducts(slug, workspaceId, signal),
    [slug, workspaceId]
  );
  return useDirectory<AssociationProduct[]>(JSON.stringify([slug, workspaceId, actorId]), !!actorId, load);
}
export function useCurveRoadmapOverview(slug: string, actorId: string | undefined, scope: CurveRoadmapScope) {
  const { productId, roadmapId } = scope;
  const load = useCallback(
    async (signal: AbortSignal) => {
      const result: CurveItemMetadata[] = [];
      const seen = new Set<string>();
      let after: string | undefined;
      let version: number | undefined;
      let canCreate: boolean | undefined;
      for (let page = 0; page < 100; page += 1) {
        if (signal.aborted) throw new CurveExistingWorkError("CANCELLED");
        // Cursor-dependent reads must complete before the milestone can claim an empty list.
        // oxlint-disable-next-line no-await-in-loop
        const next = await items.list(slug, { productId, roadmapId }, { pageSize: 100, after, signal });
        if (version !== undefined && (next.roadmap_version !== version || next.can_create !== canCreate))
          throw new CurveExistingWorkError("CONFLICT");
        version = next.roadmap_version;
        canCreate = next.can_create;
        for (const item of next.results) {
          if (seen.has(item.id)) throw new CurveExistingWorkError("INVALID");
          seen.add(item.id);
          result.push(item);
        }
        if (!next.next_cursor) return { items: result, version, canCreate };
        if (next.next_cursor === after || !seen.has(next.next_cursor)) throw new CurveExistingWorkError("INVALID");
        after = next.next_cursor;
      }
      throw new CurveExistingWorkError("UNAVAILABLE");
    },
    [slug, productId, roadmapId]
  );
  return useDirectory(JSON.stringify([slug, actorId, productId, roadmapId]), !!actorId && !!roadmapId, load);
}
