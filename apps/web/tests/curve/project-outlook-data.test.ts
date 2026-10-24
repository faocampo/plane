/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { describe, expect, it } from "vitest";
import type {
  ProjectOutlookCycle,
  ProjectOutlookModule,
  ProjectOutlookProject,
  ProjectOutlookMember,
} from "@/components/curve/projects/project-outlook-data";
import {
  datedCycles,
  datedModules,
  isCycleDate,
  isLocalDate,
  projectLeadLabel,
} from "@/components/curve/projects/project-outlook-data";

describe("native project date and owner semantics", () => {
  it("does not substitute creator, default assignee or email for a project lead", () => {
    const project = {
      project_lead: null,
      created_by: "creator",
      default_assignee: "assignee",
    } as unknown as ProjectOutlookProject;
    expect(projectLeadLabel(project, { status: "ready", data: [] })).toBe("Not assigned");
    project.project_lead = "lead";
    expect(projectLeadLabel(project, { status: "ready", data: [] })).toBe("Name unavailable");
    const member = { member: { id: "lead", email: "person@example.invalid" } } as ProjectOutlookMember;
    expect(projectLeadLabel(project, { status: "ready", data: [member] })).toBe("Name unavailable");
    member.member.display_name = "Fictional lead";
    expect(projectLeadLabel(project, { status: "ready", data: [member] })).toBe("Fictional lead");
    expect(projectLeadLabel(project, { status: "denied", data: [member] })).toBe("Name unavailable");
  });
  it("accepts only real module local dates without converting them to browser time", () => {
    expect(isLocalDate("2028-02-29")).toBe(true);
    for (const value of [null, "", "2026-02-29", "2026-04-31", "2026-10-02T00:00:00Z", "2026-1-1"])
      expect(isLocalDate(value)).toBe(false);
  });
  it("includes paused native modules but excludes completed/cancelled modules without changing input", () => {
    const modules = [
      { id: "paused", status: "paused", target_date: "2026-10-20" },
      { id: "completed", status: "completed", target_date: "2026-10-01" },
      { id: "cancelled", status: "cancelled", target_date: "2026-10-01" },
      { id: "planned", status: "planned", target_date: "2026-10-05" },
      { id: "missing", status: "planned", target_date: null },
    ] as ProjectOutlookModule[];
    expect(datedModules(modules).map(({ id }) => id)).toEqual(["planned", "paused"]);
    expect(modules[0].id).toBe("paused");
  });
  it("compares cycle timezone-qualified instants and preserves their source text", () => {
    const cycles = [
      { id: "later", end_date: "2026-10-02T23:59:00-07:00" },
      { id: "earlier", end_date: "2026-10-03T00:30:00+00:00" },
      { id: "past", end_date: "2026-10-02T10:00:00Z" },
      { id: "missing", end_date: null },
    ] as ProjectOutlookCycle[];
    expect(datedCycles(cycles, "2026-10-02T20:00:00Z").map(({ id }) => id)).toEqual(["earlier", "later"]);
    expect(datedCycles(cycles, "2026-10-02T20:00:00Z")[1].end_date).toBe("2026-10-02T23:59:00-07:00");
    expect(isCycleDate("2026-10-02")).toBe(false);
    expect(isCycleDate("2026-02-30T10:00:00Z")).toBe(false);
    expect(isCycleDate("2026-10-02T10:00:00")).toBe(false);
    expect(datedCycles(cycles, "invalid")).toEqual([]);
  });
});
