/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React, { useState } from "react";
import { observer } from "mobx-react";
import { HelpCircle, User } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { PageIcon } from "@plane/propel/icons";
// ui
import { CustomMenu } from "@plane/ui";
// components
import { ProductUpdatesModal } from "@/components/global";
import { AppSidebarItem } from "@/components/sidebar/sidebar-item";
import { PlaneVersionNumber } from "@/components/global/version-number";
import { CurveSourceLink } from "@/components/curve/curve-source-link";
// hooks
import { usePowerK } from "@/hooks/store/use-power-k";

export const HelpMenuRoot = observer(function HelpMenuRoot({
  showCurveAttribution = false,
}: {
  showCurveAttribution?: boolean;
}) {
  // store hooks
  const { t } = useTranslation();
  const { toggleShortcutsListModal } = usePowerK();
  // states
  const [isNeedHelpOpen, setIsNeedHelpOpen] = useState(false);
  const [isProductUpdatesModalOpen, setProductUpdatesModalOpen] = useState(false);

  return (
    <>
      <ProductUpdatesModal isOpen={isProductUpdatesModalOpen} handleClose={() => setProductUpdatesModalOpen(false)} />

      <CustomMenu
        customButton={
          <AppSidebarItem
            variant="button"
            item={{
              icon: <HelpCircle className="size-5" />,
              isActive: isNeedHelpOpen,
            }}
          />
        }
        // customButtonClassName="relative grid place-items-center rounded-md p-1.5 outline-none"
        menuButtonOnClick={() => !isNeedHelpOpen && setIsNeedHelpOpen(true)}
        onMenuClose={() => setIsNeedHelpOpen(false)}
        placement="bottom-end"
        maxHeight="lg"
        closeOnSelect
      >
        <CustomMenu.MenuItem onClick={() => window.open("https://go.plane.so/p-docs", "_blank")}>
          <div className="flex items-center gap-x-2 rounded-sm text-11">
            <PageIcon className="h-3.5 w-3.5 text-secondary" height={14} width={14} />
            <span className="text-11">{t("documentation")}</span>
          </div>
        </CustomMenu.MenuItem>
        <CustomMenu.MenuItem onClick={() => window.open("mailto:sales@plane.so", "_blank")}>
          <div className="flex items-center gap-x-2 rounded-sm text-11">
            <User className="h-3.5 w-3.5 text-secondary" size={14} />
            <span className="text-11">{t("contact_sales")}</span>
          </div>
        </CustomMenu.MenuItem>
        <div className="my-1 border-t border-subtle" />
        <CustomMenu.MenuItem>
          <button
            type="button"
            onClick={() => toggleShortcutsListModal(true)}
            className="justify-sbg-layer-211 flex w-full items-center hover:bg-layer-1"
          >
            <span className="text-11">{t("keyboard_shortcuts")}</span>
          </button>
        </CustomMenu.MenuItem>
        <CustomMenu.MenuItem>
          <button
            type="button"
            onClick={() => setProductUpdatesModalOpen(true)}
            className="justify-sbg-layer-211 flex w-full items-center hover:bg-layer-1"
          >
            <span className="text-11">{t("whats_new")}</span>
          </button>
        </CustomMenu.MenuItem>
        <CustomMenu.MenuItem onClick={() => window.open("https://forum.plane.so", "_blank", "noopener,noreferrer")}>
          <div className="flex items-center gap-x-2 rounded-sm text-11">
            <span className="text-11">Forum</span>
          </div>
        </CustomMenu.MenuItem>
        <div className="mt-1 border-t border-subtle px-1 pt-2 text-11 text-secondary">
          <PlaneVersionNumber />
        </div>
        {showCurveAttribution && (
          <div className="mt-1 space-y-2 border-t border-subtle px-1 pt-2 text-11 text-secondary">
            <p>Plane powers Curve&apos;s work-management capabilities.</p>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <a
                href="https://github.com/makeplane/plane"
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-link-primary underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-accent-strong focus-visible:outline-none"
              >
                Plane source (AGPL)
              </a>
              <CurveSourceLink compact />
            </div>
          </div>
        )}
      </CustomMenu>
    </>
  );
});
