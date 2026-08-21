/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";

import { Dialog, EDialogWidth } from "@plane/propel/dialog";

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
    <Dialog open={open} onOpenChange={onOpenChange}>
      <Dialog.Panel
        width={EDialogWidth.SM}
        className="top-0 left-0 h-dvh w-[min(20rem,calc(100vw-3rem))] max-w-none translate-x-0 translate-y-0 overflow-hidden rounded-none border-y-0 border-l-0"
      >
        <Dialog.Title className="sr-only">Curve workspace navigation</Dialog.Title>
        {children}
      </Dialog.Panel>
    </Dialog>
  );
}
