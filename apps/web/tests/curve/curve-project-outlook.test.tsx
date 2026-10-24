/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { observable, runInAction } from "mobx";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ProjectOutlookCycle,
  ProjectOutlookModule,
  ProjectOutlookProject,
  ProjectReadStatus,
} from "@/components/curve/projects/project-outlook-data";
import {
  ProjectOutlook,
  ProjectOutlookView,
  type ProjectOutlookViewProps,
} from "@/components/curve/projects/project-outlook";
import CurveProjectsPage from "@/app/(all)/[workspaceSlug]/(projects)/curve/projects/page";

const { projectsHook, shellHook, router } = vi.hoisted(() => ({
  projectsHook: vi.fn(),
  shellHook: vi.fn(),
  router: { replace: vi.fn() },
}));

const user = observable({ isAuthenticated: true, data: { id: "viewer-1" } });

vi.mock("@/hooks/use-curve-projects", () => ({ useCurveProjects: projectsHook }));
vi.mock("@/hooks/store/user", () => ({ useUser: () => user }));
vi.mock("@/hooks/use-curve-workspace-shell", () => ({ useCurveWorkspaceShell: shellHook }));
vi.mock("@/components/core/page-title", () => ({ PageHead: () => null }));
vi.mock("@/components/curve/curve-projects-header", () => ({
  CurveProjectsHeader: () => <div>Projects breadcrumb</div>,
}));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const project = (id: string, name: string): ProjectOutlookProject => ({
  id,
  name,
  identifier: id.toUpperCase(),
  sort_order: null,
  logo_props: { in_use: "icon" },
  member_role: 20,
  archived_at: null,
  workspace: "workspace-1",
  cycle_view: true,
  issue_views_view: true,
  module_view: true,
  page_view: true,
  inbox_view: true,
  project_lead: "lead-1",
});
const projects = [project("alpha", "Account foundation"), project("beta", "Billing experience")];
const moduleRecord = (
  id: string,
  date: string | null,
  status: ProjectOutlookModule["status"] = "planned"
): ProjectOutlookModule => ({
  id,
  name: `Module ${id}`,
  project_id: "alpha",
  workspace_id: "workspace-1",
  status,
  target_date: date,
  start_date: null,
});
const cycleRecord = (id: string, date: string | null): ProjectOutlookCycle => ({
  id,
  name: `Cycle ${id}`,
  project_id: "alpha",
  workspace_id: "workspace-1",
  start_date: null,
  end_date: date,
});
const makeProps = (overrides: Partial<ProjectOutlookViewProps> = {}): ProjectOutlookViewProps => ({
  workspaceSlug: "example-workspace",
  projects: { status: "ready", data: projects },
  members: {
    status: "ready",
    data: [
      {
        id: "membership-1",
        member: {
          id: "lead-1",
          display_name: "Taylor Lead",
          first_name: "Taylor",
          last_name: "Lead",
          avatar_url: "",
          is_bot: false,
        },
        role: 20,
        is_active: true,
      },
    ],
  },
  selectedProject: undefined,
  selectProject: vi.fn(),
  refresh: vi.fn(),
  modules: { status: "idle", data: [] },
  cycles: { status: "idle", data: [] },
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  runInAction(() => {
    user.isAuthenticated = true;
    user.data.id = "viewer-1";
  });
  projectsHook.mockReturnValue(makeProps());
  shellHook.mockReturnValue({
    shell: { workspace_slug: "example-workspace" },
    isEnabled: true,
    isLoading: false,
    isUnavailable: false,
    isPermissionLimited: false,
  });
});

describe("Curve Projects outlook", () => {
  it("requires an explicit single-project selection and keeps the native directory reachable", () => {
    const props = makeProps();
    const { rerender } = render(<ProjectOutlookView {...props} />);
    expect(screen.getByRole("heading", { level: 1, name: "Projects" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Choose a project" })).toBeInTheDocument();
    expect(props.selectProject).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Open native Projects directory" })).toHaveAttribute(
      "href",
      "/example-workspace/projects/"
    );
    expect(screen.queryByRole("heading", { name: "Module targets" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Account foundation/ }));
    expect(props.selectProject).toHaveBeenCalledExactlyOnceWith("alpha");
    rerender(<ProjectOutlookView {...props} selectedProject={projects[0]} />);
    expect(screen.getAllByRole("button", { pressed: true })).toHaveLength(1);
    expect(screen.getByRole("button", { name: /Billing experience/ })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("heading", { name: "Account foundation" })).toBeInTheDocument();
    expect(screen.getByText("Taylor Lead", { selector: "span.font-medium" })).toBeInTheDocument();
  });

  it("searches names and identifiers without auto-selecting a match", () => {
    const props = makeProps();
    render(<ProjectOutlookView {...props} />);
    fireEvent.change(screen.getByRole("searchbox", { name: "Search projects" }), { target: { value: "BILLING" } });
    expect(screen.getByRole("button", { name: /Billing experience/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Account foundation/ })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: " alpha " } });
    expect(screen.getByRole("button", { name: /Account foundation/ })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "no matching project" } });
    expect(screen.getByText("No projects match this search")).toBeInTheDocument();
    expect(props.selectProject).not.toHaveBeenCalled();
  });

  it("clears local search synchronously on account and workspace changes", () => {
    const { rerender } = render(<ProjectOutlook workspaceSlug="example-workspace" />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "private previous query" } });
    act(() =>
      runInAction(() => {
        user.data.id = "viewer-2";
      })
    );
    rerender(<ProjectOutlook workspaceSlug="example-workspace" />);
    expect(screen.getByRole("searchbox")).toHaveValue("");
    expect(projectsHook).toHaveBeenLastCalledWith("example-workspace", "viewer-2");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "another query" } });
    rerender(<ProjectOutlook workspaceSlug="other-workspace" />);
    expect(screen.getByRole("searchbox")).toHaveValue("");
    act(() =>
      runInAction(() => {
        user.isAuthenticated = false;
      })
    );
    rerender(<ProjectOutlook workspaceSlug="other-workspace" />);
    expect(projectsHook).toHaveBeenLastCalledWith("other-workspace", undefined);
  });

  it("shows only active projects and never details outside the current readable list", () => {
    render(
      <ProjectOutlookView
        {...makeProps({
          projects: { status: "ready", data: [{ ...projects[0], archived_at: "2026-10-01T00:00:00Z" }, projects[1]] },
          selectedProject: projects[0],
        })}
      />
    );
    expect(screen.queryByText("Account foundation")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Choose a project" })).toBeInTheDocument();
  });

  it("uses exact native dates and links without asserting deadlines or completion", () => {
    const props = makeProps({
      selectedProject: projects[0],
      modules: {
        status: "ready",
        data: [
          moduleRecord("later", "2026-11-10"),
          moduleRecord("earlier", "2026-10-08"),
          moduleRecord("done", "2026-10-01", "completed"),
          moduleRecord("cancelled", "2026-10-02", "cancelled"),
          moduleRecord("undated", null),
        ],
      },
      cycles: {
        status: "ready",
        data: [
          cycleRecord("upcoming", "2099-10-08T23:30:00-07:00"),
          cycleRecord("ended", "2000-10-01T00:00:00Z"),
          cycleRecord("undated", null),
        ],
      },
    });
    const { container } = render(<ProjectOutlookView {...props} />);
    const moduleSection = screen.getByRole("region", { name: "Module targets" });
    expect(
      within(moduleSection)
        .getAllByRole("listitem")
        .map((item) => item.textContent)
    ).toEqual([expect.stringContaining("Module earlier"), expect.stringContaining("Module later")]);
    expect(screen.getByText("2026-10-08")).toHaveAttribute("datetime", "2026-10-08");
    expect(screen.getByText("2099-10-08 23:30:00-07:00")).toHaveAttribute("datetime", "2099-10-08T23:30:00-07:00");
    expect(screen.queryByText("Module done")).not.toBeInTheDocument();
    expect(screen.queryByText("Module cancelled")).not.toBeInTheDocument();
    expect(screen.queryByText("Cycle ended")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Module earlier" })).toHaveAttribute(
      "href",
      "/example-workspace/projects/alpha/modules/earlier/"
    );
    expect(screen.getByRole("link", { name: "Cycle upcoming" })).toHaveAttribute(
      "href",
      "/example-workspace/projects/alpha/cycles/upcoming/"
    );
    expect(screen.getByRole("link", { name: "Open project work" })).toHaveAttribute(
      "href",
      "/example-workspace/projects/alpha/issues/"
    );
    expect(screen.getByRole("link", { name: "Open modules" })).toHaveAttribute(
      "href",
      "/example-workspace/projects/alpha/modules/"
    );
    expect(screen.getByRole("link", { name: "Open cycles" })).toHaveAttribute(
      "href",
      "/example-workspace/projects/alpha/cycles/"
    );
    expect(screen.getByText("Blockers not assessed.")).toBeInTheDocument();
    expect(screen.getByText(/A cycle ending does not mean delivery is complete/)).toBeInTheDocument();
    expect(screen.getByText("1 non-completed, non-cancelled module has no usable target date.")).toBeInTheDocument();
    expect(screen.getByText("1 cycle has no usable end date.")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\d+%|project deadline|milestone|health/i);
    expect(
      screen.queryByRole("button", { name: /approve|new|create|initiative|PRD|adopt|complete/i })
    ).not.toBeInTheDocument();
  });

  it("limits module targets to the earliest five without changing the records", () => {
    const records = [8, 7, 6, 5, 4, 3, 2, 1].map((day) => moduleRecord(`target-${day}`, `2026-10-0${day}`));
    render(
      <ProjectOutlookView
        {...makeProps({ selectedProject: projects[0], modules: { status: "ready", data: records } })}
      />
    );
    const section = screen.getByRole("region", { name: "Module targets" });
    expect(within(section).getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByText("Showing the earliest 5 of 8 recorded targets.")).toBeInTheDocument();
    expect(screen.queryByText("Module target-6")).not.toBeInTheDocument();
    expect(records[0].id).toBe("target-8");
  });

  it.each([
    ["idle", "Modules: not loaded."],
    ["loading", "Modules: loading."],
    ["error", "Modules: read failed."],
    ["denied", "Modules: access unavailable."],
    ["disabled", "Modules: feature disabled."],
    ["not-member", "Modules: membership required."],
    ["restricted", "Modules: restricted."],
  ] as [ProjectReadStatus, string][])("distinguishes %s coverage from an empty source", (status, text) => {
    render(
      <ProjectOutlookView
        {...makeProps({
          selectedProject: projects[0],
          modules: { status, data: [moduleRecord("stale", "2026-10-08")] },
          cycles: { status: "ready", data: [] },
        })}
      />
    );
    expect(screen.getByText(text)).toBeInTheDocument();
    expect(screen.queryByText("Module stale")).not.toBeInTheDocument();
    expect(screen.queryByText("No modules recorded.")).not.toBeInTheDocument();
    expect(screen.getByText("No cycles recorded.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Source coverage" })).toHaveTextContent("Empty source");
  });

  it("distinguishes empty source, absent target dates, and unavailable member names", () => {
    const props = makeProps({
      selectedProject: projects[0],
      members: { status: "error", data: makeProps().members.data },
      modules: { status: "ready", data: [moduleRecord("undated", null)] },
      cycles: { status: "ready", data: [] },
    });
    render(<ProjectOutlookView {...props} />);
    expect(screen.getByText("No target dates recorded for non-completed, non-cancelled modules.")).toBeInTheDocument();
    expect(screen.getByText("Name unavailable", { selector: "span.font-medium" })).toBeInTheDocument();
    expect(screen.queryByText(/Taylor Lead/)).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Source coverage" })).toHaveTextContent("Read failed");
    expect(screen.getByRole("region", { name: "Source coverage" })).toHaveTextContent("Empty source");
  });

  it.each(["denied", "error"] as const)("hides stale list and detail data when project access is %s", (status) => {
    const props = makeProps({
      selectedProject: projects[0],
      projects: { status, data: projects },
      modules: { status: "ready", data: [moduleRecord("stale", "2026-10-08")] },
    });
    render(<ProjectOutlookView {...props} />);
    expect(screen.getByRole("heading", { name: "Projects unavailable" })).toBeInTheDocument();
    expect(screen.queryByText("Account foundation")).not.toBeInTheDocument();
    expect(screen.queryByText("Module stale")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh sources" }));
    expect(props.refresh).toHaveBeenCalledOnce();
  });

  it("shows a genuine empty directory and loading state without invented projects", () => {
    const { rerender } = render(<ProjectOutlookView {...makeProps({ projects: { status: "ready", data: [] } })} />);
    expect(screen.getByText("No active projects available")).toBeInTheDocument();
    rerender(<ProjectOutlookView {...makeProps({ projects: { status: "loading", data: projects } })} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading projects");
    expect(screen.queryByText("Account foundation")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh sources" })).toBeDisabled();
  });
});

describe("Curve Projects page shell gate", () => {
  const pageProps = { params: { workspaceSlug: "example-workspace" } } as React.ComponentProps<
    typeof CurveProjectsPage
  >;

  it("mounts reads only for an enabled, available shell", () => {
    render(<CurveProjectsPage {...pageProps} />);
    expect(projectsHook).toHaveBeenCalledWith("example-workspace", "viewer-1");
    expect(screen.getByRole("heading", { name: "Projects", level: 1 })).toBeInTheDocument();
  });

  it.each([401, 403])("does not mount project reads on %s, even with a cached enabled shell", (errorStatus) => {
    shellHook.mockReturnValue({
      shell: { workspace_slug: "example-workspace" },
      isEnabled: true,
      isLoading: false,
      isPermissionLimited: true,
      errorStatus,
    });
    render(<CurveProjectsPage {...pageProps} />);
    expect(projectsHook).not.toHaveBeenCalled();
    expect(screen.getByText("Workspace access could not be verified.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Return to workspace" })).toHaveAttribute("href", "/example-workspace");
  });

  it.each([
    { isLoading: true, isEnabled: true, shell: {} },
    { isLoading: false, isEnabled: false, shell: {} },
    { isLoading: false, isEnabled: true, shell: undefined },
  ])("does not mount reads while the shell is unverified: %j", (shell) => {
    shellHook.mockReturnValue(shell);
    render(<CurveProjectsPage {...pageProps} />);
    expect(projectsHook).not.toHaveBeenCalled();
  });

  it("returns to the workspace when the Curve shell is unavailable", () => {
    shellHook.mockReturnValue({ isLoading: false, isUnavailable: true });
    render(<CurveProjectsPage {...pageProps} />);
    expect(projectsHook).not.toHaveBeenCalled();
    expect(router.replace).toHaveBeenCalledWith("/example-workspace");
  });
});
