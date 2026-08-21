/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { isEmpty } from "lodash-es";
import { observer } from "mobx-react";
// plane helpers
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
// components
import { SidebarWrapper } from "@/components/sidebar/sidebar-wrapper";
import { CurveSidebarLoading, CurveWorkspaceSidebar } from "@/components/curve/curve-workspace-sidebar";
import { SidebarFavoritesMenu } from "@/components/workspace/sidebar/favorites/favorites-menu";
import { SidebarProjectsList } from "@/components/workspace/sidebar/projects-list";
import { SidebarQuickActions } from "@/components/workspace/sidebar/quick-actions";
import { SidebarMenuItems } from "@/components/workspace/sidebar/sidebar-menu-items";
// hooks
import { useFavorite } from "@/hooks/store/use-favorite";
import { useUserPermissions } from "@/hooks/store/user";
import { useCurveWorkspaceShell } from "@/hooks/use-curve-workspace-shell";
import { useParams } from "next/navigation";

export const AppSidebar = observer(function AppSidebar() {
  const { workspaceSlug } = useParams();
  const { isEnabled: isCurveEnabled, isLoading: isCurveLoading } = useCurveWorkspaceShell(workspaceSlug?.toString());
  // store hooks
  const { allowPermissions } = useUserPermissions();
  const { groupedFavorites } = useFavorite();

  // derived values
  const canPerformWorkspaceMemberActions = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.WORKSPACE
  );

  const isFavoriteEmpty = isEmpty(groupedFavorites);

  if (isCurveLoading) return <CurveSidebarLoading />;
  if (isCurveEnabled) return <CurveWorkspaceSidebar />;

  return (
    <SidebarWrapper title="Projects" quickActions={<SidebarQuickActions />}>
      <SidebarMenuItems />
      {/* Favorites Menu */}
      {canPerformWorkspaceMemberActions && !isFavoriteEmpty && <SidebarFavoritesMenu />}
      {/* Projects List */}
      <SidebarProjectsList />
    </SidebarWrapper>
  );
});
