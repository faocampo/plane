// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ManualPlanClientError } from "@plane/services";
import { TechnicalReviewPanel } from "../../components/curve/initiatives/technical-review-panel";
import { definitionRef, material, record, result, status, target } from "./manual-plan-gate2-v3-fixtures";
import { payload, revision, result as draftResult, status as draftStatus } from "./manual-plan-v3-fixtures";

const api = () => ({
  preparation: vi.fn().mockRejectedValue(new Error()),
  status: vi.fn().mockResolvedValue(result(status)),
  material: vi
    .fn()
    .mockImplementation((_target, ref) =>
      Promise.resolve(result(material(ref.object_id === definitionRef.object_id ? "DEFINITION" : "RATIONALE")))
    ),
  execute: vi.fn().mockResolvedValue(result({ ...record, action: "APPROVE" })),
});
const props = (service = api()) => ({ api: service, target, viewerId: record.actor_id, initiativeVersion: 10 });
async function approve() {
  await screen.findByText("Synthetic approval evidence.");
  fireEvent.click(screen.getAllByRole("button", { name: "Record approval" }).at(-1)!);
}
describe("two-stage Technical review", () => {
  it("keeps an uncertain draft save recoverable when the window regains focus", async () => {
    const p = props();
    p.api.status.mockRejectedValue(new Error("no saved draft"));
    p.api.preparation.mockResolvedValue(
      result({ plans: [{ payload: { ...payload, expected_draft_revision: 0, definition_ref: definitionRef } }] })
    );
    const drafts = {
      status: vi
        .fn()
        .mockResolvedValue(
          draftResult({ ...draftStatus, draft_status: "ABSENT", current_revision_id: null, expected_draft_revision: 0 })
        ),
      current: vi.fn(),
      revision: vi.fn(),
      save: vi
        .fn()
        .mockRejectedValueOnce(new ManualPlanClientError("UNKNOWN"))
        .mockResolvedValueOnce(draftResult(revision)),
    };
    render(<TechnicalReviewPanel {...p} drafts={drafts} />);
    await screen.findByText("No draft saved");
    await waitFor(() => expect(screen.getByRole("button", { name: "Save prepared draft" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Save prepared draft" }));
    await screen.findByRole("button", { name: "Retry same save" });
    fireEvent.focus(window);
    expect(p.api.preparation).toHaveBeenCalledTimes(1);
    expect(drafts.status).toHaveBeenCalledTimes(1);
    for (const button of screen.getAllByRole("button", { name: "Refresh" })) expect(button).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Retry same save" }));
    await waitFor(() => expect(drafts.save).toHaveBeenCalledTimes(2));
    expect(drafts.save.mock.calls[1][1]).toEqual(drafts.save.mock.calls[0][1]);
  });
  it("loads the authorized document and note automatically, then records the exact v3 decision", async () => {
    const p = props();
    render(<TechnicalReviewPanel {...p} />);
    await screen.findByText("A synthetic user can review the local plan.");
    await approve();
    await waitFor(() => expect(p.api.execute).toHaveBeenCalledTimes(1));
    expect(p.api.execute.mock.calls[0][1]).toMatchObject({
      expectedVersion: 10,
      payload: {
        schema_version: "curve.manual-gate2.command/v3-candidate",
        action: "APPROVE",
        draft_revision_id: status.draft_revision_id,
        subject_ref: status.subject_ref,
        rationale_ref: status.rationales[0].reference,
      },
    });
  });
  it("requires matching feedback before requesting changes", async () => {
    const p = props();
    render(<TechnicalReviewPanel {...p} />);
    fireEvent.click(await screen.findByRole("button", { name: "Changes needed" }));
    expect(screen.getByText("A saved decision note is needed before you can continue.")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Send change request" }).at(-1)).toBeDisabled();
    expect(p.api.execute).not.toHaveBeenCalled();
  });
  it("records requested changes with the exact displayed feedback", async () => {
    const p = props();
    p.api.status.mockResolvedValue(
      result({
        ...status,
        allowed_actions: ["REQUEST_CHANGES"],
        rationales: [{ ...status.rationales[0], intent: "REQUEST_CHANGES" }],
      })
    );
    render(<TechnicalReviewPanel {...p} />);
    await screen.findByText("Synthetic approval evidence.");
    fireEvent.click(screen.getAllByRole("button", { name: "Send change request" }).at(-1)!);
    await waitFor(() => expect(p.api.execute).toHaveBeenCalledTimes(1));
    expect(p.api.execute.mock.calls[0][1].payload.action).toBe("REQUEST_CHANGES");
  });
  it("clears content and actions when document access fails", async () => {
    const p = props();
    p.api.material.mockRejectedValue(new Error("revoked"));
    render(<TechnicalReviewPanel {...p} />);
    await screen.findByText("Plan review unavailable");
    expect(screen.queryByRole("button", { name: "Record approval" })).not.toBeInTheDocument();
    expect(screen.queryByText("A synthetic user can review the local plan.")).not.toBeInTheDocument();
  });
  it("rejects a material from a different version", async () => {
    const p = props();
    p.api.material.mockResolvedValue(result(material("DEFINITION"), 11));
    render(<TechnicalReviewPanel {...p} />);
    await screen.findByText("Plan review unavailable");
    expect(p.api.execute).not.toHaveBeenCalled();
  });
  it("retains the exact command for recovery after an unknown outcome", async () => {
    const p = props();
    p.api.execute.mockRejectedValueOnce(new ManualPlanClientError("UNKNOWN"));
    render(<TechnicalReviewPanel {...p} />);
    await approve();
    fireEvent.click(await screen.findByRole("button", { name: "Recover decision" }));
    await waitFor(() => expect(p.api.execute).toHaveBeenCalledTimes(2));
    expect(p.api.execute.mock.calls[1][1]).toEqual(p.api.execute.mock.calls[0][1]);
  });
  it("discards late content when the viewer changes", async () => {
    const p = props();
    let resolve!: (v: ReturnType<typeof result>) => void;
    p.api.material.mockImplementationOnce(
      () =>
        new Promise((r) => {
          resolve = r;
        })
    );
    const view = render(<TechnicalReviewPanel {...p} />);
    await waitFor(() => expect(p.api.material).toHaveBeenCalled());
    view.rerender(<TechnicalReviewPanel {...p} viewerId={undefined} />);
    resolve(result(material("DEFINITION")));
    await screen.findByText("Plan review unavailable");
    expect(screen.queryByText("A synthetic user can review the local plan.")).not.toBeInTheDocument();
  });
  it("refreshes on focus and removes revoked content", async () => {
    const p = props();
    render(<TechnicalReviewPanel {...p} />);
    await screen.findByText("A synthetic user can review the local plan.");
    p.api.status.mockRejectedValue(new Error("revoked"));
    fireEvent.focus(window);
    await screen.findByText("Plan review unavailable");
    expect(screen.queryByText("Synthetic approval evidence.")).not.toBeInTheDocument();
  });
});
