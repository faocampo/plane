/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { useEffect, useRef } from "react";
import { useBlocker } from "react-router";
import { Button } from "@plane/propel/button";
import { useCurveProjectAssociation } from "@/hooks/use-curve-project-association";
import { curveProjectAssociationPort } from "@/services/curve-project-association.service";
import type { ProjectOutlookProject, ProjectRead } from "./project-outlook-data";
import { ProjectAssociationFlow } from "./project-association-flow";

export function ProjectAssociationNavigationGuard({ blocked }: { blocked: boolean }) {
  const blocker = useBlocker(blocked);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (blocker.state === "blocked") heading.current?.focus();
  }, [blocker.state]);
  if (blocker.state !== "blocked") return null;
  return (
    <section
      role="alert"
      aria-labelledby="association-leave-heading"
      className="my-4 rounded-lg border border-subtle bg-layer-1 p-5"
    >
      <h2 id="association-leave-heading" ref={heading} tabIndex={-1} className="text-16 font-semibold text-primary">
        The association result is still pending
      </h2>
      <p className="mt-2 text-13 leading-6 text-secondary">
        Leaving cannot cancel the server command. This page holds the request needed to recover its result.
      </p>
      <div className="mt-4 flex flex-wrap gap-3">
        <Button size="xl" onClick={() => blocker.reset()}>
          Stay and recover
        </Button>
        <Button size="xl" variant="secondary" onClick={() => blocker.proceed()}>
          Leave without confirming
        </Button>
      </div>
    </section>
  );
}

export function ProjectAssociationPanel(props: {
  workspaceSlug: string;
  workspaceId: string;
  actorId?: string;
  projects: ProjectRead<ProjectOutlookProject>;
  onAccessUnavailable: () => void;
}) {
  const flow = useCurveProjectAssociation({ ...props, port: curveProjectAssociationPort });
  return (
    <>
      <ProjectAssociationNavigationGuard blocked={flow.locked} />
      <ProjectAssociationFlow flow={flow} />
    </>
  );
}
