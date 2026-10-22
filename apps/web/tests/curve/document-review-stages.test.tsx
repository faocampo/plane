/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DocumentReviewStages } from "@/components/curve/initiatives/document-review-stages";

describe("document approval stage navigation", () => {
  it("shows the PRD first and opens the implementation plan with one click", () => {
    render(<DocumentReviewStages prd={<p>Current PRD</p>} plan={<p>Current plan</p>} />);
    expect(screen.getByText("Current PRD")).toBeVisible();
    expect(screen.getByText("Current plan")).not.toBeVisible();
    const plan = screen.getByRole("tab", { name: /Implementation plan/ });
    fireEvent.click(plan);
    expect(plan).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Current plan")).toBeVisible();
    expect(screen.getByText("Current PRD")).not.toBeVisible();
    expect(screen.getAllByRole("tab")).toHaveLength(2);
  });

  it("updates both approval summaries without changing the selected stage", () => {
    const { rerender } = render(
      <DocumentReviewStages prd={<p>Current PRD</p>} plan={<p>Current plan</p>} statuses={["REVIEW", "LOCKED"]} />
    );
    expect(screen.getByRole("tab", { name: /Product requirements.*Waiting for approval/ })).toBeVisible();
    expect(screen.getByRole("tab", { name: /Implementation plan.*After Product approval/ })).toBeVisible();
    rerender(
      <DocumentReviewStages prd={<p>Current PRD</p>} plan={<p>Current plan</p>} statuses={["APPROVED", "CHANGES"]} />
    );
    expect(screen.getByRole("tab", { name: /Product requirements.*Approved/ })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(screen.getByRole("tab", { name: /Implementation plan.*Changes requested/ })).toBeVisible();
    expect(screen.getAllByRole("tab")).toHaveLength(2);
  });

  it("supports arrow, Home and End keys with focus following the selected stage", () => {
    render(<DocumentReviewStages prd={<p>Current PRD</p>} plan={<p>Current plan</p>} />);
    const [prd, plan] = screen.getAllByRole("tab");
    prd.focus();
    fireEvent.keyDown(prd, { key: "ArrowRight" });
    expect(plan).toHaveFocus();
    expect(plan).toHaveAttribute("tabindex", "0");
    expect(prd).toHaveAttribute("tabindex", "-1");
    fireEvent.keyDown(plan, { key: "Home" });
    expect(prd).toHaveFocus();
    fireEvent.keyDown(prd, { key: "End" });
    expect(plan).toHaveFocus();
    fireEvent.keyDown(plan, { key: "ArrowLeft" });
    expect(prd).toHaveFocus();
  });
});
