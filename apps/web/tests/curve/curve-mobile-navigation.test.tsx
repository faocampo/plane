/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CurveMobileNavigation } from "@/components/curve/curve-mobile-navigation";

describe("Curve mobile navigation", () => {
  it("renders as a modal drawer and closes with Escape", () => {
    const onOpenChange = vi.fn();
    render(
      <CurveMobileNavigation open onOpenChange={onOpenChange}>
        <a href="/example-workspace/curve">Foundation status</a>
      </CurveMobileNavigation>
    );

    const drawer = screen.getByRole("dialog", { name: "Curve workspace navigation" });
    expect(drawer).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("Foundation status")).toBeInTheDocument();

    fireEvent.keyDown(drawer, { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false, expect.anything());
  });
});
