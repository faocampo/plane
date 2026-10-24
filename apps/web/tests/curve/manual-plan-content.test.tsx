// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MaterialContent, taskLabel } from "../../components/curve/initiatives/manual-plan-content";
import { material } from "./manual-plan-gate2-fixtures";

const definition = {
  ...material("DEFINITION"),
  content: JSON.stringify({
    repositories: [{ base_commit: "synthetic-pinned-base" }],
    slices: [
      {
        slice_key: "review",
        user_outcome: "Review a complete plan",
        in_scope: ["Show acceptance checks"],
        out_of_scope: ["Automatic execution"],
        verification_steps: [{ expected_result: "All checks are readable" }],
        rollback_plan: "Restore the previous view",
        proposed_delivery_refs: [{ provider_installation_id: "installation-a", source_issue_id: "task-a" }],
        additional_context: "Preserve additive content",
      },
    ],
    dependencies: [{ predecessor_slice_key: "prepare", successor_slice_key: "review" }],
  }),
};
describe("readable plan material", () => {
  it("exposes scope, checks, recovery and dependencies without opening technical data", () => {
    render(<MaterialContent material={definition} />);
    for (const text of [
      "Show acceptance checks",
      "Automatic execution",
      "All checks are readable",
      "Restore the previous view",
      "Preserve additive content",
    ])
      expect(screen.getByText(text)).toBeVisible();
    expect(screen.getByText("Technical source data").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("Depends on")).toBeVisible();
  });
  it("uses task identity and its matching outcome, with an explicit unavailable fallback", () => {
    expect(taskLabel(definition, "installation-a", "task-a")).toBe("review · Review a complete plan · task-a");
    expect(taskLabel(definition, "installation-b", "task-a")).toBe("Task title unavailable · task-a");
  });
  it("handles unreadable material without pretending it is reviewed content", () => {
    render(<MaterialContent material={{ ...definition, content: "invalid" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("could not be displayed");
  });
});
