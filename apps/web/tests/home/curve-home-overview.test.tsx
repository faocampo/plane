/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CurveHomeOverviewView } from "@/components/home/curve-home-overview";

vi.mock("@/hooks/store/notifications", () => ({
  useWorkspaceNotifications: vi.fn(),
}));

vi.mock("@/services/curve.service", () => ({
  default: { listInitiatives: vi.fn() },
}));

vi.mock("@/services/dashboard.service", () => ({
  DashboardService: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

describe("Curve Home overview", () => {
  it("keeps Home focused on cross-project signals and routes detailed work to My work", () => {
    render(
      <CurveHomeOverviewView
        workspaceSlug="example-workspace"
        activeInitiatives={4}
        aligningInitiatives={2}
        needsAttention={1}
        unreadMentions={3}
        unreadNotifications={8}
        assignedWorkItems={12}
        pendingWorkItems={5}
        completedWorkItems={7}
      />
    );

    expect(screen.getByRole("heading", { name: "Your control room" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open My work/ })).toHaveAttribute("href", "/example-workspace/profile/");
    expect(screen.getByRole("link", { name: /Initiative needs attention/ })).toHaveAttribute(
      "href",
      "/example-workspace/curve/initiatives/?summary=NEEDS_ATTENTION"
    );
    expect(screen.getByRole("link", { name: /Initiatives in alignment/ })).toHaveAttribute(
      "href",
      "/example-workspace/curve/initiatives/?state=ALIGNING"
    );

    const attentionQueue = screen.getByRole("heading", { name: "Attention queue" }).parentElement?.parentElement;
    expect(attentionQueue).toBeTruthy();
    expect(within(attentionQueue as HTMLElement).getByText("Initiative needs attention")).toBeInTheDocument();
    expect(within(attentionQueue as HTMLElement).getByText("Initiatives in alignment")).toBeInTheDocument();
    expect(within(attentionQueue as HTMLElement).getByText("mentions waiting")).toBeInTheDocument();

    const workPulse = screen.getByRole("complementary", { name: "Work pulse" });
    expect(within(workPulse).getByText("12")).toBeInTheDocument();
    expect(within(workPulse).getByText("5")).toBeInTheDocument();
    expect(within(workPulse).getByText("7")).toBeInTheDocument();
    expect(within(workPulse).getByText("4")).toBeInTheDocument();
    expect(within(workPulse).getByText(/task management stays in My work/)).toBeInTheDocument();
  });

  it("uses the broader unread total when no mention is waiting", () => {
    render(<CurveHomeOverviewView workspaceSlug="example-workspace" unreadMentions={0} unreadNotifications={6} />);

    expect(screen.getByText("unread updates")).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
  });

  it("shows unavailable evidence explicitly instead of presenting failed requests as zero", () => {
    render(
      <CurveHomeOverviewView
        workspaceSlug="example-workspace"
        isInitiativesUnavailable
        isNotificationsUnavailable
        isWorkUnavailable
      />
    );

    expect(screen.getAllByText("Unavailable").length).toBeGreaterThanOrEqual(6);
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });
});
