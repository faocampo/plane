/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { CurveFoundationHeader } from "@/components/curve/curve-foundation-header";
import { CurveFoundationStatus, CurvePermissionLimited } from "@/components/curve/curve-foundation-status";
import { PageHead } from "@/components/core/page-title";
import { useCurveWorkspaceShell } from "@/hooks/use-curve-workspace-shell";
import type { Route } from "./+types/page";

export default function CurveWorkspacePage({ params }: Route.ComponentProps) {
  const router = useRouter();
  const workspaceSlug = params.workspaceSlug?.toString();
  const { shell, isEnabled, isLoading, isUnavailable, isPermissionLimited } = useCurveWorkspaceShell(workspaceSlug);

  useEffect(() => {
    if (!isLoading && isUnavailable && workspaceSlug) router.replace(`/${workspaceSlug}`);
  }, [isLoading, isUnavailable, router, workspaceSlug]);

  if (isLoading || isUnavailable) return null;

  if ((!isEnabled || !shell) && !isPermissionLimited) return null;

  return (
    <>
      <PageHead title="Foundation status · Curve" />
      <CurveFoundationHeader />
      <div className="size-full overflow-y-auto bg-surface-1">
        {isPermissionLimited || !shell ? (
          <CurvePermissionLimited workspaceSlug={workspaceSlug ?? ""} />
        ) : (
          <CurveFoundationStatus
            workspaceSlug={workspaceSlug ?? shell.workspace_slug}
            workspaceId={shell.workspace_id}
          />
        )}
      </div>
    </>
  );
}
