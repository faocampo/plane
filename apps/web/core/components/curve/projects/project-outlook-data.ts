/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ICycle, IModule, IWorkspaceMember, TPartialProject } from "@plane/types";

export type ProjectReadStatus =
  | "idle"
  | "loading"
  | "ready"
  | "error"
  | "denied"
  | "disabled"
  | "not-member"
  | "restricted";
export type ProjectRead<T> = { status: ProjectReadStatus; data: T[]; observedAt?: string };
export type ProjectOutlookProject = TPartialProject;
export type ProjectOutlookModule = Pick<
  IModule,
  "id" | "name" | "project_id" | "workspace_id" | "status" | "start_date" | "target_date"
>;
export type ProjectOutlookCycle = Pick<
  ICycle,
  "id" | "name" | "project_id" | "workspace_id" | "start_date" | "end_date"
>;
export type ProjectOutlookMember = IWorkspaceMember;

export function projectFeatureStatus(
  project: ProjectOutlookProject,
  feature: "module_view" | "cycle_view"
): ProjectReadStatus {
  if (!project.member_role) return "not-member";
  if (project.member_role === 5 && project.guest_view_all_features !== true) return "restricted";
  return project[feature] ? "idle" : "disabled";
}

export function projectLeadLabel(project: ProjectOutlookProject, members: ProjectRead<ProjectOutlookMember>): string {
  if (!project.project_lead) return "Not assigned";
  const leadId = typeof project.project_lead === "string" ? project.project_lead : project.project_lead.id;
  // Never use a previous account's global member-store identity or an email fallback.
  const lead = members.status === "ready" ? members.data.find(({ member }) => member.id === leadId)?.member : undefined;
  return lead?.display_name || [lead?.first_name, lead?.last_name].filter(Boolean).join(" ") || "Name unavailable";
}

export function isLocalDate(value: string | null | undefined): value is string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00.000Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

export function openModules(modules: ProjectOutlookModule[]): ProjectOutlookModule[] {
  return modules.filter(({ status }) => status !== "completed" && status !== "cancelled");
}

export function datedModules(modules: ProjectOutlookModule[]): ProjectOutlookModule[] {
  // Copy before sorting; native records are never changed by the outlook.
  return (
    openModules(modules)
      .filter(({ target_date }) => isLocalDate(target_date))
      // oxlint-disable-next-line unicorn/no-array-sort -- sorts a fresh filtered array for the supported target.
      .sort((a, b) => a.target_date!.localeCompare(b.target_date!) || a.id.localeCompare(b.id))
  );
}

export function isCycleDate(value: string | null | undefined): value is string {
  // Native cycle dates are project-timezone instants, unlike module LocalDate values.
  if (!value || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return false;
  return isLocalDate(value.slice(0, 10)) && Number.isFinite(Date.parse(value));
}

export function datedCycles(cycles: ProjectOutlookCycle[], now: string): ProjectOutlookCycle[] {
  const nowInstant = Date.parse(now);
  if (!Number.isFinite(nowInstant)) return [];
  // An elapsed cycle is a time period, not evidence of completed delivery.
  return (
    cycles
      .filter(({ end_date }) => isCycleDate(end_date) && Date.parse(end_date) >= nowInstant)
      // oxlint-disable-next-line unicorn/no-array-sort -- sorts a fresh filtered array for the supported target.
      .sort((a, b) => Date.parse(a.end_date!) - Date.parse(b.end_date!) || a.id.localeCompare(b.id))
  );
}

export const projectPath = (workspaceSlug: string, projectId?: string) =>
  `/${encodeURIComponent(workspaceSlug)}/projects/${projectId ? `${encodeURIComponent(projectId)}/` : ""}`;
