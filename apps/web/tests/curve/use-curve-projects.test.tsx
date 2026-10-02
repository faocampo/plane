/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ProjectOutlookModule, ProjectOutlookProject } from "@/components/curve/projects/project-outlook-data";
import { useCurveProjects } from "@/hooks/use-curve-projects";
import projectReads from "@/services/curve-project-read.service";

vi.mock("@/services/curve-project-read.service", () => ({
  default: {
    listProjects: vi.fn(),
    listMembers: vi.fn(),
    listModules: vi.fn(),
    listCycles: vi.fn(),
  },
}));
const service = vi.mocked(projectReads);
const project = (id = "project-1", overrides: Partial<ProjectOutlookProject> = {}): ProjectOutlookProject => ({
  id,
  name: `Example ${id}`,
  identifier: "EX",
  sort_order: 1,
  logo_props: { in_use: "icon" },
  member_role: 15,
  archived_at: null,
  workspace: "workspace-1",
  module_view: true,
  cycle_view: true,
  issue_views_view: true,
  page_view: true,
  inbox_view: false,
  ...overrides,
});
const moduleRow = (id = "module-1", projectId = "project-1"): ProjectOutlookModule => ({
  id,
  name: "Example module",
  project_id: projectId,
  workspace_id: "workspace-1",
  status: "planned",
  start_date: null,
  target_date: "2026-10-20",
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.clearAllMocks();
  service.listProjects.mockResolvedValue([project(), project("project-2")]);
  service.listMembers.mockResolvedValue([]);
  service.listModules.mockResolvedValue([moduleRow()]);
  service.listCycles.mockResolvedValue([]);
});

describe("native Projects read isolation", () => {
  it("loads no source for a missing actor, selects nothing automatically, and excludes archived projects", async () => {
    const { result, rerender } = renderHook(({ actor }) => useCurveProjects("example", actor), {
      initialProps: { actor: undefined as string | undefined },
    });
    expect(service.listProjects).not.toHaveBeenCalled();
    service.listProjects.mockResolvedValue([project(), project("old", { archived_at: "2026-09-01" })]);
    rerender({ actor: "human-1" });
    await waitFor(() => expect(result.current.projects.status).toBe("ready"));
    expect(result.current.projects.data.map(({ id }) => id)).toEqual(["project-1"]);
    expect(result.current.selectedProject).toBeUndefined();
    expect(service.listModules).not.toHaveBeenCalled();
  });

  it("loads only the selected project and repeated selection preserves its loaded sources", async () => {
    const { result } = renderHook(() => useCurveProjects("example", "human-1"));
    await waitFor(() => expect(result.current.projects.status).toBe("ready"));
    act(() => result.current.selectProject("project-1"));
    await waitFor(() => expect(result.current.modules.status).toBe("ready"));
    expect(service.listModules).toHaveBeenCalledWith("example", "project-1", expect.any(AbortSignal));
    expect(result.current.cycles).toMatchObject({ status: "ready", data: [] });
    act(() => result.current.selectProject("project-1"));
    expect(result.current.modules.data).toEqual([moduleRow()]);
    expect(service.listModules).toHaveBeenCalledTimes(1);
  });

  it.each([
    [{ module_view: false, cycle_view: false }, "disabled"],
    [{ member_role: null }, "not-member"],
    [{ member_role: 5, guest_view_all_features: false }, "restricted"],
  ] as const)("does not fetch ineligible native features: %o", async (overrides, status) => {
    service.listProjects.mockResolvedValue([project("project-1", overrides)]);
    const { result } = renderHook(() => useCurveProjects("example", "human-1"));
    await waitFor(() => expect(result.current.projects.status).toBe("ready"));
    act(() => result.current.selectProject("project-1"));
    await waitFor(() => expect(result.current.modules.status).toBe(status));
    expect(result.current.cycles.status).toBe(status);
    expect(service.listModules).not.toHaveBeenCalled();
    expect(service.listCycles).not.toHaveBeenCalled();
  });

  it("allows explicitly enabled guest features through unchanged native permission checks", async () => {
    service.listProjects.mockResolvedValue([project("project-1", { member_role: 5, guest_view_all_features: true })]);
    const { result } = renderHook(() => useCurveProjects("example", "human-1"));
    await waitFor(() => expect(result.current.projects.status).toBe("ready"));
    act(() => result.current.selectProject("project-1"));
    await waitFor(() => expect(result.current.modules.status).toBe("ready"));
  });

  it("aborts prior project sources and ignores delayed results on newer selection", async () => {
    const old = deferred<ProjectOutlookModule[]>();
    service.listModules.mockReturnValueOnce(old.promise).mockResolvedValueOnce([moduleRow("new", "project-2")]);
    const { result } = renderHook(() => useCurveProjects("example", "human-1"));
    await waitFor(() => expect(result.current.projects.status).toBe("ready"));
    act(() => result.current.selectProject("project-1"));
    const signal = service.listModules.mock.calls[0][2];
    act(() => result.current.selectProject("project-2"));
    expect(signal.aborted).toBe(true);
    await waitFor(() => expect(result.current.modules.data[0]?.id).toBe("new"));
    await act(async () => old.resolve([moduleRow("stale")]));
    expect(result.current.modules.data[0]?.id).toBe("new");
  });

  it.each(["actor", "workspace"])("clears visible data and aborts old reads when %s changes", async (kind) => {
    const oldModules = deferred<ProjectOutlookModule[]>();
    service.listModules.mockReturnValueOnce(oldModules.promise);
    const { result, rerender } = renderHook(({ slug, actor }) => useCurveProjects(slug, actor), {
      initialProps: { slug: "example", actor: "human-1" },
    });
    await waitFor(() => expect(result.current.projects.status).toBe("ready"));
    act(() => result.current.selectProject("project-1"));
    const sourceSignal = service.listModules.mock.calls[0][2];
    const listSignal = service.listProjects.mock.calls[0][1];
    const next = deferred<ProjectOutlookProject[]>();
    service.listProjects.mockReturnValueOnce(next.promise);
    rerender(kind === "actor" ? { slug: "example", actor: "human-2" } : { slug: "other", actor: "human-1" });
    expect(result.current.projects.data).toEqual([]);
    expect(result.current.selectedProject).toBeUndefined();
    expect(result.current.modules.data).toEqual([]);
    expect(listSignal.aborted).toBe(true);
    expect(sourceSignal.aborted).toBe(true);
    await act(async () => oldModules.resolve([moduleRow("stale")]));
    expect(result.current.modules.data).toEqual([]);
    await act(async () => next.resolve([]));
    expect(result.current.projects.data).toEqual([]);
  });

  it("ignores old same-scope requests after A → B → A", async () => {
    const old = deferred<ProjectOutlookProject[]>();
    service.listProjects
      .mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([project("fresh")]);
    const { result, rerender } = renderHook(({ slug }) => useCurveProjects(slug, "human-1"), {
      initialProps: { slug: "example-a" },
    });
    rerender({ slug: "example-b" });
    rerender({ slug: "example-a" });
    await waitFor(() => expect(result.current.projects.data[0]?.id).toBe("fresh"));
    await act(async () => old.resolve([project("old")]));
    expect(result.current.projects.data[0]?.id).toBe("fresh");
  });

  it("refresh hides prior data and a denied project list discards selection and source data", async () => {
    const { result } = renderHook(() => useCurveProjects("example", "human-1"));
    await waitFor(() => expect(result.current.projects.status).toBe("ready"));
    act(() => result.current.selectProject("project-1"));
    await waitFor(() => expect(result.current.modules.status).toBe("ready"));
    const next = deferred<ProjectOutlookProject[]>();
    service.listProjects.mockReturnValueOnce(next.promise);
    act(() => result.current.refresh());
    expect(result.current.projects.data).toEqual([]);
    expect(result.current.modules.data).toEqual([]);
    await act(async () => next.reject({ response: { status: 403 } }));
    expect(result.current.projects.status).toBe("denied");
    expect(result.current.members.data).toEqual([]);
    expect(result.current.selectedProject).toBeUndefined();
  });

  it("refreshes selected sources when the authorized list is revalidated", async () => {
    const { result } = renderHook(() => useCurveProjects("example", "human-1"));
    await waitFor(() => expect(result.current.projects.status).toBe("ready"));
    act(() => result.current.selectProject("project-1"));
    await waitFor(() => expect(result.current.modules.status).toBe("ready"));
    act(() => result.current.refresh());
    await waitFor(() => expect(service.listModules).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.modules.status).toBe("ready"));
  });

  it("roster error does not prevent project visibility or invent an owner", async () => {
    service.listMembers.mockRejectedValue({ response: { status: 503 } });
    const { result } = renderHook(() => useCurveProjects("example", "human-1"));
    await waitFor(() => expect(result.current.projects.status).toBe("ready"));
    expect(result.current.members.status).toBe("error");
    expect(result.current.projects.data).toHaveLength(2);
  });

  it("treats source failures independently and rejects mismatched project/workspace records", async () => {
    service.listModules.mockResolvedValue([{ ...moduleRow(), workspace_id: "other-workspace" }]);
    service.listCycles.mockRejectedValue({ response: { status: 403 } });
    const { result } = renderHook(() => useCurveProjects("example", "human-1"));
    await waitFor(() => expect(result.current.projects.status).toBe("ready"));
    act(() => result.current.selectProject("project-1"));
    await waitFor(() => expect(result.current.modules.status).toBe("error"));
    expect(result.current.modules.data).toEqual([]);
    expect(result.current.cycles).toMatchObject({ status: "denied", data: [] });
    expect(result.current.projects.status).toBe("ready");
  });

  it("aborts all pending reads on unmount", async () => {
    const { result, unmount } = renderHook(() => useCurveProjects("example", "human-1"));
    await waitFor(() => expect(result.current.projects.status).toBe("ready"));
    act(() => result.current.selectProject("project-1"));
    unmount();
    expect(service.listProjects.mock.calls[0][1].aborted).toBe(true);
    expect(service.listModules.mock.calls[0][2].aborted).toBe(true);
  });
});
