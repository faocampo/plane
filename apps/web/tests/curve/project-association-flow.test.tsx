/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider, Link } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { ProjectAssociationFlow } from "@/components/curve/projects/project-association-flow";
import { ProjectAssociationNavigationGuard } from "@/components/curve/projects/project-association-panel";
import { useCurveProjectAssociation } from "@/hooks/use-curve-project-association";
import {
  ASSOCIATION,
  PRODUCT,
  PROJECT,
  WORKSPACE,
  deferred,
  discovery,
  makePort,
  projectRead,
  receipt,
} from "./project-association-fixtures";

vi.mock("@/services/curve-project-association.service", () => ({ curveProjectAssociationPort: {} }));

function Harness({ port = makePort(), guard = false }: { port?: ReturnType<typeof makePort>; guard?: boolean }) {
  const flow = useCurveProjectAssociation({
    workspaceSlug: "example",
    workspaceId: WORKSPACE,
    actorId: "actor-a",
    projects: projectRead,
    port,
    onAccessUnavailable: vi.fn(),
  });
  return (
    <>
      {guard && <ProjectAssociationNavigationGuard blocked={flow.locked} />}
      <ProjectAssociationFlow flow={flow} />
      {guard && <Link to="/other">Other page</Link>}
    </>
  );
}
async function selectAndReview() {
  await screen.findByRole("option", { name: "Example storefront · SHOP" });
  fireEvent.change(screen.getByLabelText("Source project"), { target: { value: PROJECT } });
  fireEvent.change(screen.getByLabelText("Existing Product"), { target: { value: PRODUCT } });
  fireEvent.click(screen.getByRole("button", { name: "Review association" }));
  await screen.findByRole("button", { name: "Associate project" });
}

describe("native association React screen", () => {
  it("requires two explicit choices, preserves field labels, and focuses exact relationship review", async () => {
    const port = makePort();
    render(<Harness port={port} />);
    await screen.findByRole("option", { name: "Example storefront · SHOP" });
    expect(screen.getByLabelText("Source project")).toHaveValue("");
    expect(screen.getByLabelText("Existing Product")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Review association" })).toBeDisabled();
    await selectAndReview();
    expect(screen.getByRole("heading", { name: "Connect work to a Product" })).toHaveFocus();
    expect(screen.getByText("Example catalog")).toBeInTheDocument();
    expect(screen.getByText("Example storefront")).toBeInTheDocument();
    expect(screen.getByText(/Product version 3/)).toBeInTheDocument();
    expect(port.create).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Back to choices" }));
    expect(screen.getByLabelText("Source project")).toHaveValue(PROJECT);
    expect(screen.getByLabelText("Existing Product")).toHaveValue(PRODUCT);
    expect(screen.getByLabelText("Existing Product")).toHaveFocus();
  });

  it("shows a confirmed receipt only after the typed server response", async () => {
    const port = makePort();
    render(<Harness port={port} />);
    await selectAndReview();
    expect(screen.queryByText(ASSOCIATION)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Associate project" }));
    await screen.findByRole("heading", { name: "Project associated" });
    expect(screen.getByRole("heading", { name: "Project associated" })).toHaveFocus();
    expect(screen.getByText(ASSOCIATION)).toBeInTheDocument();
    expect(screen.getByText("2026-10-04T12:01:00Z")).toBeInTheDocument();
  });

  it("makes uncertainty and safe replay explicit, with no fake success or new command option", async () => {
    const port = makePort();
    port.create.mockRejectedValueOnce({ code: "MUTATION_OUTCOME_UNKNOWN" });
    render(<Harness port={port} />);
    await selectAndReview();
    fireEvent.click(screen.getByRole("button", { name: "Associate project" }));
    await screen.findByRole("heading", { name: "Recover the association result" });
    expect(screen.getByRole("alert")).toHaveTextContent("The server may have recorded this association");
    expect(screen.queryByText(ASSOCIATION)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back to choices" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Associate project" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry same request" }));
    await screen.findByRole("heading", { name: "Project associated" });
    expect(port.create.mock.calls[1][3].idempotencyKey).toBe(port.create.mock.calls[0][3].idempotencyKey);
  });

  it.each(["ASSOCIATED_WITH_SELECTED_PRODUCT", "ASSOCIATED_ELSEWHERE"] as const)(
    "describes %s without offering a command or revealing another identity",
    async (availability) => {
      const port = makePort();
      port.discover.mockResolvedValue(
        availability === "ASSOCIATED_WITH_SELECTED_PRODUCT"
          ? { ...discovery, availability, association_id: ASSOCIATION }
          : { ...discovery, availability, association_id: null }
      );
      render(<Harness port={port} />);
      await screen.findByRole("option", { name: "Example storefront · SHOP" });
      fireEvent.change(screen.getByLabelText("Source project"), { target: { value: PROJECT } });
      fireEvent.change(screen.getByLabelText("Existing Product"), { target: { value: PRODUCT } });
      fireEvent.click(screen.getByRole("button", { name: "Review association" }));
      await screen.findByRole("button", { name: "Back to choices" });
      expect(screen.getByRole("status")).toHaveTextContent(
        availability === "ASSOCIATED_WITH_SELECTED_PRODUCT"
          ? "already associated with the selected Product"
          : "already associated elsewhere"
      );
      expect(screen.queryByRole("button", { name: "Associate project" })).not.toBeInTheDocument();
      expect(screen.queryByText(ASSOCIATION)).not.toBeInTheDocument();
    }
  );

  it("keeps absent Product discovery distinct from a usable empty relationship", async () => {
    const port = makePort();
    port.listProducts.mockResolvedValue([]);
    render(<Harness port={port} />);
    await screen.findByText(/No active Products are available/);
    expect(screen.getByRole("button", { name: "Review association" })).toBeDisabled();
    expect(port.discover).not.toHaveBeenCalled();
  });

  it("redacts protected names on permission denial and presents safe recovery", async () => {
    const port = makePort();
    port.create.mockRejectedValue({ status: 403 });
    render(<Harness port={port} />);
    await selectAndReview();
    fireEvent.click(screen.getByRole("button", { name: "Associate project" }));
    await screen.findByText("Access could not be verified");
    expect(screen.queryByText("Example catalog")).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Example storefront · SHOP" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review association" })).toBeDisabled();
  });

  it("blocks route/Back navigation while sending and permits an explicit informed leave", async () => {
    const port = makePort();
    const delayed = deferred<{ data: typeof receipt; etag: string }>();
    port.create.mockReturnValue(delayed.promise);
    const router = createMemoryRouter(
      [
        { path: "/", element: <Harness port={port} guard /> },
        { path: "/other", element: <h1>Other page destination</h1> },
      ],
      { initialEntries: ["/other", "/"] }
    );
    render(<RouterProvider router={router} />);
    await selectAndReview();
    fireEvent.click(screen.getByRole("button", { name: "Associate project" }));
    await act(async () => {
      void router.navigate(-1);
    });
    await screen.findByRole("heading", { name: "The association result is still pending" });
    expect(screen.getByRole("heading", { name: "The association result is still pending" })).toHaveFocus();
    expect(router.state.location.pathname).toBe("/");
    fireEvent.click(screen.getByRole("button", { name: "Stay and recover" }));
    expect(screen.queryByText("The association result is still pending")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop waiting" }));
    fireEvent.click(screen.getByRole("link", { name: "Other page" }));
    fireEvent.click(await screen.findByRole("button", { name: "Leave without confirming" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/other"));
    expect(port.create.mock.calls[0][3].signal?.aborted).toBe(true);
    await act(async () => delayed.resolve({ data: receipt, etag: "exact" }));
    expect(screen.getByRole("heading", { name: "Other page destination" })).toBeInTheDocument();
  });
});
