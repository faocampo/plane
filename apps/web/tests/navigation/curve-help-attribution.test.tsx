/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { HelpMenuRoot } from "@/components/workspace/sidebar/help-section/root";

vi.mock("@plane/i18n", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@plane/ui", () => {
  // oxlint-disable-next-line unicorn/consistent-function-scoping -- Vitest requires this mock implementation inside the hoisted factory.
  const CustomMenu = ({ children, customButton }: { children: React.ReactNode; customButton: React.ReactNode }) => (
    <div>
      {customButton}
      <div>{children}</div>
    </div>
  );
  CustomMenu.MenuItem = ({ children }: { children: React.ReactNode }) => <div>{children}</div>;
  return { CustomMenu };
});
vi.mock("@/components/global", () => ({ ProductUpdatesModal: () => null }));
vi.mock("@/components/global/version-number", () => ({ PlaneVersionNumber: () => <span>Plane version</span> }));
vi.mock("@/components/sidebar/sidebar-item", () => ({ AppSidebarItem: () => <button type="button">Help</button> }));
vi.mock("@/components/curve/curve-source-link", () => ({
  CurveSourceLink: () => <a href="https://github.com/faocampo/plane">Curve source</a>,
}));
vi.mock("@/hooks/store/use-power-k", () => ({
  usePowerK: () => ({ toggleShortcutsListModal: vi.fn() }),
}));
vi.mock("@plane/propel/icons", () => ({ PageIcon: () => null }));

describe("Curve Help attribution", () => {
  it("keeps Plane and Curve source information inside Help for the Curve shell", () => {
    render(<HelpMenuRoot showCurveAttribution />);

    expect(screen.getByText("Plane powers Curve's work-management capabilities.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Plane source (AGPL)" })).toHaveAttribute(
      "href",
      "https://github.com/makeplane/plane"
    );
    expect(screen.getByRole("link", { name: "Curve source" })).toHaveAttribute(
      "href",
      "https://github.com/faocampo/plane"
    );
  });

  it("does not add Curve attribution outside the Curve shell", () => {
    render(<HelpMenuRoot />);

    expect(screen.queryByText("Plane powers Curve's work-management capabilities.")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Curve source" })).not.toBeInTheDocument();
  });
});
