/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";

import { Drawer, DrawerPanel, DrawerTitle } from "@makeplane/propel/components/drawer";

export function CurveMobileNavigation({
  open,
  onOpenChange,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
}) {
  return (
    <Drawer open={open} onOpenChange={onOpenChange} modal swipeDirection="left">
      <DrawerPanel side="start" size="sm" variant="overlay" backdrop aria-modal="true">
        <div className="sr-only">
          <DrawerTitle>Curve workspace navigation</DrawerTitle>
        </div>
        {children}
      </DrawerPanel>
    </Drawer>
  );
}
