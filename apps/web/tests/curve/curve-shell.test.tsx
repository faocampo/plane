import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CurveEmptyState } from "@/components/curve/curve-empty-state";
import { shouldShowCurveNavigation } from "@/components/curve/curve-navigation";

describe("Curve module shell", () => {
  it("renders the accessible empty workspace shell", () => {
    render(<CurveEmptyState />);

    expect(screen.getByRole("heading", { name: "Curve" })).toBeInTheDocument();
    expect(screen.getByText("Your AI-native product development workspace is ready.")).toBeInTheDocument();
  });

  it.each([
    [false, false, false],
    [true, true, false],
    [true, false, true],
  ])("derives navigation visibility from backend eligibility", (isEnabled, isLoading, expected) => {
    expect(shouldShowCurveNavigation(isEnabled, isLoading)).toBe(expected);
  });
});
