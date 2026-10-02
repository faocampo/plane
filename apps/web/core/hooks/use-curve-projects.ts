/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  ProjectOutlookCycle,
  ProjectOutlookMember,
  ProjectOutlookModule,
  ProjectOutlookProject,
  ProjectRead,
} from "@/components/curve/projects/project-outlook-data";
import { projectFeatureStatus } from "@/components/curve/projects/project-outlook-data";
import projectReads from "@/services/curve-project-read.service";

const empty = <T>(status: ProjectRead<T>["status"] = "idle"): ProjectRead<T> => ({ status, data: [] });
const errorStatus = (error: unknown): "denied" | "error" => {
  const status =
    (error as { response?: { status?: number }; status?: number })?.response?.status ??
    (error as { status?: number })?.status;
  return status === 401 || status === 403 || status === 404 ? "denied" : "error";
};

type WorkspaceRead = {
  scope: string;
  projects: ProjectRead<ProjectOutlookProject>;
  members: ProjectRead<ProjectOutlookMember>;
};
type ScheduleRead = {
  scope: string;
  projectId: string;
  modules: ProjectRead<ProjectOutlookModule>;
  cycles: ProjectRead<ProjectOutlookCycle>;
};

export function useCurveProjects(workspaceSlug: string, actorId?: string) {
  const scope = JSON.stringify([actorId ?? null, workspaceSlug]);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [workspaceRead, setWorkspaceRead] = useState<WorkspaceRead>();
  const [selection, setSelection] = useState<{ scope: string; id: string }>();
  const [scheduleRead, setScheduleRead] = useState<ScheduleRead>();
  const currentScope = useRef(scope);
  currentScope.current = scope;

  const refresh = useCallback(() => {
    // Hide previously authorized values immediately, including while revalidation is pending.
    setWorkspaceRead(undefined);
    setScheduleRead(undefined);
    setRefreshVersion((value) => value + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    if (!actorId || !workspaceSlug) return () => controller.abort();
    setWorkspaceRead({ scope, projects: empty("loading"), members: empty("loading") });
    setScheduleRead(undefined);
    const valid = () => !controller.signal.aborted && currentScope.current === scope;
    void projectReads
      .listProjects(workspaceSlug, controller.signal)
      .then((projects) => {
        if (!valid()) return undefined;
        const active = projects.filter(({ archived_at }) => !archived_at);
        setWorkspaceRead((current) =>
          current?.scope === scope
            ? { ...current, projects: { status: "ready", data: active, observedAt: new Date().toISOString() } }
            : current
        );
        setSelection((current) =>
          current?.scope === scope && active.some(({ id }) => id === current.id) ? current : undefined
        );
        return undefined;
      })
      .catch((error: unknown) => {
        if (!valid()) return undefined;
        // A denied list invalidates every visible field, even a roster that already succeeded.
        setWorkspaceRead({ scope, projects: empty(errorStatus(error)), members: empty() });
        setSelection(undefined);
        setScheduleRead(undefined);
      });
    void projectReads
      .listMembers(workspaceSlug, controller.signal)
      .then((members) => {
        if (!valid()) return undefined;
        setWorkspaceRead((current) =>
          current?.scope === scope && current.projects.status !== "denied" && current.projects.status !== "error"
            ? { ...current, members: { status: "ready", data: members, observedAt: new Date().toISOString() } }
            : current
        );
        return undefined;
      })
      .catch((error: unknown) => {
        if (!valid()) return undefined;
        setWorkspaceRead((current) =>
          current?.scope === scope ? { ...current, members: empty(errorStatus(error)) } : current
        );
      });
    return () => controller.abort();
  }, [actorId, workspaceSlug, scope, refreshVersion]);

  useEffect(() => {
    window.addEventListener("focus", refresh);
    window.addEventListener("online", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      window.removeEventListener("online", refresh);
    };
  }, [refresh]);

  const projects =
    workspaceRead?.scope === scope
      ? workspaceRead.projects
      : empty<ProjectOutlookProject>(actorId ? "loading" : "idle");
  const members = workspaceRead?.scope === scope ? workspaceRead.members : empty<ProjectOutlookMember>();
  const selectedProject =
    projects.status === "ready" && selection?.scope === scope
      ? projects.data.find(({ id }) => id === selection.id)
      : undefined;

  useEffect(() => {
    const controller = new AbortController();
    if (!selectedProject || !actorId) {
      setScheduleRead(undefined);
      return () => controller.abort();
    }
    const projectId = selectedProject.id;
    const workspaceId =
      typeof selectedProject.workspace === "string" ? selectedProject.workspace : selectedProject.workspace.id;
    const moduleStatus = projectFeatureStatus(selectedProject, "module_view");
    const cycleStatus = projectFeatureStatus(selectedProject, "cycle_view");
    setScheduleRead({
      scope,
      projectId,
      modules: empty(moduleStatus === "idle" ? "loading" : moduleStatus),
      cycles: empty(cycleStatus === "idle" ? "loading" : cycleStatus),
    });
    const valid = () => !controller.signal.aborted && currentScope.current === scope;
    const receive = <T extends ProjectOutlookModule | ProjectOutlookCycle>(key: "modules" | "cycles", data: T[]) => {
      if (!valid()) return undefined;
      if (data.some((item) => item.project_id !== projectId || item.workspace_id !== workspaceId))
        throw new Error("Native source scope mismatch");
      setScheduleRead((current) =>
        current?.scope === scope && current.projectId === projectId
          ? { ...current, [key]: { status: "ready", data, observedAt: new Date().toISOString() } }
          : current
      );
    };
    const fail = (key: "modules" | "cycles", error: unknown) => {
      if (!valid()) return undefined;
      setScheduleRead((current) =>
        current?.scope === scope && current.projectId === projectId
          ? { ...current, [key]: empty(errorStatus(error)) }
          : current
      );
    };
    if (moduleStatus === "idle")
      void projectReads
        .listModules(workspaceSlug, projectId, controller.signal)
        .then((data) => receive("modules", data))
        .catch((error: unknown) => fail("modules", error));
    if (cycleStatus === "idle")
      void projectReads
        .listCycles(workspaceSlug, projectId, controller.signal)
        .then((data) => receive("cycles", data))
        .catch((error: unknown) => fail("cycles", error));
    return () => controller.abort();
  }, [actorId, workspaceSlug, scope, selectedProject]);

  const selectProject = useCallback(
    (id: string) => {
      if (selectedProject?.id === id) return;
      setScheduleRead(undefined);
      setSelection({ scope, id });
    },
    [scope, selectedProject?.id]
  );
  const currentSchedule =
    scheduleRead?.scope === scope && scheduleRead.projectId === selectedProject?.id ? scheduleRead : undefined;
  return {
    projects,
    members,
    selectedProject,
    selectProject,
    refresh,
    modules: currentSchedule?.modules ?? empty<ProjectOutlookModule>(selectedProject ? "loading" : "idle"),
    cycles: currentSchedule?.cycles ?? empty<ProjectOutlookCycle>(selectedProject ? "loading" : "idle"),
  };
}
