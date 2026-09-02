/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { type ReactNode } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import {
  Activity,
  Blocks,
  FileCheck2,
  Gauge,
  Layers3,
  ListTodo,
  Route,
  Settings,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useTheme } from "next-themes";

import {
  WORKSPACE_SIDEBAR_DYNAMIC_NAVIGATION_ITEMS,
  WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS,
} from "@plane/constants";
import { ScrollArea } from "@plane/propel/scrollarea";
import { cn } from "@plane/utils";
import { SidebarNavItem } from "@/components/sidebar/sidebar-navigation";
import { AppSidebarToggleButton } from "@/components/sidebar/sidebar-toggle-button";
import { SidebarItemBase } from "@/components/workspace/sidebar/sidebar-item";
import { WorkspaceMenuRoot } from "@/components/workspace/sidebar/workspace-menu-root";
import { useAppTheme } from "@/hooks/store/use-app-theme";
import { CurveSourceLink } from "./curve-source-link";

const CURVE_SIDEBAR_SKELETON_ROWS = [
  "product-overview",
  "product-initiatives",
  "delivery-execution",
  "delivery-quality",
  "work-projects",
  "work-views",
  "platform-foundation",
  "platform-settings",
];

function CurveNavSection({ label, badge, children }: { label: string; badge?: string; children: ReactNode }) {
  return (
    <section aria-labelledby={`curve-nav-${label.toLowerCase().replaceAll(" ", "-")}`}>
      <div className="mb-1 flex items-center justify-between gap-2 px-2">
        <h2
          id={`curve-nav-${label.toLowerCase().replaceAll(" ", "-")}`}
          className="text-11 font-semibold tracking-[0.08em] text-placeholder uppercase"
        >
          {label}
        </h2>
        {badge && (
          <span className="rounded-sm bg-accent-subtle px-1.5 py-0.5 text-9 font-semibold text-accent-primary">
            {badge}
          </span>
        )}
      </div>
      <div className="flex flex-col gap-0.5">{children}</div>
    </section>
  );
}

function CurveLink({
  href,
  label,
  icon,
  active,
  onNavigate,
}: {
  href: string;
  label: string;
  icon: ReactNode;
  active: boolean;
  onNavigate: () => void;
}) {
  return (
    <Link href={href} onClick={onNavigate}>
      <SidebarNavItem isActive={active}>
        <div className="flex items-center gap-1.5 py-px">
          {icon}
          <span className="text-13 leading-5 font-medium">{label}</span>
        </div>
      </SidebarNavItem>
    </Link>
  );
}

function CurveUpcomingItem({ label, icon }: { label: string; icon: ReactNode }) {
  return (
    <div
      className="flex min-h-7 items-center justify-between gap-2 rounded-sm px-2 py-1 text-tertiary opacity-65"
      aria-disabled="true"
      title="Available in a later Curve milestone"
    >
      <span className="flex items-center gap-1.5 text-13 leading-5 font-medium">
        {icon}
        {label}
      </span>
      <span className="text-9 font-medium text-placeholder">Later</span>
    </div>
  );
}

export const CurveWorkspaceSidebar = observer(function CurveWorkspaceSidebar() {
  const pathname = usePathname();
  const { workspaceSlug } = useParams();
  const slug = workspaceSlug?.toString() ?? "";
  const { resolvedTheme } = useTheme();
  const { toggleSidebar } = useAppTheme();
  const foundationHref = `/${slug}/curve`;
  const initiativesHref = `${foundationHref}/initiatives`;
  const closeMobileNavigation = () => {
    if (window.innerWidth < 768) toggleSidebar(true);
  };

  return (
    <div
      id="curve-workspace-navigation"
      className="flex h-full w-full animate-fade-in flex-col"
      aria-label="Curve workspace navigation"
    >
      <div className="flex items-center justify-between gap-3 px-5 pb-3">
        <img
          src={resolvedTheme === "dark" ? "/curve/curve-logo-dark-v1.png" : "/curve/curve-logo-light-v1.webp"}
          alt="Curve"
          className={cn("h-9 w-auto object-contain object-left", resolvedTheme === "dark" && "max-w-32")}
        />
        <AppSidebarToggleButton controlsId="curve-workspace-navigation" />
      </div>
      <div className="px-4 pb-3">
        <div className="rounded-md border border-subtle bg-layer-1 p-1">
          <WorkspaceMenuRoot variant="top-navigation" />
        </div>
      </div>

      <ScrollArea
        orientation="vertical"
        scrollType="hover"
        size="sm"
        rootClassName="size-full overflow-x-hidden overflow-y-auto"
        viewportClassName="flex h-full w-full flex-col gap-4 overflow-x-hidden overflow-y-auto px-3 pb-3"
      >
        <CurveNavSection label="Product">
          <CurveUpcomingItem label="Overview" icon={<Sparkles className="size-4" />} />
          <CurveLink
            href={initiativesHref}
            label="Initiatives"
            icon={<ListTodo className="size-4" />}
            active={pathname === initiativesHref || pathname.startsWith(`${initiativesHref}/`)}
            onNavigate={closeMobileNavigation}
          />
          <CurveUpcomingItem label="Roadmaps" icon={<Route className="size-4" />} />
        </CurveNavSection>

        <CurveNavSection label="Delivery">
          <CurveUpcomingItem label="Execution" icon={<Activity className="size-4" />} />
          <CurveUpcomingItem label="Quality" icon={<ShieldCheck className="size-4" />} />
          <CurveUpcomingItem label="Evidence" icon={<FileCheck2 className="size-4" />} />
        </CurveNavSection>

        <CurveNavSection label="Work management" badge="Plane-backed">
          <SidebarItemBase item={WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS.home} />
          <SidebarItemBase item={WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS.projects} />
          <SidebarItemBase item={WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS["your-work"]} />
          <SidebarItemBase item={WORKSPACE_SIDEBAR_DYNAMIC_NAVIGATION_ITEMS.views} additionalStaticItems={["views"]} />
          <SidebarItemBase
            item={WORKSPACE_SIDEBAR_DYNAMIC_NAVIGATION_ITEMS.analytics}
            additionalStaticItems={["analytics"]}
          />
        </CurveNavSection>

        <CurveNavSection label="Platform">
          <CurveUpcomingItem label="Integrations" icon={<Blocks className="size-4" />} />
          <CurveUpcomingItem label="Policies" icon={<Layers3 className="size-4" />} />
          <CurveLink
            href={foundationHref}
            label="Foundation status"
            icon={<Gauge className="size-4" />}
            active={pathname === foundationHref}
            onNavigate={closeMobileNavigation}
          />
          <CurveLink
            href={`/${slug}/settings`}
            label="Settings"
            icon={<Settings className="size-4" />}
            active={pathname.startsWith(`/${slug}/settings`)}
            onNavigate={closeMobileNavigation}
          />
        </CurveNavSection>
      </ScrollArea>

      <div className="border-t border-subtle px-5 py-3">
        <p className="mb-1 text-10 text-placeholder">Plane provides Curve&apos;s work-management foundation.</p>
        <CurveSourceLink />
      </div>
    </div>
  );
});

export function CurveSidebarLoading() {
  return (
    <div className="flex h-full flex-col gap-4 px-5 py-3" aria-label="Loading workspace navigation">
      <div className="h-9 w-28 animate-pulse rounded-md bg-layer-1" />
      <div className="h-10 animate-pulse rounded-md bg-layer-1" />
      <div className="mt-3 space-y-2">
        {CURVE_SIDEBAR_SKELETON_ROWS.map((row) => (
          <div key={row} className="h-7 animate-pulse rounded-sm bg-layer-1" />
        ))}
      </div>
    </div>
  );
}
