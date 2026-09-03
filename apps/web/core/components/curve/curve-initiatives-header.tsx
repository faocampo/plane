/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";

import { Breadcrumbs, Header } from "@plane/ui";
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
import { AppSidebarToggleButton } from "@/components/sidebar/sidebar-toggle-button";
import { useAppTheme } from "@/hooks/store/use-app-theme";

export const CurveInitiativesHeader = observer(function CurveInitiativesHeader() {
  const { sidebarCollapsed } = useAppTheme();

  return (
    <Header>
      <Header.LeftItem>
        {sidebarCollapsed && <AppSidebarToggleButton controlsId="curve-workspace-navigation" />}
        <Breadcrumbs>
          <Breadcrumbs.Item component={<BreadcrumbLink label="Product" />} />
          <Breadcrumbs.Item component={<BreadcrumbLink label="Initiatives" isLast />} />
        </Breadcrumbs>
      </Header.LeftItem>
    </Header>
  );
});
