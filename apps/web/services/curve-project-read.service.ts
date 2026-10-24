/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type {
  ProjectOutlookCycle,
  ProjectOutlookMember,
  ProjectOutlookModule,
  ProjectOutlookProject,
} from "@/components/curve/projects/project-outlook-data";
import { APIService } from "@/services/api.service";

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const identifier = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0;
const nullableText = (value: unknown) => value === null || typeof value === "string";
const optionalText = (value: unknown) => value === undefined || nullableText(value);
const moduleStatuses = new Set(["backlog", "planned", "in-progress", "paused", "completed", "cancelled"]);

// These guards validate only the fields consumed by this source-owned projection.
// They neither grant permission nor redefine the native service's full wire schema.
const isProject = (value: unknown): value is ProjectOutlookProject =>
  record(value) &&
  identifier(value.id) &&
  identifier(value.name) &&
  identifier(value.identifier) &&
  identifier(value.workspace) &&
  nullableText(value.archived_at) &&
  (value.project_lead === null || identifier(value.project_lead)) &&
  (value.member_role === null || value.member_role === 5 || value.member_role === 15 || value.member_role === 20) &&
  typeof value.module_view === "boolean" &&
  typeof value.cycle_view === "boolean" &&
  (value.guest_view_all_features === undefined || typeof value.guest_view_all_features === "boolean");
const isMember = (value: unknown): value is ProjectOutlookMember =>
  record(value) &&
  record(value.member) &&
  identifier(value.member.id) &&
  optionalText(value.member.display_name) &&
  optionalText(value.member.first_name) &&
  optionalText(value.member.last_name);
const isNativeEntity = (value: unknown): value is Record<string, unknown> =>
  record(value) &&
  identifier(value.id) &&
  identifier(value.name) &&
  identifier(value.project_id) &&
  identifier(value.workspace_id) &&
  nullableText(value.start_date);
const isModule = (value: unknown): value is ProjectOutlookModule =>
  isNativeEntity(value) &&
  nullableText(value.target_date) &&
  (value.status === undefined || (typeof value.status === "string" && moduleStatuses.has(value.status)));
const isCycle = (value: unknown): value is ProjectOutlookCycle => isNativeEntity(value) && nullableText(value.end_date);

/** Native list endpoints only. No Curve entity writes, detail expansions or stats. */
export class CurveProjectReadService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private async list<T>(path: string, signal: AbortSignal, accepts: (value: unknown) => value is T): Promise<T[]> {
    const response = await this.get(path, {}, { signal });
    if (!Array.isArray(response.data) || !response.data.every(accepts))
      throw new Error("Native list response is unavailable");
    return response.data as T[];
  }

  listProjects(workspaceSlug: string, signal: AbortSignal) {
    return this.list(`/api/workspaces/${encodeURIComponent(workspaceSlug)}/projects/`, signal, isProject);
  }

  listMembers(workspaceSlug: string, signal: AbortSignal) {
    return this.list(`/api/workspaces/${encodeURIComponent(workspaceSlug)}/members/`, signal, isMember);
  }

  listModules(workspaceSlug: string, projectId: string, signal: AbortSignal) {
    return this.list(
      `/api/workspaces/${encodeURIComponent(workspaceSlug)}/projects/${encodeURIComponent(projectId)}/modules/`,
      signal,
      isModule
    );
  }

  listCycles(workspaceSlug: string, projectId: string, signal: AbortSignal) {
    return this.list(
      `/api/workspaces/${encodeURIComponent(workspaceSlug)}/projects/${encodeURIComponent(projectId)}/cycles/`,
      signal,
      isCycle
    );
  }
}

export default new CurveProjectReadService();
