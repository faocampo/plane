// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { LocalDocumentText } from "@/components/curve/initiatives/local-document-text";

it("renders document structure without changing the application heading hierarchy", () => {
  render(
    <LocalDocumentText
      label="PRD document"
      mediaType="text/markdown"
      text={"# Requirements\n\n## Outcome\n\n- **Clear status**\n- One next action"}
    />
  );
  expect(screen.getByRole("heading", { level: 5, name: "Requirements" })).toBeVisible();
  expect(screen.getByRole("heading", { level: 6, name: "Outcome" })).toBeVisible();
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
  expect(screen.getByText("Clear status").tagName).toBe("STRONG");
});
it("keeps raw HTML and remote images inert and rejects executable links", () => {
  const text =
    '<img src="https://example.invalid/pixel" onerror="alert(1)">\n\n<script>alert(1)</script>\n\n![Diagram](https://example.invalid/diagram.svg)\n\n[Unsafe](javascript:alert%281%29) [Reference](https://example.invalid/reference)';
  const { container } = render(<LocalDocumentText label="PRD document" mediaType="text/markdown" text={text} />);
  expect(container.querySelector("img,script,iframe")).toBeNull();
  expect(screen.getByText(/Image: Diagram/)).toBeVisible();
  expect(screen.queryByRole("link", { name: "Unsafe" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Reference" })).toHaveAttribute("rel", "noopener noreferrer");
});
it("preserves literal plain text and bounds synchronous formatting for large documents", () => {
  const { rerender, container } = render(
    <LocalDocumentText label="PRD document" mediaType="text/plain" text="# Literal heading" />
  );
  expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  expect(container.querySelector("pre")).toHaveTextContent("# Literal heading");
  const large = "# Long document\n" + "a".repeat(256_000);
  rerender(<LocalDocumentText label="PRD document" mediaType="text/markdown" text={large} />);
  expect(container.querySelector("pre")?.textContent).toBe(large);
});
