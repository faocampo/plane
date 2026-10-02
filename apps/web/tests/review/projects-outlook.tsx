/** Synthetic-only clickable review. No imported organizations, workspaces, or live requests. */
import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router";
import { ProjectOutlookView } from "@/components/curve/projects/project-outlook";
import type {
  ProjectOutlookCycle,
  ProjectOutlookMember,
  ProjectOutlookModule,
  ProjectOutlookProject,
  ProjectRead,
} from "@/components/curve/projects/project-outlook-data";
// oxlint-disable import/no-unassigned-import -- the isolated harness explicitly loads local CSS and fonts.
import "@fontsource-variable/inter";
import "@fontsource/ibm-plex-mono";
import "@/styles/globals.css";
// oxlint-enable import/no-unassigned-import

// oxlint-disable no-map-spread -- detached fictional fixtures must not mutate their source literals.
const projects: ProjectOutlookProject[] = [
  {
    id: "project-atlas",
    name: "Atlas workspace",
    identifier: "ATL",
    project_lead: "person-river",
    member_role: 15,
    module_view: true,
    cycle_view: true,
  },
  {
    id: "project-orbit",
    name: "Orbit documentation",
    identifier: "ORB",
    project_lead: null,
    member_role: 15,
    module_view: false,
    cycle_view: true,
  },
  {
    id: "project-harbor",
    name: "Harbor prototype",
    identifier: "HBR",
    project_lead: "person-missing",
    member_role: null,
    module_view: true,
    cycle_view: true,
  },
].map((project) => ({
  archived_at: null,
  workspace: "workspace-example",
  sort_order: 1,
  logo_props: { in_use: "icon" as const },
  page_view: true,
  issue_views_view: true,
  inbox_view: false,
  ...project,
}));
const modules: ProjectOutlookModule[] = [
  { id: "module-search", name: "Search experience", target_date: "2026-10-19", status: "in-progress" },
  { id: "module-access", name: "Accessible navigation", target_date: "2026-10-26", status: "planned" },
  { id: "module-unclear", name: "Unscheduled improvements", target_date: null, status: "backlog" },
].map((module) => ({
  project_id: "project-atlas",
  workspace_id: "workspace-example",
  start_date: null,
  ...module,
})) as ProjectOutlookModule[];
// oxlint-enable no-map-spread
const cycles: ProjectOutlookCycle[] = [
  {
    id: "cycle-autumn",
    name: "Autumn cycle",
    project_id: "project-atlas",
    workspace_id: "workspace-example",
    start_date: "2026-10-01T00:00:01+01:00",
    end_date: "2026-10-31T23:59:00+01:00",
  },
];
const members = [
  {
    id: "membership-river",
    role: 15,
    member: {
      id: "person-river",
      display_name: "River Example",
      first_name: "River",
      last_name: "Example",
      avatar_url: "",
      is_bot: false,
    },
  },
] as ProjectOutlookMember[];
const ready = <T,>(data: T[]): ProjectRead<T> => ({ status: "ready", data, observedAt: "2026-10-02T18:00:00Z" });

function Review() {
  const [selected, setSelected] = useState<string>();
  const [scenario, setScenario] = useState("normal");
  const [dark, setDark] = useState(false);
  const location = useLocation();
  const selectedProject = projects.find(({ id }) => id === selected);
  const restricted = selectedProject?.member_role === null;
  const modulesRead: ProjectRead<ProjectOutlookModule> = restricted
    ? { status: "not-member", data: [] }
    : selectedProject?.module_view === false
      ? { status: "disabled", data: [] }
      : scenario === "partial"
        ? { status: "error", data: [] }
        : ready(selected === "project-atlas" ? modules : []);
  const cyclesRead: ProjectRead<ProjectOutlookCycle> = restricted
    ? { status: "not-member", data: [] }
    : ready(selected === "project-atlas" ? cycles : []);
  return (
    <>
      <aside
        className="border-b border-subtle bg-layer-1 px-5 py-3 text-12 text-primary"
        aria-label="Synthetic review controls"
      >
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4">
          <strong>Synthetic review only</strong>
          <span>All names and dates are fictional. Native links stay in this preview.</span>
          <label>
            State{" "}
            <select
              value={scenario}
              onChange={(event) => setScenario(event.target.value)}
              className="ml-2 rounded border border-subtle bg-surface-1 p-1"
            >
              <option value="normal">Normal</option>
              <option value="partial">Partial source failure</option>
              <option value="denied">Access unavailable</option>
              <option value="empty">Empty directory</option>
              <option value="loading">Loading</option>
            </select>
          </label>
          <button
            type="button"
            className="rounded border border-subtle px-2 py-1"
            onClick={() => {
              setDark(!dark);
              document.documentElement.dataset.theme = dark ? "light" : "dark";
              document.documentElement.classList.toggle("dark", !dark);
            }}
          >
            {dark ? "Light theme" : "Dark theme"}
          </button>
        </div>
        {location.pathname !== "/" && (
          <p role="status" className="mx-auto mt-2 max-w-6xl">
            Native destination: {location.pathname}
          </p>
        )}
      </aside>
      <ProjectOutlookView
        workspaceSlug="example-workspace"
        projects={
          scenario === "denied"
            ? { status: "denied", data: [] }
            : scenario === "loading"
              ? { status: "loading", data: [] }
              : ready(scenario === "empty" ? [] : projects)
        }
        members={ready(members)}
        selectedProject={selectedProject}
        selectProject={setSelected}
        refresh={() => setScenario("normal")}
        modules={modulesRead}
        cycles={cyclesRead}
      />
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <MemoryRouter>
    <Review />
  </MemoryRouter>
);
