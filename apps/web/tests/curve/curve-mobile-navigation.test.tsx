import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CurveMobileNavigation } from "@/components/curve/curve-mobile-navigation";

describe("Curve mobile navigation", () => {
  it("renders as a modal drawer and closes with Escape", () => {
    const onOpenChange = vi.fn();
    render(
      <CurveMobileNavigation open onOpenChange={onOpenChange}>
        <a href="/x3m/curve">Foundation status</a>
      </CurveMobileNavigation>
    );

    const drawer = screen.getByRole("dialog", { name: "Curve workspace navigation" });
    expect(drawer).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("Foundation status")).toBeInTheDocument();

    fireEvent.keyDown(drawer, { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false, expect.anything());
  });
});
