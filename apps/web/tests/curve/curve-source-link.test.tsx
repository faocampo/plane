import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildCurveSourceUrl, CurveSourceLink } from "@/components/curve/curve-source-link";

const repository = "https://github.com/faocampo/plane";
const revision = "0123456789abcdef0123456789abcdef01234567";

describe("Curve source attribution", () => {
  it("links the visible AGPL attribution to the configured public source revision", () => {
    render(<CurveSourceLink repository={repository} revision={revision} />);

    expect(screen.getByRole("link", { name: /open source for curve revision/i })).toHaveAttribute(
      "href",
      `${repository}/tree/${revision}`
    );
    expect(screen.getByText("Source code (AGPL)")).toBeInTheDocument();
  });

  it.each([undefined, "preview", "curve/m0-s4", "0123456"])(
    "fails closed for a missing or mutable revision: %s",
    (candidateRevision) => {
      expect(buildCurveSourceUrl(repository, candidateRevision)).toBeUndefined();
      render(<CurveSourceLink repository={repository} revision={candidateRevision} />);
      expect(screen.queryByRole("link")).not.toBeInTheDocument();
      expect(screen.getByText("Source code unavailable")).toBeInTheDocument();
    }
  );
});
