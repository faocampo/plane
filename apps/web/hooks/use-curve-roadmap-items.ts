/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { CurveExistingWorkError } from "@plane/services";
import type { CurveExistingWorkErrorCode, CurveExistingWorkReadState } from "@plane/services";
import type { CurveItemCreate, CurveItemCreationResult, CurveItemPage, CurveRoadmapScope } from "@plane/types";
import { itemCreationRecovery, ItemRecoveryUnavailable } from "@/components/curve/roadmap/item-creation-recovery";
import items from "@/services/curve-roadmap-items.service";

type CommandState =
  | { status: "IDLE" | "SAVING" | "CANCELLED" | "CANCELLING" | "RECOVERING" }
  | { status: "CREATED"; result: CurveItemCreationResult }
  | { status: "RECOVERED"; result: Pick<CurveItemCreationResult, "resource_ref"> }
  | { status: "FAILED" | "UNKNOWN"; code: CurveExistingWorkErrorCode };
type DraftPayload = Omit<CurveItemCreate, "scope_body">;
type Intent = {
  payload: CurveItemCreate | DraftPayload;
  expectedVersion: number;
  idempotencyKey: string;
  uncertain: boolean;
  preparation?: { body: string; idempotencyKey: string };
};
type Session = {
  key: string;
  readGeneration: number;
  readController?: AbortController;
  writeController?: AbortController;
  page?: CurveItemPage;
  intent?: Intent;
  recoveryReady?: boolean;
  recoveryKey?: string;
  cancellationKey?: string;
};
const idle: CurveExistingWorkReadState<CurveItemPage> = { status: "IDLE", data: null };
const codeOf = (error: unknown): CurveExistingWorkErrorCode =>
  error instanceof CurveExistingWorkError ? error.code : "TRANSPORT";

/** Draft bytes remain ephemeral; a durable opaque locator supports current-authorized receipt recovery. */
export function useCurveRoadmapItems(workspaceSlug: string, actorId: string | undefined, scope: CurveRoadmapScope) {
  const { productId, roadmapId } = scope;
  const key = JSON.stringify([workspaceSlug, actorId ?? null, productId, roadmapId]);
  const current = useRef<Session>({ key, readGeneration: 0 });
  const [read, setRead] = useState<{ session: Session; value: CurveExistingWorkReadState<CurveItemPage> }>();
  const [command, setCommand] = useState<{ session: Session; value: CommandState }>();
  // Render-time identity guard hides old data before effect cleanup, including A -> B -> A.
  if (current.current.key !== key) current.current = { key, readGeneration: 0 };
  const session = current.current;
  const active = useCallback(() => current.current === session, [session]);
  const journal = useCallback(() => {
    if (!actorId) throw new ItemRecoveryUnavailable();
    return itemCreationRecovery(window.sessionStorage, { workspaceSlug, actorId, productId, roadmapId });
  }, [workspaceSlug, actorId, productId, roadmapId]);
  const inspectRecovery = useCallback(() => {
    if (!active() || !actorId) return;
    try {
      session.recoveryKey = journal().read()?.commandKey;
      session.recoveryReady = true;
      if (session.recoveryKey) setCommand({ session, value: { status: "UNKNOWN", code: "UNAVAILABLE" } });
    } catch {
      session.recoveryReady = false;
      setCommand({ session, value: { status: "UNKNOWN", code: "UNAVAILABLE" } });
    }
  }, [active, actorId, journal, session]);

  const load = useCallback(
    async (after?: string) => {
      if (!active()) return;
      session.readController?.abort();
      const generation = ++session.readGeneration;
      session.page = undefined;
      setRead({ session, value: actorId ? { status: "LOADING", data: null } : idle });
      if (!actorId || !workspaceSlug || !productId || !roadmapId) return;
      const controller = new AbortController();
      session.readController = controller;
      const valid = () => active() && generation === session.readGeneration && !controller.signal.aborted;
      try {
        const page = await items.list(workspaceSlug, { productId, roadmapId }, { after, signal: controller.signal });
        if (!valid()) return;
        session.page = structuredClone(page);
        setRead({ session, value: { status: "READY", data: page } });
      } catch (error) {
        if (valid()) setRead({ session, value: { status: "UNAVAILABLE", data: null, code: codeOf(error) } });
      }
    },
    [active, session, key, actorId, workspaceSlug, productId, roadmapId]
  );
  const refresh = useCallback(() => {
    void load();
  }, [load]);
  useEffect(() => {
    inspectRecovery();
    refresh();
    window.addEventListener("focus", refresh);
    window.addEventListener("online", refresh);
    return () => {
      session.readGeneration += 1;
      session.readController?.abort();
      session.writeController?.abort();
      session.page = undefined;
      session.intent = undefined;
      window.removeEventListener("focus", refresh);
      window.removeEventListener("online", refresh);
    };
  }, [session, refresh, inspectRecovery]);

  const send = useCallback(
    async (intent: Intent, recovering = false) => {
      if (!active() || session.writeController || !session.page?.can_create || !actorId) return;
      const controller = new AbortController();
      session.writeController = controller;
      setCommand({ session, value: { status: recovering ? "RECOVERING" : "SAVING" } });
      try {
        if (intent.preparation) {
          const prepared = await items.prepareScope(
            workspaceSlug,
            { productId, roadmapId },
            { body: intent.preparation.body },
            {
              expectedVersion: intent.expectedVersion,
              idempotencyKey: intent.preparation.idempotencyKey,
              signal: controller.signal,
            }
          );
          if (!active() || controller.signal.aborted) return;
          intent.payload = { ...intent.payload, scope_body: structuredClone(prepared.resource_ref.scope_body) };
          intent.preparation = undefined;
          intent.uncertain = false;
          // A refresh can remove current authority while document preparation waits.
          // Keep the exact continuation for an explicit recovery after fresh access.
          if (!session.page?.can_create) {
            intent.uncertain = true;
            setCommand({ session, value: { status: "UNKNOWN", code: "UNAVAILABLE" } });
            return;
          }
        }
        if (!("scope_body" in intent.payload)) throw new CurveExistingWorkError("TRANSPORT");
        // Persist the locator before a request can reach the server. Draft material
        // never enters browser storage; a failed write prevents submission.
        journal().retain(intent.idempotencyKey);
        session.recoveryKey = intent.idempotencyKey;
        const result = await items.create(workspaceSlug, { productId, roadmapId }, structuredClone(intent.payload), {
          expectedVersion: intent.expectedVersion,
          idempotencyKey: intent.idempotencyKey,
          signal: controller.signal,
        });
        if (!active() || controller.signal.aborted) return;
        session.intent = undefined;
        try {
          if (journal().settle(intent.idempotencyKey)) session.recoveryKey = undefined;
        } catch {
          // The verified result remains valid. A retained locator can be read
          // again after navigation/reload; it cannot trigger another write.
        }
        setCommand({ session, value: { status: "CREATED", result } });
        refresh();
      } catch (error) {
        if (!active() || controller.signal.aborted) return;
        if (error instanceof ItemRecoveryUnavailable) {
          session.intent = undefined;
          session.recoveryReady = false;
          inspectRecovery();
          setCommand({ session, value: { status: "UNKNOWN", code: "UNAVAILABLE" } });
          return;
        }
        const code = codeOf(error);
        // Rejection of a later replay cannot prove the first attempt did not commit.
        intent.uncertain ||= code === "MUTATION_OUTCOME_UNKNOWN";
        if (!intent.uncertain) {
          session.intent = undefined;
          try {
            journal().settle(intent.idempotencyKey);
            session.recoveryKey = undefined;
          } catch {
            session.recoveryReady = false;
            setCommand({ session, value: { status: "UNKNOWN", code: "UNAVAILABLE" } });
            return;
          }
        }
        setCommand({ session, value: { status: intent.uncertain ? "UNKNOWN" : "FAILED", code } });
        if (code === "UNAVAILABLE" || code === "CONFLICT") refresh();
      } finally {
        if (session.writeController === controller) session.writeController = undefined;
      }
    },
    [active, session, actorId, key, workspaceSlug, productId, roadmapId, refresh, journal, inspectRecovery]
  );

  const create = useCallback(
    async (payload: CurveItemCreate) => {
      if (
        !active() ||
        !session.recoveryReady ||
        session.recoveryKey ||
        session.intent ||
        session.writeController ||
        !session.page?.can_create ||
        !actorId
      )
        return;
      const intent: Intent = {
        payload: structuredClone(payload),
        expectedVersion: session.page.roadmap_version,
        idempotencyKey: crypto.randomUUID(),
        uncertain: false,
      };
      session.intent = intent;
      await send(intent);
    },
    [active, session, actorId, send]
  );
  const createDraft = useCallback(
    async (payload: DraftPayload) => {
      if (
        !active() ||
        !session.recoveryReady ||
        session.recoveryKey ||
        session.intent ||
        session.writeController ||
        !session.page?.can_create ||
        !actorId
      )
        return;
      const detached = structuredClone(payload);
      const intent: Intent = {
        payload: detached,
        expectedVersion: session.page.roadmap_version,
        idempotencyKey: crypto.randomUUID(),
        uncertain: false,
        preparation: { body: detached.initiative.description.body, idempotencyKey: crypto.randomUUID() },
      };
      session.intent = intent;
      await send(intent);
    },
    [active, session, actorId, send]
  );
  const cancel = useCallback(async () => {
    if (!active() || session.writeController || !actorId) return;
    // An in-memory original identity takes precedence over an altered locator.
    const commandKey = session.cancellationKey ?? session.recoveryKey;
    if (!commandKey) return;
    const originalKey = session.intent?.uncertain ? session.intent.idempotencyKey : commandKey;
    session.cancellationKey = originalKey;
    const controller = new AbortController();
    session.writeController = controller;
    setCommand({ session, value: { status: "CANCELLING" } });
    try {
      const result = await items.cancelCreation(
        workspaceSlug,
        { productId, roadmapId },
        originalKey,
        controller.signal
      );
      if (!active() || controller.signal.aborted) return;
      if (result.state === "UNRESOLVED") {
        setCommand({ session, value: { status: "UNKNOWN", code: "UNAVAILABLE" } });
        return;
      }
      if (result.state === "COMPLETED") {
        try {
          if (journal().settle(originalKey)) session.recoveryKey = undefined;
        } catch {
          // A verified existing Item can be opened even if locator cleanup fails.
        }
        session.intent = undefined;
        setCommand({ session, value: { status: "RECOVERED", result } });
        return;
      }
      // Starting again requires both server confirmation and durable cleanup.
      if (!journal().settle(originalKey) && journal().read() !== null) throw new ItemRecoveryUnavailable();
      session.intent = undefined;
      session.recoveryKey = undefined;
      session.cancellationKey = undefined;
      session.recoveryReady = true;
      setCommand({ session, value: { status: "CANCELLED" } });
      refresh();
    } catch (error) {
      if (active() && !controller.signal.aborted)
        setCommand({ session, value: { status: "UNKNOWN", code: codeOf(error) } });
    } finally {
      if (session.writeController === controller) session.writeController = undefined;
    }
  }, [active, actorId, session, workspaceSlug, productId, roadmapId, journal, refresh]);
  const retry = useCallback(async () => {
    if (session.cancellationKey) {
      await cancel();
      return;
    }
    if (!active() || session.writeController || !actorId) return;
    if (session.intent?.uncertain) {
      if (session.page?.can_create) {
        await send(session.intent, true);
        return;
      }
      if (!session.recoveryKey) return;
    }
    inspectRecovery();
    if (!session.recoveryReady) return;
    const commandKey = session.intent?.uncertain ? session.intent.idempotencyKey : session.recoveryKey;
    if (!commandKey) {
      setCommand({ session, value: { status: "FAILED", code: "UNAVAILABLE" } });
      return;
    }
    const controller = new AbortController();
    session.writeController = controller;
    setCommand({ session, value: { status: "RECOVERING" } });
    try {
      const result = await items.reconcileCreation(
        workspaceSlug,
        { productId, roadmapId },
        commandKey,
        controller.signal
      );
      if (!active() || controller.signal.aborted) return;
      if (result.state === "UNRESOLVED") {
        setCommand({ session, value: { status: "UNKNOWN", code: "UNAVAILABLE" } });
        return;
      }
      try {
        if (journal().settle(commandKey)) session.recoveryKey = undefined;
      } catch {
        // Keep verified navigation available even when cleanup is unavailable.
      }
      session.intent = undefined;
      setCommand({ session, value: { status: "RECOVERED", result } });
    } catch (error) {
      if (active() && !controller.signal.aborted)
        setCommand({ session, value: { status: "UNKNOWN", code: codeOf(error) } });
    } finally {
      if (session.writeController === controller) session.writeController = undefined;
    }
  }, [active, actorId, session, send, inspectRecovery, workspaceSlug, productId, roadmapId, journal, cancel]);
  const nextPage = useCallback(() => {
    if (active() && session.page?.next_cursor) void load(session.page.next_cursor);
  }, [active, session, load]);

  return {
    page: read?.session === session ? read.value : idle,
    command: command?.session === session ? command.value : ({ status: "IDLE" } as CommandState),
    canRecover: !!actorId && (!session.intent || !!session.recoveryKey || !!session.page?.can_create),
    refresh,
    nextPage,
    create,
    createDraft,
    retry,
    cancel,
    canCancel: !!actorId && !!session.recoveryKey,
  };
}
