/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CurveWorkspaceSidebar } from "@/components/curve/curve-workspace-sidebar";
import { TopNavigationRoot } from "@/components/navigation/top-navigation-root";

vi.mock("next/navigation", () => ({
  useParams: () => ({ workspaceSlug: "example-workspace" }),
  usePathname: () => "/example-workspace/curve/initiatives/",
}));
vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "light" }) }));
vi.mock("swr", () => ({ default: () => undefined }));
vi.mock("@plane/propel/scrollarea", () => ({
  ScrollArea: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("@plane/propel/tooltip", () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@plane/propel/icons", () => ({ InboxIcon: () => <span aria-hidden="true" /> }));
vi.mock("@/components/navigation", () => ({ TopNavPowerK: () => <div data-testid="command-search" /> }));
vi.mock("@/components/sidebar/sidebar-navigation", () => ({
  SidebarNavItem: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("@/components/sidebar/sidebar-toggle-button", () => ({
  AppSidebarToggleButton: () => <button type="button">Toggle navigation</button>,
}));
vi.mock("@/components/sidebar/sidebar-item", () => ({
  AppSidebarItem: () => <div data-testid="top-action" />,
}));
vi.mock("@/components/workspace/sidebar/sidebar-item", () => ({
  SidebarItemBase: () => <div data-testid="work-management-item" />,
}));
vi.mock("@/components/workspace/sidebar/workspace-menu-root", () => ({
  WorkspaceMenuRoot: ({ variant }: { variant: string }) => (
    <button type="button" data-testid="workspace-selector" data-variant={variant}>
      Example Organization workspace
    </button>
  ),
}));
vi.mock("@/components/workspace/sidebar/help-section/root", () => ({
  HelpMenuRoot: ({ showCurveAttribution }: { showCurveAttribution?: boolean }) => (
    <button type="button" data-testid="help-menu" data-curve-attribution={showCurveAttribution}>
      Help
    </button>
  ),
}));
vi.mock("@/components/workspace/sidebar/user-menu-root", () => ({ UserMenuRoot: () => <div>User</div> }));
vi.mock("@/hooks/store/use-app-theme", () => ({ useAppTheme: () => ({ toggleSidebar: vi.fn() }) }));
vi.mock("@/hooks/store/notifications", () => ({
  useWorkspaceNotifications: () => ({
    unreadNotificationsCount: { mention_unread_notifications_count: 0, total_unread_notifications_count: 0 },
    getUnreadNotificationsCount: vi.fn(),
  }),
}));
vi.mock("@/hooks/use-navigation-preferences", () => ({
  useAppRailPreferences: () => ({ preferences: { displayMode: "icon_only" } }),
}));
vi.mock("@/hooks/use-curve-workspace-shell", () => ({
  useCurveWorkspaceShell: () => ({ isEnabled: true }),
}));
vi.mock("@/app/(all)/[workspaceSlug]/(projects)/star-us-link", () => ({ StarUsOnGitHubLink: () => null }));

describe("Curve navigation placement", () => {
  it("keeps the workspace selector in the bottom area of the Curve sidebar", () => {
    render(<CurveWorkspaceSidebar />);

    const navigation = screen.getByLabelText("Curve workspace navigation");
    const selector = screen.getByTestId("workspace-selector");
    expect(selector).toHaveAttribute("data-variant", "curve-sidebar");
    expect(navigation.lastElementChild).toContainElement(selector);
    expect(screen.queryByText("Settings")).not.toBeInTheDocument();
  });

  it("removes the redundant global workspace selector while retaining Help attribution", () => {
    render(<TopNavigationRoot />);

    expect(screen.queryByTestId("workspace-selector")).not.toBeInTheDocument();
    expect(screen.getByTestId("help-menu")).toHaveAttribute("data-curve-attribution", "true");
    expect(screen.getByTestId("command-search")).toBeInTheDocument();
  });
});
