/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { CurveExistingWorkResult, CurveProjectAssociation } from "@plane/types";
import {
  associationIssue,
  type AssociationDiscovery,
  type AssociationIssue,
  type AssociationPort,
  type AssociationProduct,
} from "@/components/curve/projects/project-association-model";
import type { ProjectOutlookProject, ProjectRead } from "@/components/curve/projects/project-outlook-data";

type Step = "choose" | "checking" | "review" | "sending" | "unknown" | "confirmed";
type Command = { projectId: string; productId: string; installationId: string; productVersion: number; key: string };
type Session = {
  scope: string;
  step: Step;
  products: AssociationProduct[];
  productsState: "loading" | "ready" | "unavailable";
  projectId: string;
  productId: string;
  discovery?: AssociationDiscovery;
  issue?: AssociationIssue;
  receipt?: CurveExistingWorkResult<CurveProjectAssociation>;
};
const initial = (scope: string): Session => ({
  scope,
  step: "choose",
  products: [],
  productsState: "loading",
  projectId: "",
  productId: "",
});

/** In-memory intent. No actor identity, role or cached read is ever sent as authority. */
export function useCurveProjectAssociation({
  workspaceSlug,
  workspaceId,
  actorId,
  projects,
  port,
  onAccessUnavailable,
}: {
  workspaceSlug: string;
  workspaceId?: string;
  actorId?: string;
  projects: ProjectRead<ProjectOutlookProject>;
  port: AssociationPort;
  onAccessUnavailable: () => void;
}) {
  const scope = JSON.stringify([workspaceSlug, workspaceId ?? null, actorId ?? null]);
  const [session, setSession] = useState<Session>(() => initial(scope));
  const [revision, setRevision] = useState(0);
  const currentScope = useRef(scope);
  currentScope.current = scope;
  const generation = useRef(0);
  const productGeneration = useRef(0);
  const request = useRef<AbortController | undefined>(undefined);
  const pending = useRef<Command | undefined>(undefined);
  const busy = useRef(false);
  const accessCallback = useRef(onAccessUnavailable);
  accessCallback.current = onAccessUnavailable;
  const current = session.scope === scope ? session : initial(scope);
  const validSession = !!actorId && !!workspaceId && !!workspaceSlug;
  const update = useCallback(
    (change: Partial<Session>) => {
      if (currentScope.current !== scope) return;
      setSession((value) => (value.scope === scope ? { ...value, ...change } : value));
    },
    [scope]
  );

  useEffect(() => {
    const controller = new AbortController();
    const epoch = ++productGeneration.current;
    generation.current += 1;
    request.current?.abort();
    pending.current = undefined;
    busy.current = false;
    setSession((value) =>
      value.scope === scope
        ? { ...initial(scope), projectId: value.projectId, productId: value.productId }
        : initial(scope)
    );
    if (!validSession || !workspaceId) return () => controller.abort();
    void port
      .listProducts(workspaceSlug, workspaceId, controller.signal)
      .then((products) => {
        if (controller.signal.aborted || productGeneration.current !== epoch || currentScope.current !== scope)
          return undefined;
        update({ products, productsState: "ready" });
        return undefined;
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || productGeneration.current !== epoch || currentScope.current !== scope) return;
        const issue = associationIssue(error);
        update({ products: [], productsState: "unavailable", issue });
        if (issue === "denied") accessCallback.current();
      });
    return () => {
      controller.abort();
      request.current?.abort();
      generation.current += 1;
      pending.current = undefined;
      busy.current = false;
    };
  }, [scope, workspaceSlug, workspaceId, validSession, port, update, revision]);

  const redact = useCallback(() => {
    request.current?.abort();
    generation.current += 1;
    productGeneration.current += 1;
    pending.current = undefined;
    busy.current = false;
    update({
      step: "choose",
      products: [],
      productsState: "unavailable",
      projectId: "",
      productId: "",
      discovery: undefined,
      receipt: undefined,
      issue: "denied",
    });
  }, [update]);

  useEffect(() => {
    if (projects.status === "denied") redact();
  }, [projects.status, redact]);

  const locked = current.step === "sending" || current.step === "unknown";
  const visibleProjects =
    projects.status === "ready" && current.issue !== "denied"
      ? projects.data.filter(
          (project) =>
            !project.archived_at &&
            (typeof project.workspace === "string" ? project.workspace : project.workspace.id) === workspaceId
        )
      : [];
  const project = visibleProjects.find(({ id }) => id === current.projectId);
  const product = current.products.find(({ id }) => id === current.productId);

  const choose = (field: "projectId" | "productId", value: string) => {
    if (locked || busy.current) return;
    request.current?.abort();
    generation.current += 1;
    pending.current = undefined;
    update({ [field]: value, step: "choose", discovery: undefined, receipt: undefined, issue: undefined });
  };

  const check = async () => {
    if (!validSession || !workspaceId || !project || !product || busy.current || locked) return;
    const controller = new AbortController();
    request.current?.abort();
    request.current = controller;
    const epoch = ++generation.current;
    busy.current = true;
    update({ step: "checking", issue: undefined, discovery: undefined, receipt: undefined });
    try {
      const discovery = await port.discover(
        workspaceSlug,
        { workspaceId, productId: product.id },
        project.id,
        controller.signal
      );
      if (controller.signal.aborted || generation.current !== epoch || currentScope.current !== scope) return;
      pending.current = undefined;
      update({ step: "review", discovery });
    } catch (error) {
      if (controller.signal.aborted || generation.current !== epoch || currentScope.current !== scope) return;
      const issue = associationIssue(error);
      if (issue === "denied") {
        redact();
        accessCallback.current();
      } else update({ step: "choose", issue });
    } finally {
      if (generation.current === epoch) busy.current = false;
    }
  };

  const send = async () => {
    if (!validSession || !workspaceId || !project || !product || busy.current) return;
    const recovering = current.step === "unknown";
    if (!recovering && (current.step !== "review" || current.discovery?.availability !== "AVAILABLE")) return;
    const command = recovering
      ? pending.current
      : current.discovery && {
          projectId: project.id,
          productId: product.id,
          installationId: current.discovery.provider_installation_id,
          productVersion: current.discovery.product_version,
          key: crypto.randomUUID(),
        };
    if (!command) return;
    pending.current = command;
    const controller = new AbortController();
    request.current = controller;
    const epoch = ++generation.current;
    busy.current = true;
    update({ step: "sending", issue: undefined });
    try {
      const receipt = await port.create(
        workspaceSlug,
        { workspaceId, productId: command.productId },
        {
          provider_installation_id: command.installationId,
          source_project_id: command.projectId,
        },
        { expectedVersion: command.productVersion, idempotencyKey: command.key, signal: controller.signal }
      );
      if (controller.signal.aborted || generation.current !== epoch || currentScope.current !== scope) return;
      pending.current = undefined;
      update({ step: "confirmed", receipt, issue: undefined });
    } catch (error) {
      if (generation.current !== epoch || currentScope.current !== scope) return;
      const issue = associationIssue(error);
      if (issue === "denied") {
        redact();
        accessCallback.current();
      } else if (issue === "unknown" || controller.signal.aborted) update({ step: "unknown", issue: "unknown" });
      else {
        pending.current = undefined;
        update({ step: "choose", issue, discovery: undefined });
      }
    } finally {
      if (generation.current === epoch) busy.current = false;
    }
  };

  const stopWaiting = () => {
    if (current.step !== "sending") return;
    request.current?.abort();
    generation.current += 1;
    busy.current = false;
    update({ step: "unknown", issue: "unknown" });
  };
  const back = () => {
    if (locked) return;
    request.current?.abort();
    generation.current += 1;
    busy.current = false;
    update({ step: "choose", discovery: undefined, issue: undefined, receipt: undefined });
  };
  const refreshProducts = () => {
    if (locked || busy.current) return;
    setRevision((value) => value + 1);
  };

  useEffect(() => {
    const invalidate = () => {
      if (busy.current || pending.current) return;
      setRevision((value) => value + 1);
    };
    window.addEventListener("focus", invalidate);
    window.addEventListener("online", invalidate);
    return () => {
      window.removeEventListener("focus", invalidate);
      window.removeEventListener("online", invalidate);
    };
  }, []);

  useEffect(() => {
    if (!locked) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [locked]);

  return {
    ...current,
    project,
    product,
    visibleProjects,
    locked,
    validSession,
    choose,
    check,
    send,
    stopWaiting,
    back,
    refreshProducts,
  };
}
