/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useUser } from "@/hooks/store/user";
import { useCurveProjects } from "@/hooks/use-curve-projects";
import { ProjectAssociationPanel } from "./project-association-panel";
import { ProjectOutlookView } from "./project-outlook-view";
export { ProjectOutlookView } from "./project-outlook-view";
export type { ProjectOutlookViewProps } from "./project-outlook-view";

export const ProjectOutlook = observer(function ProjectOutlook({
  workspaceSlug,
  workspaceId,
}: {
  workspaceSlug: string;
  workspaceId?: string;
}) {
  const { data, isAuthenticated } = useUser();
  const actorId = isAuthenticated ? data?.id : undefined;
  const outlook = useCurveProjects(workspaceSlug, actorId);
  // Remount local search state synchronously when the authenticated account or workspace changes.
  return (
    <ProjectOutlookView
      key={JSON.stringify([workspaceSlug, actorId ?? null])}
      workspaceSlug={workspaceSlug}
      {...outlook}
      associationPanel={
        workspaceId ? (
          <ProjectAssociationPanel
            key={JSON.stringify([workspaceSlug, workspaceId, actorId ?? null])}
            workspaceSlug={workspaceSlug}
            workspaceId={workspaceId}
            actorId={actorId}
            projects={outlook.projects}
            onAccessUnavailable={outlook.refresh}
          />
        ) : undefined
      }
    />
  );
});
