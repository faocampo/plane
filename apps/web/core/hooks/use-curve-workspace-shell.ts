/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";

import curveService from "@/services/curve.service";

export const curveWorkspaceShellKey = (workspaceSlug: string) => `CURVE_WORKSPACE_SHELL_${workspaceSlug}`;

export const useCurveWorkspaceShell = (workspaceSlug: string | undefined) => {
  const { data, error, isLoading } = useSWR(
    workspaceSlug ? curveWorkspaceShellKey(workspaceSlug) : null,
    () => curveService.retrieveWorkspaceShell(workspaceSlug ?? ""),
    {
      shouldRetryOnError: false,
      revalidateOnFocus: false,
    }
  );

  return {
    shell: data,
    isEnabled: data?.state === "EMPTY",
    isLoading,
    error,
  };
};
