/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { PanelLeft } from "lucide-react";
// hooks
import { useAppTheme } from "@/hooks/store/use-app-theme";
import { IconButton } from "@plane/propel/icon-button";

export const AppSidebarToggleButton = observer(function AppSidebarToggleButton({
  controlsId = "main-sidebar",
}: {
  controlsId?: string;
}) {
  // store hooks
  const { sidebarCollapsed, toggleSidebar, sidebarPeek, toggleSidebarPeek } = useAppTheme();

  return (
    <IconButton
      aria-label="Toggle workspace navigation"
      aria-controls={controlsId}
      aria-expanded={sidebarCollapsed === false}
      size="base"
      variant="ghost"
      icon={PanelLeft}
      onClick={() => {
        if (sidebarPeek) toggleSidebarPeek(false);
        toggleSidebar();
      }}
    />
  );
});
