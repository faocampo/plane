/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import type { AxiosResponse } from "axios";
import { describe, expect, it, vi } from "vitest";
import { CurveProjectReadService } from "@/services/curve-project-read.service";

describe("native project source read service", () => {
  it("uses only native list GETs and forwards cancellation for every source", async () => {
    const service = new CurveProjectReadService();
    const get = vi.spyOn(service, "get").mockResolvedValue({ data: [] } as AxiosResponse);
    const post = vi.spyOn(service, "post");
    const patch = vi.spyOn(service, "patch");
    const remove = vi.spyOn(service, "delete");
    const signal = new AbortController().signal;
    await service.listProjects("example", signal);
    await service.listMembers("example", signal);
    await service.listModules("example", "project-1", signal);
    await service.listCycles("example", "project-1", signal);
    expect(get.mock.calls.map(([path]) => path)).toEqual([
      "/api/workspaces/example/projects/",
      "/api/workspaces/example/members/",
      "/api/workspaces/example/projects/project-1/modules/",
      "/api/workspaces/example/projects/project-1/cycles/",
    ]);
    for (const call of get.mock.calls) expect(call[2]).toEqual({ signal });
    expect(post).not.toHaveBeenCalled();
    expect(patch).not.toHaveBeenCalled();
    expect(remove).not.toHaveBeenCalled();
  });
  it("encodes route parameters and rejects incomplete/non-array lists", async () => {
    const service = new CurveProjectReadService();
    const get = vi.spyOn(service, "get").mockResolvedValue({ data: { results: [] } } as AxiosResponse);
    await expect(
      service.listModules("example/workspace", "project?other", new AbortController().signal)
    ).rejects.toThrow("Native list response is unavailable");
    expect(get.mock.calls[0][0]).toBe("/api/workspaces/example%2Fworkspace/projects/project%3Fother/modules/");
  });
  it.each([
    ["listProjects", null],
    ["listProjects", { id: "project-1", name: "Example", identifier: "EX", workspace: null }],
    [
      "listProjects",
      {
        id: "project-1",
        name: "Example",
        identifier: "EX",
        workspace: "workspace-1",
        project_lead: null,
        member_role: 15,
        module_view: "true",
        cycle_view: true,
        archived_at: null,
      },
    ],
    ["listMembers", { member: null }],
    ["listMembers", { member: { id: "human-1", display_name: { unexpected: true } } }],
  ] as const)("rejects malformed directory records for %s", async (method, invalid) => {
    const service = new CurveProjectReadService();
    vi.spyOn(service, "get").mockResolvedValue({ data: [invalid] } as AxiosResponse);
    await expect(service[method]("example", new AbortController().signal)).rejects.toThrow(
      "Native list response is unavailable"
    );
  });

  it.each(["listModules", "listCycles"] as const)(
    "rejects every malformed %s list without partial success",
    async (method) => {
      const service = new CurveProjectReadService();
      const get = vi.spyOn(service, "get");
      const source = {
        id: "source-1",
        name: "Example source",
        workspace_id: "workspace-1",
        project_id: "project-1",
        start_date: null,
        target_date: null,
        end_date: null,
        status: "planned",
      };
      const signal = new AbortController().signal;
      get.mockResolvedValue({ data: [source] } as AxiosResponse);
      await expect(service[method]("example", "project-1", signal)).resolves.toHaveLength(1);
      for (const invalid of [
        null,
        { ...source, project_id: null },
        { ...source, workspace_id: undefined },
        { ...source, name: 17 },
        { ...source, start_date: {} },
      ]) {
        get.mockResolvedValue({ data: [source, invalid] } as AxiosResponse);
        // oxlint-disable-next-line no-await-in-loop -- independent malformed fixtures reuse one isolated service.
        await expect(service[method]("example", "project-1", signal)).rejects.toThrow(
          "Native list response is unavailable"
        );
      }
    }
  );
});
