/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
import Link from "next/link";
import useSWR from "swr";
import { ArrowRight, Bell, CircleAlert, GitPullRequestArrow, ListChecks } from "lucide-react";

import type { ICurveInitiative, TOverviewStatsWidgetResponse } from "@plane/types";
import { cn } from "@plane/utils";
import { useWorkspaceNotifications } from "@/hooks/store/notifications";
import curveService from "@/services/curve.service";
import { DashboardService } from "@/services/dashboard.service";

const dashboardService = new DashboardService();

type TActionRowProps = {
  count?: number;
  description: string;
  href: string;
  icon: ReactNode;
  label: string;
  loading?: boolean;
  tone?: "attention" | "default";
  unavailable?: boolean;
};

function ActionRow({
  count,
  description,
  href,
  icon,
  label,
  loading = false,
  tone = "default",
  unavailable = false,
}: TActionRowProps) {
  const countLabel = loading ? "—" : unavailable || count === undefined ? "Unavailable" : count;

  return (
    <Link
      href={href}
      className="group flex min-h-20 items-center gap-3 border-b border-subtle px-4 py-3 outline-none last:border-b-0 hover:bg-layer-1 focus-visible:ring-2 focus-visible:ring-accent-strong focus-visible:ring-inset"
    >
      <span
        className={cn(
          "shrink-0 text-secondary",
          tone === "attention" && count !== undefined && count > 0 && "text-warning-primary"
        )}
        aria-hidden="true"
      >
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="text-14 font-semibold text-primary">{countLabel}</span>
          <span className="text-12 font-medium text-primary">{label}</span>
        </span>
        <span className="mt-1 block text-11 leading-5 text-secondary">{description}</span>
      </span>
      <ArrowRight className="size-4 shrink-0 text-placeholder transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
    </Link>
  );
}

export type TCurveHomeOverviewViewProps = {
  activeInitiatives?: number;
  aligningInitiatives?: number;
  assignedWorkItems?: number;
  completedWorkItems?: number;
  isInitiativesLoading?: boolean;
  isInitiativesUnavailable?: boolean;
  isNotificationsLoading?: boolean;
  isNotificationsUnavailable?: boolean;
  isWorkLoading?: boolean;
  isWorkUnavailable?: boolean;
  needsAttention?: number;
  pendingWorkItems?: number;
  unreadMentions?: number;
  unreadNotifications?: number;
  workspaceSlug: string;
};

export function CurveHomeOverviewView({
  activeInitiatives,
  aligningInitiatives,
  assignedWorkItems,
  completedWorkItems,
  isInitiativesLoading = false,
  isInitiativesUnavailable = false,
  isNotificationsLoading = false,
  isNotificationsUnavailable = false,
  isWorkLoading = false,
  isWorkUnavailable = false,
  needsAttention,
  pendingWorkItems,
  unreadMentions,
  unreadNotifications,
  workspaceSlug,
}: TCurveHomeOverviewViewProps) {
  const initiativesHref = `/${workspaceSlug}/curve/initiatives/`;
  const initiativesAttentionHref = `${initiativesHref}?summary=NEEDS_ATTENTION`;
  const initiativesAligningHref = `${initiativesHref}?state=ALIGNING`;
  const notificationsHref = `/${workspaceSlug}/notifications/`;
  const myWorkHref = `/${workspaceSlug}/profile/`;
  const notificationCount = unreadMentions && unreadMentions > 0 ? unreadMentions : unreadNotifications;
  const notificationLabel =
    unreadMentions && unreadMentions > 0
      ? unreadMentions === 1
        ? "mention waiting"
        : "mentions waiting"
      : unreadNotifications === 1
        ? "unread update"
        : "unread updates";

  return (
    <section className="pt-7" aria-labelledby="curve-home-overview-title">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <h1
            id="curve-home-overview-title"
            className="text-24 leading-8 font-semibold tracking-[-0.02em] text-primary"
          >
            Your control room
          </h1>
          <p className="mt-1 max-w-2xl text-13 leading-6 text-secondary">
            Cross-project decisions, exceptions, and handoffs that need your attention.
          </p>
        </div>
        <Link
          href={myWorkHref}
          className="inline-flex min-h-9 items-center gap-2 self-start rounded-md px-2.5 text-12 font-medium text-accent-primary outline-none hover:bg-accent-subtle focus-visible:ring-2 focus-visible:ring-accent-strong sm:self-auto"
        >
          Open My work
          <ArrowRight className="size-4" aria-hidden="true" />
        </Link>
      </div>

      <div className="mt-5 grid overflow-hidden rounded-xl border border-subtle bg-surface-1 shadow-raised-100 lg:grid-cols-[minmax(0,1.35fr)_minmax(18rem,0.65fr)]">
        <section
          className="min-w-0 border-b border-subtle lg:border-r lg:border-b-0"
          aria-labelledby="curve-home-action-title"
        >
          <div className="border-b border-subtle px-4 py-3">
            <h2 id="curve-home-action-title" className="text-12 font-semibold text-primary">
              Attention queue
            </h2>
            <p className="mt-0.5 text-10 text-secondary">Start with exceptions and approval preparation.</p>
          </div>
          <ActionRow
            count={needsAttention}
            description="High-risk active Initiatives that deserve an explicit check."
            href={initiativesAttentionHref}
            icon={<CircleAlert className="size-5" />}
            label={needsAttention === 1 ? "Initiative needs attention" : "Initiatives need attention"}
            loading={isInitiativesLoading}
            tone="attention"
            unavailable={isInitiativesUnavailable}
          />
          <ActionRow
            count={aligningInitiatives}
            description="Complete their Idea Brief and PRD before submitting them for review."
            href={initiativesAligningHref}
            icon={<GitPullRequestArrow className="size-5" />}
            label={aligningInitiatives === 1 ? "Initiative in alignment" : "Initiatives in alignment"}
            loading={isInitiativesLoading}
            unavailable={isInitiativesUnavailable}
          />
          <ActionRow
            count={notificationCount}
            description="Open the Inbox for the full notification and mention history."
            href={notificationsHref}
            icon={<Bell className="size-5" />}
            label={notificationLabel}
            loading={isNotificationsLoading}
            unavailable={isNotificationsUnavailable}
          />
        </section>

        <aside className="min-w-0 bg-layer-1 px-4 py-4" aria-labelledby="curve-home-work-pulse-title">
          <div className="flex items-center gap-2">
            <ListChecks className="size-4 text-secondary" aria-hidden="true" />
            <h2 id="curve-home-work-pulse-title" className="text-12 font-semibold text-primary">
              Work pulse
            </h2>
          </div>
          <p className="mt-1 text-10 leading-5 text-secondary">
            A compact health check; task management stays in My work.
          </p>
          <dl className="mt-5 space-y-3">
            <div className="flex items-baseline justify-between gap-4 border-b border-subtle pb-3">
              <dt className="text-11 text-secondary">Assigned</dt>
              <dd className="text-16 font-semibold text-primary tabular-nums">
                {isWorkLoading
                  ? "—"
                  : isWorkUnavailable || assignedWorkItems === undefined
                    ? "Unavailable"
                    : assignedWorkItems}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4 border-b border-subtle pb-3">
              <dt className="text-11 text-secondary">Pending</dt>
              <dd className="text-16 font-semibold text-primary tabular-nums">
                {isWorkLoading
                  ? "—"
                  : isWorkUnavailable || pendingWorkItems === undefined
                    ? "Unavailable"
                    : pendingWorkItems}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-11 text-secondary">Completed</dt>
              <dd
                className={cn(
                  "text-16 font-semibold tabular-nums",
                  !isWorkLoading && !isWorkUnavailable && completedWorkItems !== undefined
                    ? "text-success-primary"
                    : "text-secondary"
                )}
              >
                {isWorkLoading
                  ? "—"
                  : isWorkUnavailable || completedWorkItems === undefined
                    ? "Unavailable"
                    : completedWorkItems}
              </dd>
            </div>
          </dl>
          <div className="mt-5 border-t border-subtle pt-4">
            <div className="flex items-baseline justify-between gap-4">
              <span className="text-11 text-secondary">
                {activeInitiatives === 1 ? "Active Initiative" : "Active Initiatives"}
              </span>
              <span className="text-12 font-semibold text-primary tabular-nums">
                {isInitiativesLoading
                  ? "—"
                  : isInitiativesUnavailable || activeInitiatives === undefined
                    ? "Unavailable"
                    : activeInitiatives}
              </span>
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}

async function loadAllInitiatives(workspaceSlug: string): Promise<ICurveInitiative[]> {
  const initiatives: ICurveInitiative[] = [];
  const seenIds = new Set<string>();
  const seenCursors = new Set<string>();
  let cursor: string | undefined;

  do {
    // Cursor pages must be requested in server order to produce workspace-wide Home totals.
    // oxlint-disable-next-line no-await-in-loop
    const page = await curveService.listInitiatives(workspaceSlug, { pageSize: 100, cursor });
    for (const initiative of page.results) {
      if (!seenIds.has(initiative.id)) initiatives.push(initiative);
      seenIds.add(initiative.id);
    }

    const nextCursor = page.next_cursor ?? undefined;
    if (nextCursor && seenCursors.has(nextCursor)) throw new Error("The Initiative cursor did not advance");
    if (nextCursor) seenCursors.add(nextCursor);
    cursor = nextCursor;
  } while (cursor);

  return initiatives;
}

export function CurveHomeOverview({ workspaceSlug }: { workspaceSlug: string }) {
  const { getUnreadNotificationsCount } = useWorkspaceNotifications();
  const {
    data: initiatives,
    error: initiativesError,
    isLoading: isInitiativesLoading,
  } = useSWR<ICurveInitiative[]>(
    workspaceSlug ? `CURVE_HOME_INITIATIVES_${workspaceSlug}` : null,
    () => loadAllInitiatives(workspaceSlug),
    { revalidateOnFocus: true, revalidateOnReconnect: true }
  );
  const {
    data: workStats,
    error: workStatsError,
    isLoading: isWorkLoading,
  } = useSWR<TOverviewStatsWidgetResponse>(
    workspaceSlug ? `CURVE_HOME_WORK_PULSE_${workspaceSlug}` : null,
    async () => {
      const dashboard = await dashboardService.getHomeDashboardWidgets(workspaceSlug);
      const stats = await dashboardService.getWidgetStats(workspaceSlug, dashboard.dashboard.id, {
        widget_key: "overview_stats",
      });
      if (!("assigned_issues_count" in stats)) throw new Error("The work overview response is unavailable");
      return stats;
    },
    { revalidateOnFocus: true, revalidateOnReconnect: true }
  );

  const {
    data: unreadNotifications,
    error: notificationsError,
    isLoading: isNotificationsLoading,
  } = useSWR(
    workspaceSlug ? "WORKSPACE_UNREAD_NOTIFICATION_COUNT" : null,
    () => getUnreadNotificationsCount(workspaceSlug),
    { revalidateOnFocus: true, revalidateOnReconnect: true }
  );

  const activeInitiatives = initiatives?.filter(({ state }) => state === "DRAFT" || state === "ALIGNING").length;
  const aligningInitiatives = initiatives?.filter(({ state }) => state === "ALIGNING").length;
  const needsAttention = initiatives?.filter(
    ({ risk_tier, state }) => risk_tier === "HIGH" && (state === "DRAFT" || state === "ALIGNING")
  ).length;

  return (
    <CurveHomeOverviewView
      workspaceSlug={workspaceSlug}
      activeInitiatives={activeInitiatives}
      aligningInitiatives={aligningInitiatives}
      needsAttention={needsAttention}
      unreadMentions={unreadNotifications?.mention_unread_notifications_count}
      unreadNotifications={unreadNotifications?.total_unread_notifications_count}
      assignedWorkItems={workStats?.assigned_issues_count}
      pendingWorkItems={workStats?.pending_issues_count}
      completedWorkItems={workStats?.completed_issues_count}
      isInitiativesLoading={isInitiativesLoading}
      isInitiativesUnavailable={!!initiativesError || (!isInitiativesLoading && !initiatives)}
      isNotificationsLoading={isNotificationsLoading}
      isNotificationsUnavailable={!!notificationsError || (!isNotificationsLoading && !unreadNotifications)}
      isWorkLoading={isWorkLoading}
      isWorkUnavailable={!!workStatsError || (!isWorkLoading && !workStats)}
    />
  );
}
