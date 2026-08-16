/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { Sparkles } from "lucide-react";

import { SidebarNavItem } from "@/components/sidebar/sidebar-navigation";
import { useCurveWorkspaceShell } from "@/hooks/use-curve-workspace-shell";
import { shouldShowCurveNavigation } from "./curve-navigation";

export function CurveSidebarItem() {
  const pathname = usePathname();
  const { workspaceSlug } = useParams();
  const slug = workspaceSlug?.toString();
  const { isEnabled, isLoading } = useCurveWorkspaceShell(slug);

  if (!slug || !shouldShowCurveNavigation(isEnabled, isLoading)) return null;

  const href = `/${slug}/curve`;

  return (
    <Link href={href}>
      <SidebarNavItem isActive={pathname === href || pathname.startsWith(`${href}/`)}>
        <div className="flex items-center gap-1.5 py-[1px]">
          <Sparkles className="size-4 flex-shrink-0" aria-hidden="true" />
          <p className="text-13 leading-5 font-medium">Curve</p>
        </div>
      </SidebarNavItem>
    </Link>
  );
}
