/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { ProjectOutlook } from "@/components/curve/projects/project-outlook";
import { CurveProjectsHeader } from "@/components/curve/curve-projects-header";
import { PageHead } from "@/components/core/page-title";
import { useCurveWorkspaceShell } from "@/hooks/use-curve-workspace-shell";
import type { Route } from "./+types/page";

export default function CurveProjectsPage({ params }: Route.ComponentProps) {
  const router = useRouter();
  const workspaceSlug = params.workspaceSlug?.toString();
  const { shell, isEnabled, isLoading, isUnavailable, isPermissionLimited } = useCurveWorkspaceShell(workspaceSlug);

  useEffect(() => {
    if (!isLoading && isUnavailable && workspaceSlug) router.replace(`/${encodeURIComponent(workspaceSlug)}`);
  }, [isLoading, isUnavailable, router, workspaceSlug]);

  if (isLoading || isUnavailable) return null;
  // Reject a denied shell even if SWR still holds a previously enabled shell value.
  if (isPermissionLimited)
    return (
      <div className="mx-auto w-full max-w-6xl px-5 py-8 sm:px-8" role="status">
        <h1 className="text-20 font-semibold text-primary">Projects unavailable</h1>
        <p className="mt-3 text-14 text-secondary">Workspace access could not be verified.</p>
        <Link
          href={`/${encodeURIComponent(workspaceSlug ?? "")}`}
          className="mt-4 inline-block text-13 text-link-primary underline"
        >
          Return to workspace
        </Link>
      </div>
    );
  if (!isEnabled || !shell || !workspaceSlug) return null;

  return (
    <>
      <PageHead title="Projects · Curve" />
      <CurveProjectsHeader />
      <div className="size-full overflow-y-auto bg-surface-1">
        <ProjectOutlook workspaceSlug={workspaceSlug} workspaceId={shell.workspace_id} />
      </div>
    </>
  );
}
