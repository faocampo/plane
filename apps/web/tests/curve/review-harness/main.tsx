/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { ProjectAssociationFlow } from "@/components/curve/projects/project-association-flow";
import { ProjectOutlookView } from "@/components/curve/projects/project-outlook-view";
import { useCurveProjectAssociation } from "@/hooks/use-curve-project-association";
import type { AssociationPort } from "@/components/curve/projects/project-association-model";
import type { ProjectOutlookProject } from "@/components/curve/projects/project-outlook-data";
import type { CurveProjectAssociation } from "@plane/types";
import logo from "../../../public/curve/curve-logo-light-v1.webp?url";
// oxlint-disable-next-line import/no-unassigned-import -- load the incumbent local font.
import "@fontsource-variable/inter";
// oxlint-disable-next-line import/no-unassigned-import -- load the incumbent local mono font.
import "@fontsource/ibm-plex-mono";
// oxlint-disable-next-line import/no-unassigned-import -- use the real application tokens and styles.
import "../../../styles/globals.css";

// This file is a standalone review entry; production routes never import it.
const workspace = "10000000-0000-4000-8000-000000000001";
const product = "30000000-0000-4000-8000-000000000001";
const installation = "40000000-0000-4000-8000-000000000001";
const association = "50000000-0000-4000-8000-000000000001";
const projects: ProjectOutlookProject[] = [
  { id: "20000000-0000-4000-8000-000000000001", name: "Example catalog", identifier: "CAT" },
  { id: "20000000-0000-4000-8000-000000000002", name: "Example checkout", identifier: "PAY" },
].map(({ id, name, identifier }) => ({
  id,
  name,
  identifier,
  workspace,
  archived_at: null,
  member_role: 15,
  sort_order: 1,
  logo_props: { in_use: "icon" },
  module_view: true,
  cycle_view: true,
  issue_views_view: true,
  page_view: true,
  inbox_view: false,
}));
type Scenario = "available" | "selected" | "elsewhere" | "conflict" | "denied" | "uncertain" | "empty" | "unavailable";
const pause = () =>
  new Promise<void>((resolve) => {
    setTimeout(resolve, 350);
  });
function syntheticPort(scenario: Scenario): AssociationPort {
  const received = new Set<string>();
  return {
    async listProducts() {
      await pause();
      return scenario === "empty"
        ? []
        : [
            {
              id: product,
              workspace_id: workspace,
              key: "SHOP",
              name: "Example storefront",
              version: 2,
              state: "ACTIVE",
            },
          ];
    },
    async discover(_slug, scope, projectId) {
      await pause();
      if (scenario === "unavailable") throw { code: "UNAVAILABLE", status: 503 };
      if (scenario === "denied") throw { code: "UNAVAILABLE", status: 403 };
      const base = {
        schema_version: "curve.project-association-precondition/v1-candidate" as const,
        policy_edition: "LOCAL_NATIVE_PROJECT_ASSOCIATION_PRECONDITION_READ_V1" as const,
        workspace_id: scope.workspaceId,
        product_id: scope.productId,
        product_version: 3,
        provider_installation_id: installation,
        source_project_id: projectId,
        observed_at: new Date().toISOString(),
      };
      return scenario === "selected"
        ? { ...base, availability: "ASSOCIATED_WITH_SELECTED_PRODUCT", association_id: association }
        : {
            ...base,
            availability: scenario === "elsewhere" ? "ASSOCIATED_ELSEWHERE" : "AVAILABLE",
            association_id: null,
          };
    },
    async create(_slug, scope, body, command) {
      await pause();
      if (scenario === "conflict") throw { code: "CONFLICT", status: 412 };
      if (scenario === "uncertain" && !received.has(command.idempotencyKey)) {
        received.add(command.idempotencyKey);
        throw { code: "MUTATION_OUTCOME_UNKNOWN" };
      }
      const data: CurveProjectAssociation = {
        schema_version: "1.0",
        id: association,
        workspace_id: scope.workspaceId,
        product_id: scope.productId,
        provider_installation_id: body.provider_installation_id,
        source_project_id: body.source_project_id,
        state: "ACTIVE",
        version: 1,
        effective_at: new Date().toISOString(),
        initiated_by: "60000000-0000-4000-8000-000000000001",
        policy_edition: "EXPLICIT_EXISTING_PROJECT_ASSOCIATION_V1",
        command_receipt_id: "70000000-0000-4000-8000-000000000001",
        source_observed_at: new Date().toISOString(),
        source_version: "synthetic-v1",
        ended_at: null,
        ended_by: null,
        end_reason: null,
        end_receipt_id: null,
      };
      return { data, etag: `"curve-project-association:${association}:v1"` };
    },
  };
}
function ReviewSurface({ scenario }: { scenario: Scenario }) {
  const [selected, setSelected] = useState<string>();
  const [notice, setNotice] = useState("");
  const port = useMemo(() => syntheticPort(scenario), [scenario]);
  const read = { status: "ready" as const, data: projects };
  const flow = useCurveProjectAssociation({
    workspaceSlug: "synthetic-review",
    workspaceId: workspace,
    actorId: "synthetic-human",
    projects: read,
    port,
    onAccessUnavailable: () => undefined,
  });
  return (
    <div>
      {notice && (
        <p role="status" className="mx-auto max-w-6xl px-8 pt-5 text-13 text-secondary">
          {notice}
        </p>
      )}
      <ProjectOutlookView
        workspaceSlug="synthetic-review"
        projects={read}
        selectedProject={projects.find(({ id }) => id === selected)}
        selectProject={setSelected}
        members={{ status: "ready", data: [] }}
        modules={{ status: selected ? "ready" : "idle", data: [] }}
        cycles={{ status: selected ? "ready" : "idle", data: [] }}
        refresh={() => setNotice("Synthetic source records refreshed. No server was contacted.")}
        associationPanel={<ProjectAssociationFlow flow={flow} />}
      />
    </div>
  );
}
function App() {
  const [scenario, setScenario] = useState<Scenario>("available");
  return (
    <>
      <header className="flex flex-wrap items-center justify-between gap-5 border-b border-subtle bg-layer-1 px-5 py-4 sm:px-8">
        <img src={logo} alt="Curve" className="h-7 w-auto" />
        <p className="text-13 font-medium text-primary">Native component review · Synthetic data only</p>
        <label className="text-12 text-secondary">
          Review state{" "}
          <select
            value={scenario}
            onChange={(event) => setScenario(event.target.value as Scenario)}
            className="ml-2 rounded border border-subtle bg-surface-1 p-2 text-primary"
          >
            <option value="available">Available</option>
            <option value="selected">Already associated</option>
            <option value="elsewhere">Associated elsewhere</option>
            <option value="conflict">Version conflict</option>
            <option value="denied">Access denied</option>
            <option value="uncertain">Uncertain, then recover</option>
            <option value="empty">No Products</option>
            <option value="unavailable">Discovery unavailable</option>
          </select>
        </label>
      </header>
      <p className="mx-auto max-w-6xl px-5 pt-5 text-12 leading-5 text-secondary sm:px-8">
        All responses below are simulated in memory. No server is contacted, no native work is changed, and no approval
        or execution is granted. Visual and usability acceptance is pending.
      </p>
      <ReviewSurface key={scenario} scenario={scenario} />
    </>
  );
}
const root = document.getElementById("root");
if (root) createRoot(root).render(<App />);
