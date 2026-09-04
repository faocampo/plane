/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ResizableSidebar } from "@/components/sidebar/resizable-sidebar";
import { AppSidebarToggleButton } from "@/components/sidebar/sidebar-toggle-button";

const { appTheme } = vi.hoisted(() => ({
  appTheme: {
    sidebarCollapsed: true,
    sidebarPeek: false,
    toggleSidebar: vi.fn(),
    toggleSidebarPeek: vi.fn(),
  },
}));

vi.mock("@/hooks/store/use-app-theme", () => ({ useAppTheme: () => appTheme }));
vi.mock("@plane/hooks", () => ({ usePlatformOS: () => ({ isMobile: false }) }));
vi.mock("@plane/propel/icon-button", () => ({
  IconButton: ({ icon: _icon, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { icon?: unknown }) => (
    <button type="button" {...props} />
  ),
}));

describe("Collapsed workspace navigation", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("opens the overlay peek when the collapsed-menu control is hovered", () => {
    render(<AppSidebarToggleButton controlsId="curve-workspace-navigation" />);

    const control = screen.getByRole("button", { name: "Toggle workspace navigation" });
    expect(control).toHaveAttribute("aria-controls", "curve-workspace-navigation");
    expect(control).toHaveAttribute("aria-expanded", "false");
    fireEvent.mouseEnter(control);

    expect(appTheme.toggleSidebarPeek).toHaveBeenCalledWith(true);
  });

  it("renders a non-modal overlay and dismisses it after the pointer leaves", () => {
    vi.useFakeTimers();
    const togglePeek = vi.fn();
    const { rerender } = render(
      <ResizableSidebar
        showPeek={false}
        isCollapsed
        width={250}
        setWidth={vi.fn()}
        toggleCollapsed={vi.fn()}
        togglePeek={togglePeek}
        peekDuration={1500}
      >
        <nav>Workspace links</nav>
      </ResizableSidebar>
    );

    const peek = screen.getByRole("complementary", { name: "Sidebar peek view" });
    expect(peek).toHaveClass("pointer-events-none", "translate-x-[-100%]");

    rerender(
      <ResizableSidebar
        showPeek
        isCollapsed
        width={250}
        setWidth={vi.fn()}
        toggleCollapsed={vi.fn()}
        togglePeek={togglePeek}
        peekDuration={1500}
      >
        <nav>Workspace links</nav>
      </ResizableSidebar>
    );
    expect(peek).toHaveClass("pointer-events-auto", "translate-x-0");
    expect(peek).toHaveStyle({ width: "250px" });

    fireEvent.mouseLeave(peek);
    vi.advanceTimersByTime(1499);
    expect(togglePeek).not.toHaveBeenCalledWith(false);
    vi.advanceTimersByTime(1);
    expect(togglePeek).toHaveBeenCalledWith(false);
  });

  it("keeps the overlay open while a sidebar dropdown owns focus", () => {
    vi.useFakeTimers();
    const togglePeek = vi.fn();
    render(
      <ResizableSidebar
        showPeek
        isCollapsed
        width={250}
        setWidth={vi.fn()}
        toggleCollapsed={vi.fn()}
        togglePeek={togglePeek}
        peekDuration={1500}
        isAnySidebarDropdownOpen
      >
        <nav>Workspace links</nav>
      </ResizableSidebar>
    );

    fireEvent.mouseLeave(screen.getByRole("complementary", { name: "Sidebar peek view" }));
    vi.advanceTimersByTime(1500);
    expect(togglePeek).not.toHaveBeenCalledWith(false);
  });
});
