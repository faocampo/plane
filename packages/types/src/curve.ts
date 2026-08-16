/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export type TCurveWorkspaceShellState = "EMPTY";

export interface ICurveWorkspaceShell {
  workspace_id: string;
  workspace_slug: string;
  state: TCurveWorkspaceShellState;
}
