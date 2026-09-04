/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type {
  ICurveInitiative,
  ICurveInitiativeCreateRequest,
  ICurveInitiativeDraftUpdateRequest,
  ICurveProblemDetails,
  ICurveProduct,
  IWorkspaceMember,
} from "@plane/types";
import {
  CURVE_INITIATIVE_CONFLICT_STATUSES,
  CURVE_INITIATIVE_PERMISSION_STATUSES,
  mergeCurveInitiatives,
  toSafeCurveProblem,
} from "@/components/curve/initiatives/initiative-data";
import { useMember } from "@/hooks/store/use-member";
import curveService from "@/services/curve.service";

const CURVE_PAGE_SIZE = 100;

type TInitiativeTransition = "accept" | "pause" | "resume" | "cancel";

type TPendingMutationIntent = {
  fingerprint: string;
  idempotencyKey: string;
};

const canonicalizeMutationValue = (value: unknown): unknown => {
  if (Array.isArray(value)) return value.map(canonicalizeMutationValue);
  if (!value || typeof value !== "object") return value;

  return Object.fromEntries(
    Object.entries(value)
      .filter(([, entryValue]) => entryValue !== undefined)
      // oxlint-disable-next-line unicorn/no-array-sort -- the configured TypeScript target does not include Array.toSorted.
      .sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey))
      .map(([key, entryValue]) => [key, canonicalizeMutationValue(entryValue)])
  );
};

const mutationFingerprint = (intent: Record<string, unknown>) => JSON.stringify(canonicalizeMutationValue(intent));

export const useCurveInitiatives = (workspaceSlug?: string) => {
  const { workspace: workspaceMemberStore } = useMember();
  const requestGeneration = useRef(0);
  const mutationInFlight = useRef(false);
  const pendingMutationIntent = useRef<TPendingMutationIntent>();
  const [products, setProducts] = useState<ICurveProduct[]>([]);
  const [initiatives, setInitiatives] = useState<ICurveInitiative[]>([]);
  const [nextCursor, setNextCursor] = useState<string>();
  const [selectedId, setSelectedId] = useState<string>();
  const [selectedResource, setSelectedResource] = useState<ICurveInitiative>();
  const [selectedEtag, setSelectedEtag] = useState<string>();
  const [problem, setProblem] = useState<ICurveProblemDetails>();
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [isMutating, setIsMutating] = useState(false);
  const [isPermissionLimited, setIsPermissionLimited] = useState(false);

  const activeMembers = workspaceSlug
    ? workspaceMemberStore
        .getWorkspaceMemberIds(workspaceSlug)
        .map((memberId) => workspaceMemberStore.getWorkspaceMemberDetails(memberId))
        .filter(
          (member): member is IWorkspaceMember =>
            !!member && member.is_active !== false && !!member.member && member.member.is_bot !== true
        )
    : [];

  const replaceConfirmedInitiative = useCallback((initiative: ICurveInitiative, etag: string) => {
    setInitiatives((current) => mergeCurveInitiatives(current, [initiative]));
    setSelectedId(initiative.id);
    setSelectedResource(initiative);
    setSelectedEtag(etag);
  }, []);

  const idempotencyKeyFor = useCallback((fingerprint: string) => {
    if (pendingMutationIntent.current?.fingerprint === fingerprint) {
      return pendingMutationIntent.current.idempotencyKey;
    }

    const idempotencyKey = crypto.randomUUID();
    pendingMutationIntent.current = { fingerprint, idempotencyKey };
    return idempotencyKey;
  }, []);

  const confirmMutationIntent = useCallback((fingerprint: string) => {
    if (pendingMutationIntent.current?.fingerprint === fingerprint) pendingMutationIntent.current = undefined;
  }, []);

  const loadActiveProducts = useCallback(async (slug: string, generation: number) => {
    const accumulated: ICurveProduct[] = [];
    const seenIds = new Set<string>();
    const seenCursors = new Set<string>();
    let cursor: string | undefined;

    do {
      // Product pages are cursor-dependent and must be requested in server order.
      // oxlint-disable-next-line no-await-in-loop
      const page = await curveService.listProducts(slug, { state: "ACTIVE", pageSize: CURVE_PAGE_SIZE, cursor });
      if (generation !== requestGeneration.current) return [];
      for (const product of page.results) {
        if (!seenIds.has(product.id)) accumulated.push(product);
        seenIds.add(product.id);
      }
      const candidate = page.next_cursor ?? undefined;
      if (candidate && seenCursors.has(candidate)) break;
      if (candidate) seenCursors.add(candidate);
      cursor = candidate;
    } while (cursor);

    return accumulated;
  }, []);

  const loadInitial = useCallback(async () => {
    if (!workspaceSlug) {
      setIsLoading(false);
      return;
    }

    const generation = ++requestGeneration.current;
    setIsLoading(true);
    setProblem(undefined);
    setIsPermissionLimited(false);
    setProducts([]);
    setInitiatives([]);
    setNextCursor(undefined);
    setSelectedId(undefined);
    setSelectedResource(undefined);
    setSelectedEtag(undefined);
    mutationInFlight.current = false;
    pendingMutationIntent.current = undefined;
    setIsMutating(false);

    try {
      const [loadedProducts, initiativePage] = await Promise.all([
        loadActiveProducts(workspaceSlug, generation),
        curveService.listInitiatives(workspaceSlug, { pageSize: CURVE_PAGE_SIZE }),
        workspaceMemberStore.fetchWorkspaceMembers(workspaceSlug),
      ]).then(([productResult, initiativeResult]) => [productResult, initiativeResult] as const);
      if (generation !== requestGeneration.current) return;
      setProducts(loadedProducts);
      setInitiatives(initiativePage.results);
      setNextCursor(initiativePage.next_cursor ?? undefined);
      setSelectedId(initiativePage.results[0]?.id);
    } catch (error) {
      if (generation !== requestGeneration.current) return;
      const safeProblem = toSafeCurveProblem(error, "Initiatives could not be loaded");
      setProblem(safeProblem);
      setIsPermissionLimited(CURVE_INITIATIVE_PERMISSION_STATUSES.has(safeProblem.status));
    } finally {
      if (generation === requestGeneration.current) setIsLoading(false);
    }
  }, [loadActiveProducts, workspaceMemberStore, workspaceSlug]);

  useEffect(() => {
    void loadInitial();
    return () => {
      requestGeneration.current += 1;
    };
  }, [loadInitial]);

  const refreshSelected = useCallback(async () => {
    if (!workspaceSlug || !selectedId) return;
    const generation = requestGeneration.current;
    try {
      const result = await curveService.retrieveInitiative(workspaceSlug, selectedId);
      if (generation !== requestGeneration.current || selectedId !== result.initiative.id) return;
      replaceConfirmedInitiative(result.initiative, result.etag);
      setProblem(undefined);
    } catch (error) {
      if (generation !== requestGeneration.current) return;
      setProblem(toSafeCurveProblem(error, "The Initiative could not be refreshed"));
    }
  }, [replaceConfirmedInitiative, selectedId, workspaceSlug]);

  useEffect(() => {
    if (!selectedId) {
      setSelectedResource(undefined);
      setSelectedEtag(undefined);
      return;
    }
    void refreshSelected();
  }, [refreshSelected, selectedId]);

  const selectInitiative = useCallback((initiativeId: string) => {
    setProblem(undefined);
    setSelectedResource(undefined);
    setSelectedEtag(undefined);
    setSelectedId(initiativeId);
  }, []);

  const loadMore = useCallback(async () => {
    if (!workspaceSlug || !nextCursor || isLoadingMore) return;
    const generation = requestGeneration.current;
    setIsLoadingMore(true);
    try {
      const page = await curveService.listInitiatives(workspaceSlug, {
        pageSize: CURVE_PAGE_SIZE,
        cursor: nextCursor,
      });
      if (generation !== requestGeneration.current) return;
      setInitiatives((current) => mergeCurveInitiatives(current, page.results));
      setNextCursor(page.next_cursor ?? undefined);
      setProblem(undefined);
    } catch (error) {
      if (generation !== requestGeneration.current) return;
      setProblem(toSafeCurveProblem(error, "More Initiatives could not be loaded"));
    } finally {
      if (generation === requestGeneration.current) setIsLoadingMore(false);
    }
  }, [isLoadingMore, nextCursor, workspaceSlug]);

  const createInitiative = useCallback(
    async (payload: ICurveInitiativeCreateRequest) => {
      if (!workspaceSlug || mutationInFlight.current) return false;
      const generation = requestGeneration.current;
      mutationInFlight.current = true;
      setIsMutating(true);
      setProblem(undefined);
      const fingerprint = mutationFingerprint({ kind: "create", workspaceSlug, payload });
      try {
        const result = await curveService.createInitiative(workspaceSlug, payload, idempotencyKeyFor(fingerprint));
        if (generation !== requestGeneration.current) return false;
        confirmMutationIntent(fingerprint);
        setInitiatives((current) => [result.initiative, ...current.filter(({ id }) => id !== result.initiative.id)]);
        replaceConfirmedInitiative(result.initiative, result.etag);
        return true;
      } catch (error) {
        if (generation !== requestGeneration.current) return false;
        setProblem(toSafeCurveProblem(error, "The Initiative could not be created"));
        return false;
      } finally {
        if (generation === requestGeneration.current) {
          mutationInFlight.current = false;
          setIsMutating(false);
        }
      }
    },
    [confirmMutationIntent, idempotencyKeyFor, replaceConfirmedInitiative, workspaceSlug]
  );

  const updateInitiativeDraft = useCallback(
    async (payload: ICurveInitiativeDraftUpdateRequest) => {
      if (!workspaceSlug || !selectedId || !selectedEtag || mutationInFlight.current) return false;
      const generation = requestGeneration.current;
      mutationInFlight.current = true;
      setIsMutating(true);
      setProblem(undefined);
      const fingerprint = mutationFingerprint({
        kind: "update-draft",
        workspaceSlug,
        initiativeId: selectedId,
        etag: selectedEtag,
        payload,
      });
      try {
        const result = await curveService.updateInitiativeDraft(
          workspaceSlug,
          selectedId,
          payload,
          selectedEtag,
          idempotencyKeyFor(fingerprint)
        );
        if (generation !== requestGeneration.current) return false;
        confirmMutationIntent(fingerprint);
        replaceConfirmedInitiative(result.initiative, result.etag);
        return true;
      } catch (error) {
        if (generation !== requestGeneration.current) return false;
        setProblem(toSafeCurveProblem(error, "The Initiative draft could not be updated"));
        return false;
      } finally {
        if (generation === requestGeneration.current) {
          mutationInFlight.current = false;
          setIsMutating(false);
        }
      }
    },
    [confirmMutationIntent, idempotencyKeyFor, replaceConfirmedInitiative, selectedEtag, selectedId, workspaceSlug]
  );

  const transitionInitiative = useCallback(
    async (transition: TInitiativeTransition, reason?: string) => {
      if (!workspaceSlug || !selectedId || !selectedEtag || mutationInFlight.current) return false;
      const generation = requestGeneration.current;
      mutationInFlight.current = true;
      setIsMutating(true);
      setProblem(undefined);
      const fingerprint = mutationFingerprint({
        kind: "transition",
        workspaceSlug,
        initiativeId: selectedId,
        etag: selectedEtag,
        transition,
        reason: reason ?? "",
      });
      try {
        const idempotencyKey = idempotencyKeyFor(fingerprint);
        const result =
          transition === "accept"
            ? await curveService.acceptInitiativeRefinement(workspaceSlug, selectedId, selectedEtag, idempotencyKey)
            : transition === "pause"
              ? await curveService.pauseInitiative(
                  workspaceSlug,
                  selectedId,
                  { reason: reason ?? "" },
                  selectedEtag,
                  idempotencyKey
                )
              : transition === "resume"
                ? await curveService.resumeInitiative(
                    workspaceSlug,
                    selectedId,
                    { reason: reason ?? "" },
                    selectedEtag,
                    idempotencyKey
                  )
                : await curveService.cancelInitiative(
                    workspaceSlug,
                    selectedId,
                    { reason: reason ?? "" },
                    selectedEtag,
                    idempotencyKey
                  );
        if (generation !== requestGeneration.current) return false;
        confirmMutationIntent(fingerprint);
        replaceConfirmedInitiative(result.initiative, result.etag);
        return true;
      } catch (error) {
        if (generation !== requestGeneration.current) return false;
        setProblem(toSafeCurveProblem(error, "The Initiative action could not be completed"));
        return false;
      } finally {
        if (generation === requestGeneration.current) {
          mutationInFlight.current = false;
          setIsMutating(false);
        }
      }
    },
    [confirmMutationIntent, idempotencyKeyFor, replaceConfirmedInitiative, selectedEtag, selectedId, workspaceSlug]
  );

  const selectedInitiative = selectedResource ?? initiatives.find((initiative) => initiative.id === selectedId);

  return {
    products,
    initiatives,
    nextCursor,
    selectedInitiative,
    selectedEtag,
    activeMembers,
    problem,
    isLoading,
    isLoadingMore,
    isMutating,
    isPermissionLimited,
    isConflict: !!problem && CURVE_INITIATIVE_CONFLICT_STATUSES.has(problem.status),
    selectInitiative,
    loadMore,
    createInitiative,
    updateInitiativeDraft,
    acceptRefinement: () => transitionInitiative("accept"),
    pauseInitiative: (reason: string) => transitionInitiative("pause", reason),
    resumeInitiative: (reason: string) => transitionInitiative("resume", reason),
    cancelInitiative: (reason: string) => transitionInitiative("cancel", reason),
    refreshSelected,
    refresh: loadInitial,
  };
};
