/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/** An opaque receipt locator, never a saved draft, document, permission, or retry payload. */
export type ItemCreationRecovery = {
  version: 1;
  commandKey: string;
};
export type ItemRecoveryScope = {
  workspaceSlug: string;
  actorId: string;
  productId: string;
  roadmapId: string;
};
export class ItemRecoveryUnavailable extends Error {
  constructor() {
    super("Item creation recovery is unavailable");
  }
}
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
function validKey(value: unknown): value is string {
  return typeof value === "string" && uuid.test(value);
}
function storageKey(scope: ItemRecoveryScope) {
  if (
    !scope.workspaceSlug ||
    scope.workspaceSlug.length > 255 ||
    !validKey(scope.actorId) ||
    !validKey(scope.productId) ||
    !validKey(scope.roadmapId)
  )
    throw new ItemRecoveryUnavailable();
  return `curve:item-creation-recovery:v1:${JSON.stringify([
    scope.workspaceSlug,
    scope.actorId,
    scope.productId,
    scope.roadmapId,
  ])}`;
}
function parse(value: string): ItemCreationRecovery {
  try {
    if (value.length > 128) throw new Error();
    const record = JSON.parse(value) as unknown;
    if (
      !record ||
      typeof record !== "object" ||
      Array.isArray(record) ||
      Object.keys(record).sort().join(",") !== "commandKey,version" ||
      !("version" in record) ||
      record.version !== 1 ||
      !("commandKey" in record) ||
      !validKey(record.commandKey)
    )
      throw new Error();
    return { version: 1, commandKey: record.commandKey };
  } catch {
    // Corrupt state cannot prove that an earlier request did not commit.
    throw new ItemRecoveryUnavailable();
  }
}

/**
 * Tab-scoped storage survives reload. Readers must reconcile with current server
 * authority; possession of this locator grants no access and cannot replay a write.
 * Storage errors and corrupt state fail closed, preventing a fresh write from
 * silently replacing an unresolved operation. There is deliberately no expiry.
 */
export function itemCreationRecovery(
  storage: Pick<Storage, "getItem" | "setItem" | "removeItem">,
  scope: ItemRecoveryScope
) {
  const key = storageKey(scope);
  const read = (): ItemCreationRecovery | null => {
    try {
      const value = storage.getItem(key);
      return value === null ? null : parse(value);
    } catch {
      throw new ItemRecoveryUnavailable();
    }
  };
  return {
    read,
    /** Complete this durable write before submitting Item creation. */
    retain(commandKey: string) {
      if (!validKey(commandKey)) throw new ItemRecoveryUnavailable();
      const existing = read();
      if (existing && existing.commandKey !== commandKey) throw new ItemRecoveryUnavailable();
      try {
        storage.setItem(key, JSON.stringify({ version: 1, commandKey }));
        if (read()?.commandKey !== commandKey) throw new ItemRecoveryUnavailable();
      } catch {
        throw new ItemRecoveryUnavailable();
      }
    },
    /** Only a verified terminal outcome may clear its own locator. */
    settle(commandKey: string) {
      if (!validKey(commandKey)) throw new ItemRecoveryUnavailable();
      const existing = read();
      if (!existing || existing.commandKey !== commandKey) return false;
      try {
        storage.removeItem(key);
        if (read() !== null) throw new ItemRecoveryUnavailable();
        return true;
      } catch {
        throw new ItemRecoveryUnavailable();
      }
    },
  };
}
