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
  key: "example-product",
  name: "Example Product",
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

const members = [
  member("user-1", "Reviewer Alpha"),
  member("user-2", "Reviewer Beta"),
  member("user-3", "Reviewer Gamma"),
];

const initiative = (
  id: string,
  title: string,
  state: ICurveInitiative["state"],
  riskTier: ICurveInitiative["risk_tier"]
): ICurveInitiative => ({
  schema_version: "1.1",
  id,
  workspace_id: "workspace-1",
  product_id: product.id,
  mode: "STANDALONE",
  roadmap_item_id: null,
  keyword: id,
  title,
  description: { schema_version: "1.0", format: "MARKDOWN", body: `Outcome for ${title}` },
  risk_tier: riskTier,
  business_intent: "STRATEGIC",
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
  initiative("capability-overview", "Example capability overview", "ALIGNING", "STANDARD"),
  initiative("rollout-confidence", "Experiment rollout confidence", "DRAFT", "HIGH"),
  initiative("evidence-ledger", "Internal release evidence ledger", "PAUSED", "STANDARD"),
  initiative("campaign-cleanup", "Legacy campaign rules cleanup", "CANCELLED", "LOW"),
];

const defaultHookValue = {
  products: [product],
  initiatives,
  nextCursor: "next-page",
  selectedInitiative: initiatives[0],
  selectedEtag: '"curve-initiative:capability-overview:v1"',
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
  updateInitiativeDraft: vi.fn().mockResolvedValue(true),
  acceptRefinement: vi.fn().mockResolvedValue(true),
  pauseInitiative: vi.fn().mockResolvedValue(true),
  resumeInitiative: vi.fn().mockResolvedValue(true),
  cancelInitiative: vi.fn().mockResolvedValue(true),
  refreshSelected: vi.fn(),
  refresh: vi.fn(),
};

const openCreation = async () => {
  fireEvent.click(screen.getByRole("button", { name: "New Initiative" }));
  await waitFor(() => expect(screen.getByLabelText("Title")).toHaveFocus());
};
const fillDefinition = () => {
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Improve delivery confidence" } });
  fireEvent.change(screen.getByRole("textbox", { name: "Problem and intended outcome" }), {
    target: { value: "Make releases easier to verify." },
  });
};
const continueToReviewers = () => fireEvent.click(screen.getByRole("button", { name: "Continue to reviewers" }));
const assignReviewers = (ids = ["user-1", "user-2", "user-3"]) => {
  ["Product Approver", "Technical Approver", "Code Approver"].forEach((label, index) => {
    fireEvent.change(screen.getByLabelText(label), { target: { value: ids[index] } });
  });
};
const create = () => fireEvent.click(screen.getByRole("button", { name: "Create Initiative" }));
const selectDraft = () =>
  useCurveInitiativesMock.mockReturnValue({
    ...defaultHookValue,
    selectedInitiative: initiatives[1],
    selectedEtag: '"curve-initiative:rollout-confidence:v1"',
  });

describe("Curve Initiative shell", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
    useCurveInitiativesMock.mockReset();
    vi.clearAllMocks();
    useCurveInitiativesMock.mockReturnValue({ ...defaultHookValue });
  });

  it("filters loaded data and clears every filter without changing server state", async () => {
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    const filters = screen.getByRole("region", { name: "Initiative filters" });
    expect(within(filters).getByRole("status")).toHaveTextContent("Showing 4 of 4 · more available");
    fireEvent.change(screen.getByLabelText("Filter by lifecycle state"), { target: { value: "PAUSED" } });
    expect(within(filters).getByRole("status")).toHaveTextContent("Showing 1 of 4");
    fireEvent.change(screen.getByPlaceholderText("Search title, keyword, Product, or description"), {
      target: { value: "no-match" },
    });
    expect(screen.getByText("No Initiatives match these filters")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(within(filters).getByRole("status")).toHaveTextContent("Showing 4 of 4");
    expect(screen.queryByRole("button", { name: "Clear filters" })).not.toBeInTheDocument();
  });

  it("retains accessible portfolio shortcuts and navigation parameters", async () => {
    window.history.replaceState({}, "", "/example-workspace/curve/initiatives/?summary=NEEDS_ATTENTION");
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    expect(screen.getByRole("button", { name: "Filter Initiatives: Needs attention" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    const active = screen.getByRole("button", { name: "Filter Initiatives: Active" });
    fireEvent.click(active);
    expect(active).toHaveAttribute("aria-pressed", "true");
    expect(within(screen.getByRole("region", { name: "Initiative filters" })).getByRole("status")).toHaveTextContent(
      "Showing 2 of 4"
    );
    fireEvent.click(active);
    expect(active).toHaveAttribute("aria-pressed", "false");
  });

  it("initializes state filtering from Home navigation", async () => {
    window.history.replaceState({}, "", "/example-workspace/curve/initiatives/?state=ALIGNING");
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    expect(screen.getByLabelText("Filter by lifecycle state")).toHaveValue("ALIGNING");
  });

  it("retains one pagination control and merges unique server records", async () => {
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(defaultHookValue.loadMore).toHaveBeenCalledOnce();
    const updated = { ...initiatives[0], title: "Updated capability overview", version: 2 };
    expect(mergeCurveInitiatives(initiatives.slice(0, 2), [updated, initiatives[2]])).toEqual([
      updated,
      initiatives[1],
      initiatives[2],
    ]);
  });

  it("shows only definition inputs first and explains required information", async () => {
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    await openCreation();
    expect(
      screen.getByText("Title, Product and outcome are required. You can refine this Draft before alignment.")
    ).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Product Approver" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Mode" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create Initiative" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Product")).toHaveValue(product.id);
    expect(screen.getByText("Keyword and business intent").closest("details")).not.toHaveAttribute("open");
  });

  it("validates and focuses the first missing definition before continuing", async () => {
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    await openCreation();
    continueToReviewers();
    expect(screen.getByText("Enter a title.")).toBeInTheDocument();
    expect(defaultHookValue.createInitiative).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByLabelText("Title")).toHaveFocus());
  });

  it("suggests a keyword, preserves manual changes and exposes invalid hidden values", async () => {
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    await openCreation();
    fillDefinition();
    fireEvent.click(screen.getByText("Keyword and business intent"));
    expect(screen.getByLabelText("Keyword")).toHaveValue("improve-delivery-confidence");
    fireEvent.change(screen.getByLabelText("Keyword"), { target: { value: "invalid_keyword" } });
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Changed title" } });
    expect(screen.getByLabelText("Keyword")).toHaveValue("invalid_keyword");
    fireEvent.click(screen.getByText("Keyword and business intent"));
    continueToReviewers();
    expect(screen.getByText("Keyword and business intent").closest("details")).toHaveAttribute("open");
    expect(screen.getByText("Use 1–50 letters, numbers, or hyphens, starting with a letter or number.")).toHaveClass(
      "text-12",
      "font-medium"
    );
    await waitFor(() => expect(screen.getByLabelText("Keyword")).toHaveFocus());
  });

  it("requires explicit reviewer selections instead of choosing people by list order", async () => {
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    await openCreation();
    fillDefinition();
    continueToReviewers();
    for (const label of ["Product Approver", "Technical Approver", "Code Approver"])
      expect(screen.getByLabelText(label)).toHaveValue("");
    expect(screen.getByText(/Assigning a reviewer does not approve any work/)).toBeInTheDocument();
    create();
    expect(defaultHookValue.createInitiative).not.toHaveBeenCalled();
    expect(screen.getAllByText("Choose an active human.")).toHaveLength(3);
    await waitFor(() => expect(screen.getByLabelText("Product Approver")).toHaveFocus());
  });

  it.each(["STANDARD", "HIGH"])("requires three different people at %s risk", async (risk) => {
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    await openCreation();
    fillDefinition();
    continueToReviewers();
    fireEvent.change(screen.getByLabelText("Risk tier"), { target: { value: risk } });
    assignReviewers(["user-1", "user-1", "user-3"]);
    create();
    expect(defaultHookValue.createInitiative).not.toHaveBeenCalled();
    expect(screen.getAllByText("Choose three distinct active humans for Standard or High risk.")).toHaveLength(3);
    expect(screen.getByLabelText("Product Approver")).toHaveAttribute("aria-invalid", "true");
    await waitFor(() => expect(screen.getByLabelText("Product Approver")).toHaveFocus());
  });

  it("permits one reviewer in all Low-risk roles but never omits a role", async () => {
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    await openCreation();
    fillDefinition();
    continueToReviewers();
    fireEvent.change(screen.getByLabelText("Risk tier"), { target: { value: "LOW" } });
    assignReviewers(["user-1", "user-1", "user-1"]);
    create();
    await waitFor(() =>
      expect(defaultHookValue.createInitiative).toHaveBeenCalledWith(
        expect.objectContaining({
          risk_tier: "LOW",
          gate_assignments: [
            { gate_type: "PRD_APPROVAL", approver_user_id: "user-1" },
            { gate_type: "PLAN_APPROVAL", approver_user_id: "user-1" },
            { gate_type: "CODE_READINESS", approver_user_id: "user-1" },
          ],
        })
      )
    );
  });

  it("creates a standalone Draft with the selected intent and all gate assignments", async () => {
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    await openCreation();
    fillDefinition();
    fireEvent.click(screen.getByText("Keyword and business intent"));
    fireEvent.change(screen.getByLabelText("Business intent"), { target: { value: "BUSINESS_IMPROVEMENT" } });
    continueToReviewers();
    assignReviewers();
    create();
    await waitFor(() =>
      expect(defaultHookValue.createInitiative).toHaveBeenCalledWith({
        product_id: product.id,
        mode: "STANDALONE",
        roadmap_item_id: null,
        keyword: "improve-delivery-confidence",
        title: "Improve delivery confidence",
        description: { schema_version: "1.0", format: "MARKDOWN", body: "Make releases easier to verify." },
        risk_tier: "STANDARD",
        business_intent: "BUSINESS_IMPROVEMENT",
        gate_assignments: [
          { gate_type: "PRD_APPROVAL", approver_user_id: "user-1" },
          { gate_type: "PLAN_APPROVAL", approver_user_id: "user-2" },
          { gate_type: "CODE_READINESS", approver_user_id: "user-3" },
        ],
      })
    );
    expect(screen.getByText("Initiative created in Draft state.")).toBeInTheDocument();
    await openCreation();
    expect(screen.getByLabelText("Title")).toHaveValue("");
  });

  it("preserves input and assignments through Back, Close and reopening", async () => {
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    await openCreation();
    fillDefinition();
    continueToReviewers();
    assignReviewers();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText("Title")).toHaveValue("Improve delivery confidence");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await openCreation();
    expect(screen.getByLabelText("Title")).toHaveValue("Improve delivery confidence");
    continueToReviewers();
    expect(screen.getByLabelText("Technical Approver")).toHaveValue("user-2");
  });

  it("returns to the top of the drawer when moving between creation steps", async () => {
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    await openCreation();
    fillDefinition();
    fireEvent.click(screen.getByText("Keyword and business intent"));
    const panel = screen.getByRole("dialog");
    panel.scrollTop = 240;
    continueToReviewers();
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Who reviews this Initiative?" })).toHaveFocus();
      expect(panel.scrollTop).toBe(0);
    });
    panel.scrollTop = 240;
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() => {
      expect(screen.getByLabelText("Title")).toHaveFocus();
      expect(panel.scrollTop).toBe(0);
    });
  });

  it("preserves a rejected submission and supports retry without duplicate requests", async () => {
    let resolve!: (success: boolean) => void;
    const createInitiative = vi.fn().mockImplementation(
      () =>
        new Promise<boolean>((done) => {
          resolve = done;
        })
    );
    useCurveInitiativesMock.mockReturnValue({ ...defaultHookValue, createInitiative });
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    await openCreation();
    fillDefinition();
    continueToReviewers();
    assignReviewers();
    create();
    create();
    expect(createInitiative).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    resolve(false);
    expect(await screen.findByText(/The Initiative could not be created/)).toBeInTheDocument();
    expect(screen.getByLabelText("Technical Approver")).toHaveValue("user-2");
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText("Title")).toHaveValue("Improve delivery confidence");
  });

  it("explains creation prerequisites and does not guess among Products", async () => {
    useCurveInitiativesMock.mockReturnValue({ ...defaultHookValue, products: [] });
    const { rerender } = render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    expect(screen.getByRole("button", { name: "New Initiative" })).toBeDisabled();
    expect(screen.getByText("An active Product is required before an Initiative can be created.")).toBeInTheDocument();
    useCurveInitiativesMock.mockReturnValue({
      ...defaultHookValue,
      products: [product, { ...product, id: "product-2", name: "Second Product" }],
    });
    rerender(<InitiativeWorkspace key="multiple" workspaceSlug="example-workspace" />);
    await openCreation();
    expect(screen.getByLabelText("Product")).toHaveValue("");
  });

  it("shows unverified readiness honestly and explains review responsibilities", async () => {
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    expect(screen.getByText("Readiness not checked")).toBeInTheDocument();
    expect(
      screen.getByText(/Document contents, access and approval decisions cannot be verified here/)
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve|Submit PRD/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Active assignment")).not.toBeInTheDocument();
    expect(screen.getByText(/Assignments identify reviewers/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("What is needed for PRD review?"));
    expect(screen.getByText(/Readiness alone does not mean approval/)).toBeVisible();
    fireEvent.click(screen.getByText("Initiative details and activity"));
    expect(screen.getByText("Links are not loaded in this view")).toBeVisible();
  });

  it("does not infer document readiness from a recorded external resource", async () => {
    const linked = { ...initiatives[0], first_external_resource_at: "2026-09-01T12:00:00Z" };
    useCurveInitiativesMock.mockReturnValue({ ...defaultHookValue, initiatives: [linked], selectedInitiative: linked });
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    expect(screen.getByText("Readiness not checked")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Initiative details and activity"));
    expect(screen.getByText("Resource recorded; document access not verified")).toBeVisible();
  });

  it("does not display expired reviewer assignments as current", async () => {
    const expired = {
      ...initiatives[0],
      gate_assignments: initiatives[0].gate_assignments.map((assignment) => ({
        ...assignment,
        valid_until: "2026-09-02T12:00:00Z",
      })),
    };
    useCurveInitiativesMock.mockReturnValue({
      ...defaultHookValue,
      initiatives: [expired],
      selectedInitiative: expired,
    });
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    expect(screen.getAllByText("No current assignment")).toHaveLength(3);
  });

  it("preserves the real Draft transition and current-version gate", async () => {
    selectDraft();
    const { rerender } = render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    expect(screen.getByText(/moves this Initiative from Draft to Aligning/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start alignment" }));
    expect(defaultHookValue.acceptRefinement).toHaveBeenCalledOnce();
    useCurveInitiativesMock.mockReturnValue({
      ...defaultHookValue,
      selectedInitiative: initiatives[1],
      selectedEtag: undefined,
    });
    rerender(<InitiativeWorkspace key="stale" workspaceSlug="example-workspace" />);
    expect(screen.getByRole("button", { name: "Start alignment" })).toBeDisabled();
  });

  it("requires a saved business intent before alignment and preserves Draft edit payload", async () => {
    const draft = { ...initiatives[1], business_intent: null };
    useCurveInitiativesMock.mockReturnValue({ ...defaultHookValue, initiatives: [draft], selectedInitiative: draft });
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    expect(screen.getByRole("button", { name: "Start alignment" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Edit Initiative" }));
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Updated confidence" } });
    fireEvent.change(screen.getByRole("combobox", { name: /Business intent/ }), {
      target: { value: "CUSTOMER_COMMITMENT" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(defaultHookValue.updateInitiativeDraft).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "Updated confidence",
          business_intent: "CUSTOMER_COMMITMENT",
          risk_tier: "HIGH",
          keyword: "rollout-confidence",
        })
      )
    );
  });

  it("keeps edits within Draft and before any external resource", async () => {
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    expect(screen.queryByRole("button", { name: "Edit Initiative" })).not.toBeInTheDocument();
  });

  it("reveals secondary actions deliberately and still requires a lifecycle reason", async () => {
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    expect(screen.getByText("Manage Initiative").closest("details")).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("Manage Initiative"));
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    fireEvent.click(screen.getByRole("button", { name: "Pause Initiative" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a reason.");
    expect(screen.getByLabelText("Reason")).toHaveFocus();
    expect(defaultHookValue.pauseInitiative).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Awaiting a dependency" } });
    fireEvent.click(screen.getByRole("button", { name: "Pause Initiative" }));
    await waitFor(() => expect(defaultHookValue.pauseInitiative).toHaveBeenCalledWith("Awaiting a dependency"));
  });

  it.each([
    ["Resume", "Resume Initiative", "resumeInitiative", initiatives[2]],
    ["Cancel", "Cancel Initiative", "cancelInitiative", initiatives[0]],
  ] as const)("retains the %s lifecycle action", async (openLabel, submitLabel, mutationName, selected) => {
    useCurveInitiativesMock.mockReturnValue({
      ...defaultHookValue,
      initiatives: [selected],
      selectedInitiative: selected,
    });
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    if (openLabel === "Cancel") fireEvent.click(screen.getByText("Manage Initiative"));
    fireEvent.click(screen.getByRole("button", { name: openLabel }));
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Current priority changed" } });
    fireEvent.click(screen.getByRole("button", { name: submitLabel }));
    await waitFor(() => expect(defaultHookValue[mutationName]).toHaveBeenCalledWith("Current priority changed"));
  });

  it("keeps cancellation terminal and preserves metadata", async () => {
    useCurveInitiativesMock.mockReturnValue({
      ...defaultHookValue,
      initiatives: [initiatives[3]],
      selectedInitiative: initiatives[3],
    });
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    expect(screen.queryByText("Manage Initiative")).not.toBeInTheDocument();
    expect(within(screen.getByLabelText("Initiative lifecycle actions")).queryAllByRole("button")).toHaveLength(0);
    fireEvent.click(screen.getByText("Initiative details and activity"));
    expect(screen.getByText("Record version")).toBeVisible();
  });

  it("retains permission, loading and empty states", async () => {
    useCurveInitiativesMock.mockReturnValue({
      ...defaultHookValue,
      initiatives: [],
      nextCursor: undefined,
      selectedInitiative: undefined,
    });
    const { rerender } = render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    expect(screen.getByText("No Initiatives yet")).toBeInTheDocument();
    useCurveInitiativesMock.mockReturnValue({ ...defaultHookValue, isPermissionLimited: true });
    rerender(<InitiativeWorkspace key="permission" workspaceSlug="example-workspace" />);
    expect(screen.getByRole("link", { name: "Return to workspace" })).toHaveAttribute("href", "/example-workspace");
    useCurveInitiativesMock.mockReturnValue({ ...defaultHookValue, isLoading: true });
    rerender(<InitiativeWorkspace key="loading" workspaceSlug="example-workspace" />);
    expect(screen.getByLabelText("Loading Initiatives")).toBeInTheDocument();
  });

  it("preserves safe conflict evidence and deliberate refresh", async () => {
    useCurveInitiativesMock.mockReturnValue({
      ...defaultHookValue,
      problem: { title: "A newer Initiative version is available", status: 412 },
      isConflict: true,
    });
    render(<InitiativeWorkspace workspaceSlug="example-workspace" />);
    fireEvent.click(screen.getByRole("button", { name: "Refresh Initiative" }));
    expect(defaultHookValue.refreshSelected).toHaveBeenCalledOnce();
    expect(toSafeCurveProblem({ status: 403, data: { title: "Private content" } }, "Failed").title).toBe(
      "Initiatives are unavailable"
    );
  });
});
