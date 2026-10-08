// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
/** Fail closed if a review accidentally mounts a source-connected container. */
export function useUser(): never {
  throw new Error("The synthetic review cannot read an account");
}
export function useCurveProjects(): never {
  throw new Error("The synthetic review cannot read source records");
}
