/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { forwardRef } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LinkCreateUpdateModal } from "@/components/home/widgets/links/create-update-link-modal";

vi.mock("@plane/i18n", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@plane/propel/button", () => ({
  Button: ({ loading: _loading, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean }) => (
    <button {...props} />
  ),
}));
vi.mock("@plane/ui", () => ({
  Input: forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement> & { hasError?: boolean }>(
    ({ hasError: _hasError, ...props }, ref) => <input {...props} ref={ref} />
  ),
  ModalCore: ({ isOpen, children }: { isOpen: boolean; children: React.ReactNode }) =>
    isOpen ? <div role="dialog">{children}</div> : null,
}));

const operations = () => ({
  create: vi.fn().mockResolvedValue(undefined),
  update: vi.fn().mockResolvedValue(undefined),
});

describe("Quicklink form", () => {
  it("keeps malformed URLs in the form and blocks the create request with an inline error", async () => {
    const linkOperations = operations();
    render(<LinkCreateUpdateModal isModalOpen linkOperations={linkOperations} />);

    const url = screen.getByLabelText(/^link\.modal\.url\.text/);
    fireEvent.change(url, { target: { value: "not a website" } });
    fireEvent.click(screen.getByRole("button", { name: "add home.quick_links.title" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("link.modal.url.required");
    expect(url).toHaveValue("not a website");
    expect(url).toHaveAttribute("aria-describedby", "quick-link-url-error");
    expect(linkOperations.create).not.toHaveBeenCalled();
  });

  it("normalizes a recognizable website address before creating the Quicklink", async () => {
    const linkOperations = operations();
    const handleOnClose = vi.fn();
    render(<LinkCreateUpdateModal isModalOpen linkOperations={linkOperations} handleOnClose={handleOnClose} />);

    fireEvent.change(screen.getByLabelText(/^link\.modal\.url\.text/), { target: { value: "example.com/docs" } });
    fireEvent.change(screen.getByLabelText(/^link\.modal\.title\.text/), { target: { value: "Documentation" } });
    fireEvent.click(screen.getByRole("button", { name: "add home.quick_links.title" }));

    await waitFor(() =>
      expect(linkOperations.create).toHaveBeenCalledWith({
        title: "Documentation",
        url: "https://example.com/docs",
      })
    );
    expect(handleOnClose).toHaveBeenCalledOnce();
  });

  it("updates the existing Quicklink instead of creating a duplicate", async () => {
    const linkOperations = operations();
    render(
      <LinkCreateUpdateModal
        isModalOpen
        linkOperations={linkOperations}
        preloadedData={{ id: "link-1", title: "Old title", url: "https://example.com/old" }}
      />
    );

    fireEvent.change(screen.getByLabelText(/^link\.modal\.url\.text/), { target: { value: "example.com/new" } });
    fireEvent.click(screen.getByRole("button", { name: "update home.quick_links.title" }));

    await waitFor(() =>
      expect(linkOperations.update).toHaveBeenCalledWith("link-1", {
        title: "Old title",
        url: "https://example.com/new",
      })
    );
    expect(linkOperations.create).not.toHaveBeenCalled();
  });
});
