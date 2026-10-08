/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { CurveExistingWorkError } from "./existing-work-validation";
import type { CurveExistingWorkErrorCode } from "./existing-work-validation";
export type CurveExistingWorkReadState<T> =
  | { status: "IDLE" | "LOADING"; data: null }
  | { status: "READY"; data: T }
  | { status: "UNAVAILABLE"; data: null; code: CurveExistingWorkErrorCode };
/**
 * Ephemeral latest-read slot for a future authenticated screen. Use only decoded service reads.
 * Clear on navigation/logout/access change. Every refresh clears the old protected projection.
 * No command input, persisted cache, permission, rationale, or raw error is stored here.
 */
export class CurveExistingWorkReadSlot<T> {
  private generation = 0;
  private controller?: AbortController;
  private value: CurveExistingWorkReadState<T> = { status: "IDLE", data: null };
  get snapshot(): CurveExistingWorkReadState<T> {
    return structuredClone(this.value);
  }
  clear(): void {
    this.generation += 1;
    this.controller?.abort();
    this.controller = undefined;
    this.value = { status: "IDLE", data: null };
  }
  async load(read: (signal: AbortSignal) => Promise<T>): Promise<CurveExistingWorkReadState<T> | null> {
    this.clear();
    const generation = this.generation;
    const controller = new AbortController();
    this.controller = controller;
    this.value = { status: "LOADING", data: null };
    try {
      const data = await read(controller.signal);
      if (generation !== this.generation || controller.signal.aborted) return null;
      this.value = { status: "READY", data: structuredClone(data) };
    } catch (error) {
      if (generation !== this.generation || controller.signal.aborted) return null;
      this.value = {
        status: "UNAVAILABLE",
        data: null,
        code: error instanceof CurveExistingWorkError ? error.code : "TRANSPORT",
      };
    } finally {
      if (generation === this.generation) this.controller = undefined;
    }
    return this.snapshot;
  }
}
