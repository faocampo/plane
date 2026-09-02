/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { InitiativeWorkspace } from "@/components/curve/initiatives/initiative-workspace";
import { PageHead } from "@/components/core/page-title";
import { useCurveWorkspaceShell } from "@/hooks/use-curve-workspace-shell";
import type { Route } from "./+types/page";

export default function CurveInitiativesPage({ params }: Route.ComponentProps) {
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
      <PageHead title="Initiatives · Curve" />
      <div className="size-full overflow-y-auto bg-surface-1">
        <InitiativeWorkspace workspaceSlug={workspaceSlug ?? shell?.workspace_slug ?? ""} />
      </div>
    </>
  );
}
