/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { useParams, usePathname } from "next/navigation";
import { SIDEBAR_WIDTH } from "@plane/constants";
import { useLocalStorage } from "@plane/hooks";
// components
import { ResizableSidebar } from "@/components/sidebar/resizable-sidebar";
import { CurveMobileNavigation } from "@/components/curve/curve-mobile-navigation";
// hooks
import { useAppTheme } from "@/hooks/store/use-app-theme";
import { useCurveWorkspaceShell } from "@/hooks/use-curve-workspace-shell";
import useSize from "@/hooks/use-window-size";
// local imports
import { ExtendedAppSidebar } from "./extended-sidebar";
import { AppSidebar } from "./sidebar";

export const ProjectAppSidebar = observer(function ProjectAppSidebar() {
  // store hooks
  const {
    sidebarCollapsed,
    toggleSidebar,
    sidebarPeek,
    toggleSidebarPeek,
    isExtendedSidebarOpened,
    isAnySidebarDropdownOpen,
  } = useAppTheme();
  const { storedValue, setValue } = useLocalStorage("sidebarWidth", SIDEBAR_WIDTH);
  // states
  const [sidebarWidth, setSidebarWidth] = useState<number>(storedValue ?? SIDEBAR_WIDTH);
  // routes
  const { workspaceSlug } = useParams();
  const pathname = usePathname();
  const { isEnabled: isCurveEnabled } = useCurveWorkspaceShell(workspaceSlug?.toString());
  const windowSize = useSize();
  const isCurveMobile = isCurveEnabled && windowSize[0] < 768;
  const wasCurveMobile = useRef(false);
  // derived values
  const isAnyExtendedSidebarOpen = isExtendedSidebarOpened;

  const isNotificationsPath = pathname.includes(`/${workspaceSlug}/notifications`);

  // handlers
  const handleWidthChange = (width: number) => setValue(width);

  useEffect(() => {
    if (isCurveMobile && !wasCurveMobile.current) toggleSidebar(true);
    wasCurveMobile.current = isCurveMobile;
  }, [isCurveMobile, toggleSidebar]);

  if (isNotificationsPath) return null;

  if (isCurveMobile) {
    return (
      <CurveMobileNavigation open={sidebarCollapsed === false} onOpenChange={(open) => toggleSidebar(!open)}>
        <AppSidebar />
      </CurveMobileNavigation>
    );
  }

  return (
    <>
      <ResizableSidebar
        showPeek={sidebarPeek}
        defaultWidth={storedValue ?? 250}
        width={sidebarWidth}
        setWidth={setSidebarWidth}
        defaultCollapsed={sidebarCollapsed}
        peekDuration={1500}
        onWidthChange={handleWidthChange}
        onCollapsedChange={toggleSidebar}
        isCollapsed={sidebarCollapsed}
        toggleCollapsed={toggleSidebar}
        togglePeek={toggleSidebarPeek}
        extendedSidebar={
          <>
            <ExtendedAppSidebar />
          </>
        }
        isAnyExtendedSidebarExpanded={isAnyExtendedSidebarOpen}
        isAnySidebarDropdownOpen={isAnySidebarDropdownOpen}
      >
        <AppSidebar />
      </ResizableSidebar>
    </>
  );
});
