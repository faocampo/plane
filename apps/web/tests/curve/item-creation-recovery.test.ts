/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { beforeEach, expect, it, vi } from "vitest";
import { itemCreationRecovery, ItemRecoveryUnavailable } from "@/components/curve/roadmap/item-creation-recovery";
const id = (n: number) => `99000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope = { workspaceSlug: "example", actorId: id(1), productId: id(2), roadmapId: id(3) };
beforeEach(() => sessionStorage.clear());
it("survives a new reader with only the opaque command locator", () => {
  itemCreationRecovery(sessionStorage, scope).retain(id(4));
  expect(itemCreationRecovery(sessionStorage, scope).read()).toEqual({ version: 1, commandKey: id(4) });
  expect(JSON.parse(sessionStorage.getItem(sessionStorage.key(0)!)!)).toEqual({ version: 1, commandKey: id(4) });
});
it.each(["workspaceSlug", "actorId", "productId", "roadmapId"] as const)("isolates the %s boundary", (field) => {
  itemCreationRecovery(sessionStorage, scope).retain(id(4));
  const changed = { ...scope, [field]: field === "workspaceSlug" ? "another-example" : id(9) };
  expect(itemCreationRecovery(sessionStorage, changed).read()).toBeNull();
});
it("retains the unresolved operation and ignores a stale completion", () => {
  const journal = itemCreationRecovery(sessionStorage, scope);
  journal.retain(id(4));
  journal.retain(id(4));
  expect(() => journal.retain(id(5))).toThrow(ItemRecoveryUnavailable);
  expect(journal.settle(id(5))).toBe(false);
  expect(journal.read()?.commandKey).toBe(id(4));
  expect(journal.settle(id(4))).toBe(true);
  expect(journal.read()).toBeNull();
});
it.each([
  "broken",
  "null",
  "[]",
  '{"version":2,"commandKey":"x"}',
  JSON.stringify({ version: 1, commandKey: id(4), body: "synthetic draft" }),
])("fails closed for malformed persisted data %s", (value) => {
  const journal = itemCreationRecovery(sessionStorage, scope);
  journal.retain(id(4));
  sessionStorage.setItem(sessionStorage.key(0)!, value);
  expect(() => journal.read()).toThrow(ItemRecoveryUnavailable);
  expect(() => journal.retain(id(5))).toThrow(ItemRecoveryUnavailable);
  expect(sessionStorage.getItem(sessionStorage.key(0)!)).toBe(value);
});
it("rejects blocked storage before a locator can be considered durable", () => {
  const storage = {
    getItem: vi.fn(() => null),
    setItem: vi.fn(() => {
      throw new Error("synthetic quota");
    }),
    removeItem: vi.fn(),
  };
  expect(() => itemCreationRecovery(storage, scope).retain(id(4))).toThrow(ItemRecoveryUnavailable);
});
it("detects silently discarded writes and removals", () => {
  const storage = { getItem: vi.fn<() => string | null>(() => null), setItem: vi.fn(), removeItem: vi.fn() };
  const journal = itemCreationRecovery(storage, scope);
  expect(() => journal.retain(id(4))).toThrow(ItemRecoveryUnavailable);
  storage.getItem.mockReturnValue(JSON.stringify({ version: 1, commandKey: id(4) }));
  expect(() => journal.settle(id(4))).toThrow(ItemRecoveryUnavailable);
});
it("validates scope and command identifiers before writing", () => {
  expect(() => itemCreationRecovery(sessionStorage, { ...scope, actorId: "" })).toThrow(ItemRecoveryUnavailable);
  expect(() => itemCreationRecovery(sessionStorage, scope).retain("private body")).toThrow(ItemRecoveryUnavailable);
  expect(sessionStorage.length).toBe(0);
});
