/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { itemCreationRecovery } from "@/components/curve/roadmap/item-creation-recovery";
import { RoadmapWorkspace } from "@/components/curve/roadmap/roadmap-workspace";
const id = (n: number) => `99000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const state = vi.hoisted(() => ({ choices: vi.fn(), products: vi.fn(), pending: false }));
vi.mock("@/hooks/store/user", () => ({ useUser: () => ({ isAuthenticated: true, data: { id: id(10) } }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/hooks/use-curve-roadmap-directory", () => ({
  useCurveRoadmapProducts: state.products,
  useCurveRoadmapOverview: () => ({
    read: { status: "READY", data: { items: [], canCreate: true } },
    refresh: vi.fn(),
  }),
}));
vi.mock("@/hooks/use-curve-roadmap-choices", () => ({ useCurveRoadmapChoices: state.choices }));
vi.mock("@/hooks/use-curve-roadmap-approvals", () => ({ useCurveRoadmapApprovals: () => ({}) }));
vi.mock("@/components/curve/roadmap/item-create-controller", () => ({
  RoadmapItemCreateController: ({ onPendingChange }: { onPendingChange: (v: boolean) => void }) => (
    <button onClick={() => onPendingChange(true)}>Simulate uncertain creation</button>
  ),
}));
beforeEach(() => {
  sessionStorage.clear();
  vi.clearAllMocks();
  Element.prototype.scrollIntoView = vi.fn();
  state.products.mockReturnValue({ read: { status: "READY", data: [{ id: id(1), name: "Example" }] } });
  state.choices.mockImplementation((_slug, _actor, _scope, _roadmap, cursors) => ({
    choices: {
      status: "READY",
      data: {
        roadmaps: {
          results: [{ id: cursors.roadmaps ? id(3) : id(2), name: "Roadmap" }],
          next_cursor: cursors.roadmaps ? null : "roadmap-1",
        },
        milestones: {
          results: [{ id: cursors.milestones ? "milestone-2" : "milestone-1", name: "Milestone" }],
          next_cursor: cursors.milestones ? null : "milestone-1",
        },
        features: { results: [], next_cursor: null },
        reviewers: [],
      },
    },
    refresh: vi.fn(),
  }));
});
async function mount() {
  const view = render(<RoadmapWorkspace workspaceSlug="example" workspaceId="workspace" />);
  fireEvent.change(screen.getByRole("combobox", { name: /^Product$/ }), { target: { value: id(1) } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Create item" })).toBeEnabled());
  return view;
}
it("resets milestone pagination when moving to another roadmap page and permits returning", async () => {
  await mount();
  fireEvent.click(screen.getByRole("button", { name: "More milestones" }));
  await screen.findByRole("button", { name: "First milestones" });
  fireEvent.click(screen.getByRole("button", { name: "More roadmaps" }));
  await screen.findByRole("button", { name: "First roadmaps" });
  expect(state.choices.mock.calls.at(-1)?.[4]).toEqual({ roadmaps: "roadmap-1", milestones: undefined });
  expect(screen.queryByRole("button", { name: "First milestones" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "First roadmaps" }));
  await screen.findByRole("button", { name: "More roadmaps" });
  expect(state.choices.mock.calls.at(-1)?.[4].roadmaps).toBeUndefined();
});
it("focuses creation and retains uncertain intent while Product access is rechecked", async () => {
  const view = await mount();
  fireEvent.click(screen.getByRole("button", { name: "Create item" }));
  expect(screen.getByRole("region", { name: "Create roadmap item" })).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: "Simulate uncertain creation" }));
  expect(screen.getByRole("combobox", { name: /^Product$/ })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Close creation" })).toBeDisabled();
  state.products.mockReturnValue({ read: { status: "UNAVAILABLE", data: null }, refresh: vi.fn() });
  view.rerender(<RoadmapWorkspace workspaceSlug="example" workspaceId="workspace" />);
  expect(screen.getByRole("button", { name: "Simulate uncertain creation" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Close creation" })).toBeDisabled();
});

it("opens the retained recovery when its Roadmap is selected after reload", async () => {
  itemCreationRecovery(sessionStorage, {
    workspaceSlug: "example",
    actorId: id(10),
    productId: id(1),
    roadmapId: id(2),
  }).retain(id(50));
  render(<RoadmapWorkspace workspaceSlug="example" workspaceId="workspace" />);
  fireEvent.change(screen.getByRole("combobox", { name: /^Product$/ }), { target: { value: id(1) } });
  await screen.findByRole("button", { name: "Simulate uncertain creation" });
  expect(screen.getByRole("region", { name: "Create roadmap item" })).toBeInTheDocument();
});
