/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { API_BASE_URL } from "@plane/constants";
import type { ICurveOperationSummary, ICurveProblemDetails, TCurveConnectionState } from "@plane/types";
import {
  applyCurveSSEEvent,
  normalizeCurveProblem,
  operationETag,
  parseCurveSSEBlock,
} from "@/components/curve/curve-foundation-state";
import curveService from "@/services/curve.service";

const reconnectDelay = (attempt: number) => Math.min(1_000 * 2 ** attempt, 8_000);
const sleep = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));
const cursorKey = (workspaceSlug: string) => `curve:foundation:last-event:${workspaceSlug}`;
const freshIdempotencyKey = (scope: string) => `${scope}:${crypto.randomUUID()}`;
const apiBaseUrl = API_BASE_URL.replace(/\/$/, "");
const isFoundationProbe = (operation: ICurveOperationSummary): boolean =>
  operation.operation_type === "FOUNDATION_PROBE";

export interface ICurveVisibleUpdate {
  eventId: string;
  eventType: string;
  status?: ICurveOperationSummary["status"];
  occurredAt: string;
}

export const prependCurveVisibleUpdate = (
  currentUpdates: ICurveVisibleUpdate[],
  nextUpdate: ICurveVisibleUpdate
): ICurveVisibleUpdate[] => {
  if (currentUpdates[0]?.status === nextUpdate.status) return currentUpdates;
  return [nextUpdate, ...currentUpdates].slice(0, 3);
};

export const useCurveFoundation = (workspaceSlug: string | undefined, workspaceId: string | undefined) => {
  const [operation, setOperation] = useState<ICurveOperationSummary>();
  const [etag, setEtag] = useState<string>();
  const [problem, setProblem] = useState<ICurveProblemDetails>();
  const [connectionState, setConnectionState] = useState<TCurveConnectionState>("CONNECTING");
  const [updates, setUpdates] = useState<ICurveVisibleUpdate[]>([]);
  const [lastEventId, setLastEventId] = useState<string>();
  const [lastUpdateAt, setLastUpdateAt] = useState<string>();
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [isPermissionLimited, setIsPermissionLimited] = useState(false);
  const [streamGeneration, setStreamGeneration] = useState(0);
  const createInFlight = useRef(false);
  const cancelInFlight = useRef(false);
  const processedEventIds = useRef(new Set<string>());

  const loadCurrentOperation = useCallback(async () => {
    if (!workspaceSlug) return;
    setIsLoading(true);
    setProblem(undefined);
    try {
      const page = await curveService.listOperations(workspaceSlug, 1, undefined, "FOUNDATION_PROBE");
      const latest = page.results[0];
      if (!latest || !isFoundationProbe(latest)) {
        setOperation(undefined);
        setEtag(undefined);
        return;
      }
      const detail = await curveService.retrieveOperation(workspaceSlug, latest.id);
      if (!isFoundationProbe(detail.operation)) {
        setOperation(undefined);
        setEtag(undefined);
        return;
      }
      setOperation(detail.operation);
      setEtag(detail.etag);
      setLastUpdateAt(new Date().toISOString());
      setIsPermissionLimited(false);
    } catch (error) {
      const safeProblem = normalizeCurveProblem(error);
      setProblem(safeProblem);
      setIsPermissionLimited(safeProblem.status === 401 || safeProblem.status === 403);
    } finally {
      setIsLoading(false);
    }
  }, [workspaceSlug]);

  useEffect(() => {
    void loadCurrentOperation();
  }, [loadCurrentOperation]);

  useEffect(() => {
    if (!workspaceSlug || !workspaceId) return;
    const controller = new AbortController();
    let disposed = false;
    let attempt = 0;

    const consume = async (response: Response) => {
      if (!response.body) throw new Error("Curve event stream body is unavailable");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      const readNext = async (): Promise<void> => {
        if (disposed) return;
        const { done, value } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const blocks = buffer.split(/\r?\n\r?\n/);
        buffer = blocks.pop() ?? "";
        for (const block of blocks) {
          const event = parseCurveSSEBlock(block);
          if (!event || event.workspace_id !== workspaceId || processedEventIds.current.has(event.event_id)) continue;
          processedEventIds.current.add(event.event_id);
          window.sessionStorage.setItem(cursorKey(workspaceSlug), event.event_id);
          setLastEventId(event.event_id);
          setLastUpdateAt(event.occurred_at);
          setOperation((current) => {
            const next = applyCurveSSEEvent(current, event);
            if (next && next !== current) {
              setEtag(operationETag(next));
              setUpdates((currentUpdates) =>
                prependCurveVisibleUpdate(currentUpdates, {
                  eventId: event.event_id,
                  eventType: event.event_type,
                  status: event.data.status,
                  occurredAt: event.occurred_at,
                })
              );
            }
            return next;
          });
        }
        if (!done) await readNext();
      };

      await readNext();
    };

    const connect = async (): Promise<void> => {
      if (disposed) return;
      setConnectionState(attempt === 0 ? "CONNECTING" : "RECONNECTING");
      const resumeCursor = window.sessionStorage.getItem(cursorKey(workspaceSlug));
      try {
        const response = await fetch(`${apiBaseUrl}/api/v1/workspaces/${workspaceSlug}/curve/events/`, {
          credentials: "include",
          headers: {
            Accept: "text/event-stream",
            ...(resumeCursor ? { "Last-Event-ID": resumeCursor } : {}),
          },
          signal: controller.signal,
        });
        if (response.status === 410) {
          setConnectionState("STALE");
          setProblem({
            type: "https://curve.example.invalid/problems/curve-event-cursor-stale",
            title: "Live updates need to be resynchronized",
            status: 410,
          });
          return;
        }
        if (!response.ok) throw response;
        setConnectionState("LIVE");
        setProblem(undefined);
        attempt = 0;
        await consume(response);
        if (!disposed) attempt += 1;
      } catch (error) {
        if (disposed || controller.signal.aborted) return;
        attempt += 1;
        setConnectionState("RECONNECTING");
        if (error instanceof Response && (error.status === 401 || error.status === 403)) {
          setIsPermissionLimited(true);
          setConnectionState("OFFLINE");
          return;
        }
      }
      if (disposed) return;
      await sleep(reconnectDelay(Math.min(attempt, 3)));
      await connect();
    };

    void connect();
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [streamGeneration, workspaceId, workspaceSlug]);

  const createProbe = useCallback(async () => {
    if (!workspaceSlug || createInFlight.current) return;
    createInFlight.current = true;
    setIsCreating(true);
    setProblem(undefined);
    try {
      const result = await curveService.createFoundationProbe(workspaceSlug, freshIdempotencyKey("foundation-probe"));
      setOperation(result.operation);
      setEtag(result.etag);
      setUpdates([]);
      setLastUpdateAt(new Date().toISOString());
      setIsPermissionLimited(false);
    } catch (error) {
      const safeProblem = normalizeCurveProblem(error);
      setProblem(safeProblem);
      setIsPermissionLimited(safeProblem.status === 401 || safeProblem.status === 403);
    } finally {
      createInFlight.current = false;
      setIsCreating(false);
    }
  }, [workspaceSlug]);

  const cancelProbe = useCallback(async () => {
    if (!workspaceSlug || !operation || !isFoundationProbe(operation) || !etag || cancelInFlight.current) return;
    cancelInFlight.current = true;
    setIsCancelling(true);
    setProblem(undefined);
    try {
      const result = await curveService.cancelOperation(
        workspaceSlug,
        operation.id,
        etag,
        freshIdempotencyKey("cancel-foundation-probe")
      );
      setOperation(result.operation);
      setEtag(result.etag);
      setLastUpdateAt(new Date().toISOString());
    } catch (error) {
      const safeProblem = normalizeCurveProblem(error);
      await loadCurrentOperation();
      setProblem(safeProblem);
      setIsPermissionLimited(safeProblem.status === 401 || safeProblem.status === 403);
    } finally {
      cancelInFlight.current = false;
      setIsCancelling(false);
    }
  }, [etag, loadCurrentOperation, operation, workspaceSlug]);

  const resync = useCallback(async () => {
    if (!workspaceSlug) return;
    window.sessionStorage.removeItem(cursorKey(workspaceSlug));
    processedEventIds.current.clear();
    setLastEventId(undefined);
    setConnectionState("CONNECTING");
    await loadCurrentOperation();
    setStreamGeneration((value) => value + 1);
  }, [loadCurrentOperation, workspaceSlug]);

  return {
    operation,
    etag,
    problem,
    connectionState,
    updates,
    lastEventId,
    lastUpdateAt,
    isLoading,
    isCreating,
    isCancelling,
    isPermissionLimited,
    createProbe,
    cancelProbe,
    resync,
    refresh: loadCurrentOperation,
  };
};
