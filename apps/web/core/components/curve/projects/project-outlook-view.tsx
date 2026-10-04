/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  CalendarDays,
  Check,
  CircleDashed,
  CircleOff,
  FolderKanban,
  Info,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  Search,
  TriangleAlert,
} from "lucide-react";

import { Button } from "@plane/propel/button";
import { cn } from "@plane/utils";
import type { useCurveProjects } from "@/hooks/use-curve-projects";
import type { ProjectRead, ProjectReadStatus } from "./project-outlook-data";
import {
  datedCycles,
  datedModules,
  isCycleDate,
  openModules,
  projectLeadLabel,
  projectPath,
} from "./project-outlook-data";

export type ProjectOutlookViewProps = ReturnType<typeof useCurveProjects> & {
  workspaceSlug: string;
  associationPanel?: ReactNode;
};

const linkClassName =
  "inline-flex items-center gap-1.5 rounded-sm text-12 font-medium text-link-primary underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-primary";

const sourceStates: Record<
  Exclude<ProjectReadStatus, "ready">,
  { label: string; explanation: string; icon: typeof Info }
> = {
  idle: { label: "Not loaded", explanation: "Select a project to read this source.", icon: CircleDashed },
  loading: { label: "Loading", explanation: "Reading the current source.", icon: LoaderCircle },
  error: {
    label: "Read failed",
    explanation: "This source could not be read. Refresh to try again.",
    icon: TriangleAlert,
  },
  denied: {
    label: "Access unavailable",
    explanation: "Access to this source could not be verified.",
    icon: LockKeyhole,
  },
  disabled: { label: "Feature disabled", explanation: "This feature is disabled for this project.", icon: CircleOff },
  "not-member": {
    label: "Membership required",
    explanation: "Project membership is required to read this source.",
    icon: LockKeyhole,
  },
  restricted: {
    label: "Restricted",
    explanation: "Your project role does not allow this source to be read.",
    icon: LockKeyhole,
  },
};

function SourceCoverage({ name, source }: { name: string; source: ProjectRead<unknown> }) {
  const state =
    source.status === "ready"
      ? {
          label: source.data.length ? `${source.data.length} records read` : "Empty source",
          explanation: source.data.length ? "Native records are available." : "The source returned no records.",
          icon: Check,
        }
      : sourceStates[source.status];
  const Icon = state.icon;

  return (
    <div className="min-w-0 rounded-lg border border-subtle bg-surface-1 p-3">
      <dt className="text-11 font-medium text-secondary">{name}</dt>
      <dd className="mt-2">
        <span className="flex items-center gap-2 text-12 font-medium text-primary">
          <Icon className={cn("size-3.5 shrink-0", source.status === "loading" && "animate-spin")} aria-hidden="true" />
          {state.label}
        </span>
        <p className="mt-1 text-11 leading-5 text-secondary">{state.explanation}</p>
        {source.status === "ready" && source.observedAt && (
          <p className="mt-2 text-10 leading-4 break-words text-tertiary">
            Read at <time dateTime={source.observedAt}>{source.observedAt.replace("T", " ").replace("Z", " UTC")}</time>
          </p>
        )}
      </dd>
    </div>
  );
}

function SourceUnavailable({ source, name }: { source: ProjectRead<unknown>; name: string }) {
  if (source.status === "ready") return null;
  const state = sourceStates[source.status];
  const Icon = state.icon;
  return (
    <div className="flex items-start gap-2 py-4 text-12 leading-5 text-secondary" role="status">
      <Icon
        className={cn("mt-0.5 size-4 shrink-0", source.status === "loading" && "animate-spin")}
        aria-hidden="true"
      />
      <p>
        <span className="font-medium text-primary">
          {name}: {state.label.toLowerCase()}.
        </span>{" "}
        {state.explanation}
      </p>
    </div>
  );
}

function ProjectDetail({ workspaceSlug, selectedProject: project, members, modules, cycles }: ProjectOutlookViewProps) {
  if (!project) return null;
  const projectHref = projectPath(workspaceSlug, project.id);
  const targets = modules.status === "ready" ? datedModules(modules.data) : [];
  const undatedModuleCount = modules.status === "ready" ? openModules(modules.data).length - targets.length : 0;
  const cycleEnds = cycles.status === "ready" ? datedCycles(cycles.data, new Date().toISOString()) : [];
  const missingCycleEndCount =
    cycles.status === "ready" ? cycles.data.filter(({ end_date }) => !isCycleDate(end_date)).length : 0;

  return (
    <section aria-labelledby="project-outlook-detail-heading" className="min-w-0 space-y-5">
      <div className="rounded-xl border border-subtle bg-layer-1 p-5 shadow-raised-100 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="font-mono text-11 text-tertiary">{project.identifier}</p>
            <h2 id="project-outlook-detail-heading" className="mt-1 text-20 font-semibold break-words text-primary">
              {project.name}
            </h2>
            <p className="mt-2 text-12 text-secondary">
              Project lead <span className="ml-1 font-medium text-primary">{projectLeadLabel(project, members)}</span>
            </p>
          </div>
          <Link href={`${projectHref}issues/`} className={linkClassName}>
            Open project work <ArrowUpRight className="size-3.5" aria-hidden="true" />
          </Link>
        </div>
        <div
          className="mt-5 flex items-start gap-2 rounded-lg border border-subtle bg-surface-1 px-3 py-3 text-12 leading-5"
          role="note"
        >
          <Info className="mt-0.5 size-4 shrink-0 text-secondary" aria-hidden="true" />
          <p className="text-secondary">
            <span className="font-medium text-primary">Blockers not assessed.</span> This outlook reads project, module,
            and cycle records. It does not assess work-item dependencies.
          </p>
        </div>
      </div>

      <section aria-labelledby="project-module-targets" className="rounded-xl border border-subtle bg-surface-1 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 id="project-module-targets" className="flex items-center gap-2 text-16 font-semibold text-primary">
            <CalendarDays className="size-4 text-secondary" aria-hidden="true" />
            Module targets
          </h3>
          <Link href={`${projectHref}modules/`} className={linkClassName}>
            Open modules <ArrowUpRight className="size-3.5" aria-hidden="true" />
          </Link>
        </div>
        <p className="mt-2 text-12 leading-5 text-secondary">
          Earliest recorded target dates, excluding completed and cancelled modules.
        </p>
        <SourceUnavailable source={modules} name="Modules" />
        {modules.status === "ready" && (
          <>
            {targets.length > 0 ? (
              <ul className="mt-4 divide-y divide-subtle">
                {targets.slice(0, 5).map((module) => (
                  <li key={module.id} className="flex flex-wrap items-start justify-between gap-2 py-3">
                    <div className="min-w-0 flex-1 basis-40">
                      <Link
                        href={`${projectHref}modules/${encodeURIComponent(module.id)}/`}
                        className={cn(linkClassName, "break-words")}
                      >
                        {module.name}
                      </Link>
                      <p className="mt-1 text-11 text-tertiary">Native status: {module.status || "Not recorded"}</p>
                    </div>
                    <div className="text-11 text-secondary">
                      Module target{" "}
                      <time className="font-mono ml-1 text-12 text-primary" dateTime={module.target_date!}>
                        {module.target_date}
                      </time>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-4 text-12 text-secondary">
                {modules.data.length === 0
                  ? "No modules recorded."
                  : "No target dates recorded for non-completed, non-cancelled modules."}
              </p>
            )}
            {undatedModuleCount > 0 && (
              <p className="mt-3 text-11 leading-5 text-secondary">
                {undatedModuleCount} non-completed, non-cancelled{" "}
                {undatedModuleCount === 1 ? "module has" : "modules have"} no usable target date.
              </p>
            )}
            {targets.length > 5 && (
              <p className="mt-3 text-11 text-tertiary">Showing the earliest 5 of {targets.length} recorded targets.</p>
            )}
          </>
        )}
      </section>

      <section aria-labelledby="project-cycle-ends" className="rounded-xl border border-subtle bg-surface-1 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 id="project-cycle-ends" className="flex items-center gap-2 text-16 font-semibold text-primary">
            <CalendarDays className="size-4 text-secondary" aria-hidden="true" />
            Cycle ends
          </h3>
          <Link href={`${projectHref}cycles/`} className={linkClassName}>
            Open cycles <ArrowUpRight className="size-3.5" aria-hidden="true" />
          </Link>
        </div>
        <p className="mt-2 text-12 leading-5 text-secondary">
          Current and upcoming cycle end dates. A cycle ending does not mean delivery is complete.
        </p>
        <SourceUnavailable source={cycles} name="Cycles" />
        {cycles.status === "ready" && (
          <>
            {cycleEnds.length > 0 ? (
              <ul className="mt-4 divide-y divide-subtle">
                {cycleEnds.slice(0, 5).map((cycle) => (
                  <li key={cycle.id} className="space-y-1 py-3">
                    <Link
                      href={`${projectHref}cycles/${encodeURIComponent(cycle.id)}/`}
                      className={cn(linkClassName, "break-words")}
                    >
                      {cycle.name}
                    </Link>
                    <p className="text-11 leading-5 break-words text-secondary">
                      Cycle end{" "}
                      <time className="font-mono ml-1 text-12 text-primary" dateTime={cycle.end_date!}>
                        {cycle.end_date!.replace("T", " ").replace("Z", " UTC")}
                      </time>
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-4 text-12 text-secondary">
                {cycles.data.length === 0 ? "No cycles recorded." : "No current or upcoming cycle ends recorded."}
              </p>
            )}
            {missingCycleEndCount > 0 && (
              <p className="mt-3 text-11 text-secondary">
                {missingCycleEndCount} {missingCycleEndCount === 1 ? "cycle has" : "cycles have"} no usable end date.
              </p>
            )}
            {cycleEnds.length > 5 && (
              <p className="mt-3 text-11 text-tertiary">
                Showing the next 5 of {cycleEnds.length} recorded cycle ends.
              </p>
            )}
          </>
        )}
      </section>

      <section aria-labelledby="project-source-coverage" className="rounded-xl border border-subtle bg-layer-1 p-5">
        <h3 id="project-source-coverage" className="text-14 font-semibold text-primary">
          Source coverage
        </h3>
        <p className="mt-1 text-12 leading-5 text-secondary">
          Availability describes the records read, not project delivery status.
        </p>
        <dl className="mt-4 grid gap-3 sm:grid-cols-3">
          <SourceCoverage name="Member roster" source={members} />
          <SourceCoverage name="Modules" source={modules} />
          <SourceCoverage name="Cycles" source={cycles} />
        </dl>
      </section>
    </section>
  );
}

export function ProjectOutlookView(props: ProjectOutlookViewProps) {
  const { workspaceSlug, projects, members, selectedProject, selectProject, refresh } = props;
  const [search, setSearch] = useState("");
  const activeProjects = projects.status === "ready" ? projects.data.filter(({ archived_at }) => !archived_at) : [];
  const query = search.trim().toLocaleLowerCase();
  const filtered = activeProjects.filter((project) =>
    `${project.name} ${project.identifier}`.toLocaleLowerCase().includes(query)
  );
  // Even a synthetic or stale caller must not render details outside its current readable list.
  const selected = activeProjects.find(({ id }) => id === selectedProject?.id);
  const loading = projects.status === "loading" || projects.status === "idle";

  return (
    <main className="mx-auto w-full max-w-6xl px-5 py-7 sm:px-8 sm:py-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="text-32 leading-tight font-semibold tracking-tight text-primary">Projects</h1>
          <p className="mt-3 text-14 leading-6 text-secondary">
            Inspect existing work, connect it to Product context, and keep native project ownership clear.
          </p>
        </div>
        <Button
          variant="secondary"
          size="xl"
          onClick={refresh}
          disabled={loading}
          prependIcon={<RefreshCw aria-hidden="true" />}
          className="focus-visible:outline-accent-primary focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          Refresh sources
        </Button>
      </div>
      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-b border-subtle pb-5">
        <p className="text-12 text-secondary">
          {projects.status === "ready"
            ? `${activeProjects.length} active ${activeProjects.length === 1 ? "project" : "projects"} available`
            : "Project directory"}
        </p>
        <Link href={projectPath(workspaceSlug)} className={linkClassName}>
          Open native Projects directory <ArrowUpRight className="size-3.5" aria-hidden="true" />
        </Link>
      </div>

      {props.associationPanel}

      {loading ? (
        <div role="status" className="flex items-center gap-2 py-10 text-14 text-secondary">
          <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
          Loading projects…
        </div>
      ) : projects.status !== "ready" ? (
        <section
          className="mt-6 rounded-xl border border-subtle bg-layer-1 p-5"
          aria-labelledby="project-read-unavailable"
        >
          <h2 id="project-read-unavailable" className="text-16 font-semibold text-primary">
            Projects unavailable
          </h2>
          <SourceUnavailable name="Projects" source={projects} />
        </section>
      ) : (
        <div className="mt-6 grid items-start gap-5 lg:grid-cols-[minmax(15rem,0.7fr)_minmax(0,1.65fr)]">
          <section
            aria-labelledby="project-list-heading"
            className="min-w-0 overflow-hidden rounded-xl border border-subtle bg-surface-1"
          >
            <div className="border-b border-subtle p-4">
              <h2 id="project-list-heading" className="text-14 font-semibold text-primary">
                Existing projects
              </h2>
              <label htmlFor="project-outlook-search" className="mt-4 block text-11 font-medium text-secondary">
                Search projects
              </label>
              <div className="relative mt-2">
                <Search className="pointer-events-none absolute top-3 left-3 size-4 text-tertiary" aria-hidden="true" />
                <input
                  id="project-outlook-search"
                  type="search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Name or identifier"
                  className="focus:border-accent-primary h-10 w-full rounded-md border border-subtle bg-surface-1 pr-3 pl-9 text-12 text-primary placeholder:text-tertiary focus:outline-2 focus:outline-accent-subtle"
                />
              </div>
              <p className="mt-2 text-11 text-tertiary" role="status">
                {filtered.length} {filtered.length === 1 ? "project" : "projects"}
                {query ? " match" : " available"}
              </p>
            </div>
            {filtered.length > 0 ? (
              <ul className="max-h-[32rem] divide-y divide-subtle overflow-y-auto">
                {filtered.map((project) => (
                  <li key={project.id}>
                    <button
                      type="button"
                      onClick={() => selectProject(project.id)}
                      aria-pressed={selected?.id === project.id}
                      aria-controls="project-outlook-panel"
                      className={cn(
                        "focus-visible:outline-accent-primary w-full px-4 py-4 text-left transition-colors hover:bg-layer-1 focus-visible:relative focus-visible:outline-2 focus-visible:-outline-offset-2",
                        selected?.id === project.id && "bg-accent-subtle"
                      )}
                    >
                      <span className="flex items-start justify-between gap-3">
                        <span className="min-w-0 text-13 font-semibold break-words text-primary">{project.name}</span>
                        {selected?.id === project.id && (
                          <Check className="mt-0.5 size-4 shrink-0 text-accent-primary" aria-hidden="true" />
                        )}
                      </span>
                      <span className="font-mono mt-1 block text-10 text-tertiary">{project.identifier}</span>
                      <span className="mt-2 block text-11 text-secondary">
                        Lead: {projectLeadLabel(project, members)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="px-4 py-8 text-center">
                <FolderKanban className="mx-auto size-5 text-tertiary" aria-hidden="true" />
                <p className="mt-3 text-13 font-medium text-primary">
                  {query ? "No projects match this search" : "No active projects available"}
                </p>
                <p className="mt-2 text-12 leading-5 text-secondary">
                  {query ? "Try another name or identifier." : "The native directory is available above."}
                </p>
              </div>
            )}
          </section>
          <div id="project-outlook-panel" className="min-w-0">
            {selected ? (
              <ProjectDetail {...props} selectedProject={selected} />
            ) : (
              <section
                className="flex min-h-64 flex-col items-center justify-center rounded-xl border border-subtle bg-layer-1 p-6 text-center"
                aria-labelledby="project-selection-heading"
              >
                <FolderKanban className="size-7 text-tertiary" aria-hidden="true" />
                <h2 id="project-selection-heading" className="mt-4 text-18 font-semibold text-primary">
                  Choose a project
                </h2>
                <p className="mt-2 max-w-sm text-12 leading-5 text-secondary">
                  Select an existing project to read its module targets and cycle ends.
                </p>
              </section>
            )}
          </div>
        </div>
      )}
    </main>
  );
}
