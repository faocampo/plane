/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CurveExistingWorkError } from "@plane/services";
import { itemCreationRecovery } from "@/components/curve/roadmap/item-creation-recovery";
import { RoadmapItemCreateController } from "@/components/curve/roadmap/item-create-controller";
import items from "@/services/curve-roadmap-items.service";

vi.mock("@/services/curve-roadmap-items.service", () => ({
  default: { list: vi.fn(), create: vi.fn(), prepareScope: vi.fn(), reconcileCreation: vi.fn() },
}));
const service = vi.mocked(items);
const id = (n: number) => `99000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope = { productId: id(1), roadmapId: id(2) };
const reference = {
  object_id: id(7),
  digest: "sha256:" + "a".repeat(64),
  size_bytes: 80,
  media_type: "application/json",
  editor_schema_version: "curve.item-scope-markdown/v1-candidate",
};
const created = {
  resource_ref: {
    resource_type: "ROADMAP_ITEM" as const,
    resource_id: id(8),
    resource_version: 1 as const,
    initiative_ref: { resource_type: "INITIATIVE" as const, resource_id: id(9), resource_version: 1 as const },
  },
  etag: `"curve-roadmap-item:${id(8)}:v1"`,
  replayed: false,
};
function mount() {
  const onCreated = vi.fn();
  render(
    <RoadmapItemCreateController
      workspaceSlug="example"
      actorId={id(10)}
      scope={scope}
      milestones={[{ id: id(3), name: "First milestone" }]}
      features={[{ id: id(4), name: "Capability" }]}
      reviewers={[
        { id: id(5), name: "Product person" },
        { id: id(6), name: "Technical person" },
      ]}
      selectedMilestoneId={id(3)}
      onCreated={onCreated}
    />
  );
  return onCreated;
}
async function submit() {
  await waitFor(() => expect(screen.getByRole("button", { name: "Create item" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Item name"), { target: { value: "Synthetic outcome" } });
  fireEvent.change(screen.getByLabelText("Product reviewer"), { target: { value: id(5) } });
  fireEvent.change(screen.getByLabelText("Technical reviewer"), { target: { value: id(6) } });
  fireEvent.click(screen.getByRole("button", { name: "Create item" }));
}
beforeEach(() => {
  sessionStorage.clear();
  vi.resetAllMocks();
  service.list.mockResolvedValue({ results: [], next_cursor: null, roadmap_version: 2, can_create: true });
  service.prepareScope.mockResolvedValue({
    resource_ref: {
      resource_type: "PREPARED_ITEM_SCOPE",
      resource_id: id(7),
      resource_version: 1,
      scope_body: reference,
    },
    replayed: false,
  });
  service.create.mockResolvedValue(created);
});
describe("connected item form", () => {
  it("shows checking access until the server establishes creation authority", async () => {
    let finish!: (value: Awaited<ReturnType<typeof items.list>>) => void;
    service.list.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      })
    );
    mount();
    expect(screen.getByText("Checking your access…")).toBeInTheDocument();
    expect(screen.queryByText(/Creation requires current access/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Item name")).toBeDisabled();
    finish({ results: [], next_cursor: null, roadmap_version: 2, can_create: true });
    await waitFor(() => expect(screen.getByLabelText("Item name")).toBeEnabled());
    expect(screen.queryByText("Checking your access…")).not.toBeInTheDocument();
  });

  it("creates from user choices and hands off the committed Initiative once", async () => {
    const onCreated = mount();
    await submit();
    await waitFor(() => expect(onCreated).toHaveBeenCalledExactlyOnceWith(created));
    expect(service.prepareScope.mock.calls[0][2]).toEqual({ body: "Synthetic outcome" });
    expect(service.create.mock.calls[0][2]).toMatchObject({
      scope_body: reference,
      milestone_id: id(3),
      feature_id: id(4),
      initiative: {
        title: "Synthetic outcome",
        gate_assignments: [
          { gate_type: "PRD_APPROVAL", approver_user_id: id(5) },
          { gate_type: "PLAN_APPROVAL", approver_user_id: id(6) },
        ],
      },
    });
    expect(service.create.mock.calls[0][2].initiative.keyword).toMatch(/^ITEM-[a-f0-9-]{36}$/);
    expect(screen.getByRole("status")).toHaveTextContent("Item created");
  });
  it("keeps the form locked and recovers the same creation without preparing again", async () => {
    service.create.mockRejectedValueOnce(new CurveExistingWorkError("MUTATION_OUTCOME_UNKNOWN"));
    const onCreated = mount();
    await submit();
    await screen.findByRole("button", { name: "Recover creation" });
    expect(screen.getByLabelText("Item name")).toBeDisabled();
    expect(onCreated).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Recover creation" }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledExactlyOnceWith(created));
    expect(service.prepareScope).toHaveBeenCalledTimes(1);
    expect(service.create.mock.calls[1][2]).toEqual(service.create.mock.calls[0][2]);
    expect(service.create.mock.calls[1][3].idempotencyKey).toBe(service.create.mock.calls[0][3].idempotencyKey);
  });
});

it("opens a recovered receipt once without fabricating creation headers or requiring current ownership", async () => {
  itemCreationRecovery(sessionStorage, { workspaceSlug: "example", actorId: id(10), ...scope }).retain(id(30));
  service.list.mockResolvedValue({ results: [], next_cursor: null, roadmap_version: 2, can_create: false });
  const receipt = { state: "COMPLETED" as const, resource_ref: created.resource_ref };
  service.reconcileCreation.mockResolvedValue(receipt);
  const onCreated = mount();
  const recover = await screen.findByRole("button", { name: "Recover creation" });
  expect(recover).toBeEnabled();
  expect(screen.getByLabelText("Item name")).toBeDisabled();
  fireEvent.click(recover);
  await waitFor(() => expect(onCreated).toHaveBeenCalledExactlyOnceWith(receipt));
  expect(onCreated.mock.calls[0][0]).not.toHaveProperty("etag");
  expect(service.create).not.toHaveBeenCalled();
  expect(service.prepareScope).not.toHaveBeenCalled();
});
