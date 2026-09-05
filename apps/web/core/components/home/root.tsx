/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { ContentWrapper } from "@plane/ui";
// hooks
import { useHome } from "@/hooks/store/use-home";
import { useUserProfile, useUser } from "@/hooks/store/user";
// plane web imports
import { TourRoot } from "@/components/onboarding/tour/root";
import { useCurveWorkspaceShell } from "@/hooks/use-curve-workspace-shell";
// local imports
import { CurveHomeOverview } from "./curve-home-overview";
import { DashboardWidgets } from "./home-dashboard-widgets";
import { UserGreetingsView } from "./user-greetings";
import { HomePeekOverviewsRoot } from "../issues/peek-overview/peek-overviews";

export const WorkspaceHomeView = observer(function WorkspaceHomeView() {
  // store hooks
  const { workspaceSlug } = useParams();
  const { data: currentUser } = useUser();
  const { data: currentUserProfile, updateTourCompleted } = useUserProfile();
  const { fetchWidgets } = useHome();
  const slug = workspaceSlug?.toString();
  const { isEnabled: isCurveShell } = useCurveWorkspaceShell(slug);
  const [isClientReady, setIsClientReady] = useState(false);

  useEffect(() => setIsClientReady(true), []);

  const showCurveHome = isClientReady && isCurveShell;

  useSWR(
    workspaceSlug ? `HOME_DASHBOARD_WIDGETS_${workspaceSlug}` : null,
    workspaceSlug ? () => fetchWidgets(workspaceSlug?.toString()) : null,
    {
      revalidateIfStale: true,
      revalidateOnFocus: false,
      revalidateOnReconnect: true,
    }
  );

  const handleTourCompleted = async () => {
    try {
      await updateTourCompleted();
    } catch (error) {
      console.error("Error updating tour completed", error);
    }
  };

  // TODO: refactor loader implementation
  return (
    <>
      {currentUserProfile && !currentUserProfile.is_tour_completed && (
        <div className="fixed top-0 left-0 z-20 grid h-full w-full place-items-center overflow-y-auto bg-backdrop transition-opacity">
          <TourRoot onComplete={handleTourCompleted} />
        </div>
      )}
      <>
        <HomePeekOverviewsRoot />
        <ContentWrapper className="mx-auto scrollbar-hide gap-6 bg-surface-1 px-page-x">
          <div className={showCurveHome ? "mx-auto w-full max-w-6xl" : "mx-auto w-full max-w-[800px]"}>
            {showCurveHome && slug ? (
              <CurveHomeOverview workspaceSlug={slug} />
            ) : (
              currentUser && <UserGreetingsView user={currentUser} />
            )}
            <DashboardWidgets curveMode={showCurveHome} />
          </div>
        </ContentWrapper>
      </>
    </>
  );
});
