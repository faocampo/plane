/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { CurveEmptyState } from "@/components/curve/curve-empty-state";
import { PageHead } from "@/components/core/page-title";
import { useCurveWorkspaceShell } from "@/hooks/use-curve-workspace-shell";
import type { Route } from "./+types/page";

export default function CurveWorkspacePage({ params }: Route.ComponentProps) {
  const router = useRouter();
  const workspaceSlug = params.workspaceSlug?.toString();
  const { isEnabled, isLoading } = useCurveWorkspaceShell(workspaceSlug);

  useEffect(() => {
    if (!isLoading && !isEnabled && workspaceSlug) router.replace(`/${workspaceSlug}`);
  }, [isEnabled, isLoading, router, workspaceSlug]);

  if (isLoading || !isEnabled) return null;

  return (
    <>
      <PageHead title="Curve" />
      <CurveEmptyState />
    </>
  );
}
