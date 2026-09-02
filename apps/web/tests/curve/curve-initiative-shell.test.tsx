/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ICurveInitiative, ICurveProduct, IWorkspaceMember } from "@plane/types";
import { mergeCurveInitiatives, toSafeCurveProblem } from "@/components/curve/initiatives/initiative-data";
import { InitiativeWorkspace } from "@/components/curve/initiatives/initiative-workspace";

const { useCurveInitiativesMock } = vi.hoisted(() => ({
  useCurveInitiativesMock: vi.fn(),
}));

vi.mock("@/hooks/use-curve-initiatives", () => {
  return { useCurveInitiatives: useCurveInitiativesMock };
});

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const product: ICurveProduct = {
  schema_version: "1.0",
  id: "product-1",
  workspace_id: "workspace-1",
  key: "loomit",
  name: "Loomit",
  description: null,
  timezone: "America/Argentina/Buenos_Aires",
  state: "ACTIVE",
  owner: { actor_type: "HUMAN", actor_id: "user-1" },
  version: 1,
  created_at: "2026-09-01T12:00:00Z",
  updated_at: "2026-09-01T12:00:00Z",
  created_by: { actor_type: "HUMAN", actor_id: "user-1" },
  updated_by: { actor_type: "HUMAN", actor_id: "user-1" },
  archived_at: null,
  archived_by: null,
};

const member = (id: string, displayName: string): IWorkspaceMember => ({
  id: `membership-${id}`,
  member: {
    id,
    avatar_url: "",
    display_name: displayName,
    first_name: displayName.split(" ")[0] ?? displayName,
    last_name: displayName.split(" ").slice(1).join(" "),
    is_bot: false,
  },
  role: 20,
  is_active: true,
});

const members = [member("user-1", "Federico Ocampo"), member("user-2", "Paula Ortega"), member("user-3", "Diego Vega")];

const initiative = (
  id: string,
  title: string,
  state: ICurveInitiative["state"],
  riskTier: ICurveInitiative["risk_tier"]
): ICurveInitiative => ({
  schema_version: "1.0",
  id,
  workspace_id: "workspace-1",
  product_id: product.id,
  mode: "STANDALONE",
  roadmap_item_id: null,
  keyword: id,
  title,
  description: { schema_version: "1.0", format: "MARKDOWN", body: `Outcome for ${title}` },
  risk_tier: riskTier,
  state,
  paused_from_state: state === "PAUSED" ? "ALIGNING" : null,
  workflow_version_id: null,
  creator: { actor_type: "HUMAN", actor_id: "user-1" },
  gate_assignments: [
    {
      id: `${id}-gate-1`,
      workspace_id: "workspace-1",
      initiative_id: id,
      gate_type: "PRD_APPROVAL",
      approver: { actor_type: "HUMAN", actor_id: "user-1" },
      valid_from: "2026-09-01T12:00:00Z",
      valid_until: null,
      delegation_reason: null,
    },
    {
      id: `${id}-gate-2`,
      workspace_id: "workspace-1",
      initiative_id: id,
      gate_type: "PLAN_APPROVAL",
      approver: { actor_type: "HUMAN", actor_id: "user-2" },
      valid_from: "2026-09-01T12:00:00Z",
      valid_until: null,
      delegation_reason: null,
    },
    {
      id: `${id}-gate-3`,
      workspace_id: "workspace-1",
      initiative_id: id,
      gate_type: "CODE_READINESS",
      approver: { actor_type: "HUMAN", actor_id: "user-3" },
      valid_from: "2026-09-01T12:00:00Z",
      valid_until: null,
      delegation_reason: null,
    },
  ],
  first_external_resource_at: null,
  version: 1,
  created_at: "2026-09-01T12:00:00Z",
  updated_at: "2026-09-01T12:00:00Z",
  updated_by: { actor_type: "HUMAN", actor_id: "user-1" },
});

const initiatives = [
  initiative("sdk-compatibility", "Loomit SDK compatibility panel", "ALIGNING", "STANDARD"),
  initiative("rollout-confidence", "Experiment rollout confidence", "DRAFT", "HIGH"),
  initiative("evidence-ledger", "Internal release evidence ledger", "PAUSED", "STANDARD"),
  initiative("campaign-cleanup", "Legacy campaign rules cleanup", "CANCELLED", "LOW"),
];

const defaultHookValue = {
  products: [product],
  initiatives,
  nextCursor: "next-page",
  selectedInitiative: initiatives[0],
  selectedEtag: '"curve-initiative:sdk-compatibility:v1"',
  activeMembers: members,
  problem: undefined,
  isLoading: false,
  isLoadingMore: false,
  isMutating: false,
  isPermissionLimited: false,
  isConflict: false,
  selectInitiative: vi.fn(),
  loadMore: vi.fn(),
  createInitiative: vi.fn().mockResolvedValue(true),
  acceptRefinement: vi.fn().mockResolvedValue(true),
  pauseInitiative: vi.fn().mockResolvedValue(true),
  resumeInitiative: vi.fn().mockResolvedValue(true),
  cancelInitiative: vi.fn().mockResolvedValue(true),
  refreshSelected: vi.fn(),
  refresh: vi.fn(),
};

describe("Curve Initiative shell", () => {
  beforeEach(() => {
    useCurveInitiativesMock.mockReset();
    useCurveInitiativesMock.mockReturnValue({ ...defaultHookValue });
  });

  it("keeps every loaded Initiative in the list and filters without changing server state", () => {
    render(<InitiativeWorkspace workspaceSlug="x3m" />);

    for (const item of initiatives) expect(screen.getAllByText(item.title).length).toBeGreaterThan(0);
    const filters = screen.getByRole("region", { name: "Initiative filters" });
    expect(within(filters).getByRole("status")).toHaveTextContent("4 visible loaded Initiatives · more available");

    fireEvent.change(screen.getByLabelText("Filter by lifecycle state"), { target: { value: "PAUSED" } });
    expect(within(filters).getByRole("status")).toHaveTextContent("1 visible loaded Initiative");
    expect(screen.getByText("Internal release evidence ledger")).toBeInTheDocument();
    expect(screen.queryByText("Experiment rollout confidence")).not.toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Search title, keyword, Product, or description"), {
      target: { value: "no-match" },
    });
    expect(screen.getByText("No Initiatives match these filters")).toBeInTheDocument();
  });

  it("uses one explicit pagination control and retains unique server order", () => {
    const loadMore = vi.fn();
    useCurveInitiativesMock.mockReturnValue({ ...defaultHookValue, loadMore });
    render(<InitiativeWorkspace workspaceSlug="x3m" />);

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(loadMore).toHaveBeenCalledOnce();

    const updated = { ...initiatives[0], title: "Updated SDK compatibility panel", version: 2 };
    expect(mergeCurveInitiatives(initiatives.slice(0, 2), [updated, initiatives[2]])).toEqual([
      updated,
      initiatives[1],
      initiatives[2],
    ]);
  });

  it("requires three distinct humans for Standard risk before creating", async () => {
    const createInitiative = vi.fn().mockResolvedValue(true);
    useCurveInitiativesMock.mockReturnValue({ ...defaultHookValue, createInitiative });
    render(<InitiativeWorkspace workspaceSlug="x3m" />);

    fireEvent.click(screen.getByRole("button", { name: "New Initiative" }));
    fireEvent.change(screen.getByLabelText(/Title/), { target: { value: "New governed Initiative" } });
    fireEvent.change(screen.getByLabelText(/Keyword/), { target: { value: "new-initiative" } });
    fireEvent.change(screen.getByRole("textbox", { name: /Problem and intended outcome/ }), {
      target: { value: "Improve delivery confidence." },
    });
    fireEvent.change(screen.getByLabelText("Technical Approver"), { target: { value: "user-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Initiative" }));

    expect(createInitiative).not.toHaveBeenCalled();
    expect(screen.getAllByText("Choose three distinct active humans for Standard or High risk.")).toHaveLength(3);
    await waitFor(() => expect(screen.getByLabelText("Product Approver")).toHaveFocus());
  });

  it("resets the creation form after closing and reopening it", () => {
    render(<InitiativeWorkspace workspaceSlug="x3m" />);

    fireEvent.click(screen.getByRole("button", { name: "New Initiative" }));
    fireEvent.change(screen.getByLabelText(/Title/), { target: { value: "Temporary title" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "New Initiative" }));

    expect(screen.getByLabelText(/Title/)).toHaveValue("");
  });

  it("explains why Initiative creation is unavailable without an active Product", () => {
    useCurveInitiativesMock.mockReturnValue({ ...defaultHookValue, products: [] });
    render(<InitiativeWorkspace workspaceSlug="x3m" />);

    const createButton = screen.getByRole("button", { name: "New Initiative" });
    expect(createButton).toBeDisabled();
    expect(createButton).toHaveAttribute("aria-describedby", "curve-initiative-create-requirement");
    expect(screen.getByText("An active Product is required before an Initiative can be created.")).toBeInTheDocument();
  });

  it("creates one standalone Draft intent with the three gate assignments and announces success", async () => {
    const createInitiative = vi.fn().mockResolvedValue(true);
    useCurveInitiativesMock.mockReturnValue({ ...defaultHookValue, createInitiative });
    render(<InitiativeWorkspace workspaceSlug="x3m" />);

    fireEvent.click(screen.getByRole("button", { name: "New Initiative" }));
    fireEvent.change(screen.getByLabelText(/Title/), { target: { value: "New governed Initiative" } });
    fireEvent.change(screen.getByLabelText(/Keyword/), { target: { value: "new-initiative" } });
    fireEvent.change(screen.getByRole("textbox", { name: /Problem and intended outcome/ }), {
      target: { value: "Improve delivery confidence." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Initiative" }));

    await waitFor(() =>
      expect(createInitiative).toHaveBeenCalledWith({
        product_id: product.id,
        mode: "STANDALONE",
        roadmap_item_id: null,
        keyword: "new-initiative",
        title: "New governed Initiative",
        description: { schema_version: "1.0", format: "MARKDOWN", body: "Improve delivery confidence." },
        risk_tier: "STANDARD",
        gate_assignments: [
          { gate_type: "PRD_APPROVAL", approver_user_id: "user-1" },
          { gate_type: "PLAN_APPROVAL", approver_user_id: "user-2" },
          { gate_type: "CODE_READINESS", approver_user_id: "user-3" },
        ],
      })
    );
    expect(screen.getByText("Initiative created in Draft state.")).toBeInTheDocument();
  });

  it("renders the approved portfolio context, metadata, and recovery states", () => {
    const { rerender } = render(<InitiativeWorkspace workspaceSlug="x3m" />);

    expect(screen.getByText("Local · manual-first")).toBeInTheDocument();
    const summary = screen.getByRole("region", { name: "Loaded Initiative portfolio summary" });
    expect(within(summary).getByText("Active")).toBeInTheDocument();
    expect(within(summary).getByText("Paused")).toBeInTheDocument();
    expect(within(summary).getByText("Needs attention")).toBeInTheDocument();
    expect(screen.getByText("Lifecycle activity")).toBeInTheDocument();
    expect(screen.getByText("Creator")).toBeInTheDocument();
    expect(screen.getByText("Workflow version")).toBeInTheDocument();
    expect(screen.getByText("Optimistic version")).toBeInTheDocument();

    useCurveInitiativesMock.mockReturnValue({
      ...defaultHookValue,
      initiatives: [],
      nextCursor: undefined,
      selectedInitiative: undefined,
      selectedEtag: undefined,
    });
    rerender(<InitiativeWorkspace key="empty" workspaceSlug="x3m" />);
    expect(screen.getByText("No Initiatives yet")).toBeInTheDocument();

    useCurveInitiativesMock.mockReturnValue({ ...defaultHookValue, isPermissionLimited: true });
    rerender(<InitiativeWorkspace key="permission" workspaceSlug="x3m" />);
    expect(screen.getByRole("heading", { name: "Initiatives are unavailable" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Return to workspace" })).toHaveAttribute("href", "/x3m");

    useCurveInitiativesMock.mockReturnValue({ ...defaultHookValue, isLoading: true });
    rerender(<InitiativeWorkspace key="loading" workspaceSlug="x3m" />);
    expect(screen.getByLabelText("Loading Initiatives")).toBeInTheDocument();
  });

  it("requires and submits a lifecycle reason", async () => {
    const pauseInitiative = vi.fn().mockResolvedValue(true);
    useCurveInitiativesMock.mockReturnValue({ ...defaultHookValue, pauseInitiative });
    render(<InitiativeWorkspace workspaceSlug="x3m" />);

    const detail = screen.getByRole("region", { name: "Selected Initiative" });
    fireEvent.click(within(detail).getByRole("button", { name: "Pause" }));
    fireEvent.click(screen.getByRole("button", { name: "Pause Initiative" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a reason.");
    expect(pauseInitiative).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Awaiting backend contract" } });
    fireEvent.click(screen.getByRole("button", { name: "Pause Initiative" }));
    await waitFor(() => expect(pauseInitiative).toHaveBeenCalledWith("Awaiting backend contract"));

    fireEvent.click(within(detail).getByRole("button", { name: "Cancel" }));
    expect(screen.getByText(/Cancel “Loomit SDK compatibility panel”/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Keep current state" }));
  });

  it("preserves safe conflict evidence and exposes deliberate refresh", () => {
    const refreshSelected = vi.fn();
    useCurveInitiativesMock.mockReturnValue({
      ...defaultHookValue,
      problem: {
        type: "https://curve.x3m.internal/problems/precondition-failed",
        title: "The Initiative changed",
        status: 412,
        correlation_id: "corr-safe",
      },
      isConflict: true,
      refreshSelected,
    });
    render(<InitiativeWorkspace workspaceSlug="x3m" />);

    expect(screen.getByRole("alert")).toHaveTextContent("The last confirmed workspace state remains visible");
    expect(screen.getByRole("alert")).toHaveTextContent("Reference corr-safe");
    fireEvent.click(screen.getByRole("button", { name: "Reload current state" }));
    expect(refreshSelected).toHaveBeenCalledOnce();

    expect(
      toSafeCurveProblem(
        { status: 412, data: { title: "Private title", detail: "private diagnostic", correlation_id: "corr-safe" } },
        "Fallback"
      )
    ).toEqual({
      type: "https://curve.x3m.internal/problems/request-failed",
      title: "The Initiative changed",
      status: 412,
      correlation_id: "corr-safe",
    });
  });
});
