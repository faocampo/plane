/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { vi } from "vitest";
import type { CurveProjectAssociation } from "@plane/types";
import type {
  AssociationDiscovery,
  AssociationPort,
  AssociationProduct,
} from "@/components/curve/projects/project-association-model";
import type { ProjectOutlookProject, ProjectRead } from "@/components/curve/projects/project-outlook-data";

// Synthetic-only review data. Never imported by a production module.
export const WORKSPACE = "10000000-0000-4000-8000-000000000001";
export const PROJECT = "20000000-0000-4000-8000-000000000001";
export const PRODUCT = "30000000-0000-4000-8000-000000000001";
export const INSTALLATION = "40000000-0000-4000-8000-000000000001";
export const ASSOCIATION = "50000000-0000-4000-8000-000000000001";
export const sourceProject: ProjectOutlookProject = {
  id: PROJECT,
  name: "Example catalog",
  identifier: "CAT",
  workspace: WORKSPACE,
  archived_at: null,
  member_role: 15,
  sort_order: 1,
  logo_props: { in_use: "icon" },
  module_view: true,
  cycle_view: true,
  page_view: true,
  issue_views_view: true,
  inbox_view: false,
};
export const products: AssociationProduct[] = [
  {
    id: PRODUCT,
    workspace_id: WORKSPACE,
    key: "SHOP",
    name: "Example storefront",
    version: 2,
    state: "ACTIVE",
  },
];
export const discovery: AssociationDiscovery = {
  schema_version: "curve.project-association-precondition/v1-candidate",
  policy_edition: "LOCAL_NATIVE_PROJECT_ASSOCIATION_PRECONDITION_READ_V1",
  workspace_id: WORKSPACE,
  product_id: PRODUCT,
  product_version: 3,
  provider_installation_id: INSTALLATION,
  source_project_id: PROJECT,
  association_id: null,
  availability: "AVAILABLE",
  observed_at: "2026-10-04T12:00:00Z",
};
export const receipt: CurveProjectAssociation = {
  schema_version: "1.0",
  id: ASSOCIATION,
  workspace_id: WORKSPACE,
  provider_installation_id: INSTALLATION,
  source_project_id: PROJECT,
  product_id: PRODUCT,
  state: "ACTIVE",
  version: 1,
  effective_at: "2026-10-04T12:01:00Z",
  initiated_by: "60000000-0000-4000-8000-000000000001",
  policy_edition: "EXPLICIT_EXISTING_PROJECT_ASSOCIATION_V1",
  command_receipt_id: "70000000-0000-4000-8000-000000000001",
  source_observed_at: "2026-10-04T12:01:00Z",
  source_version: "source-v1",
  ended_at: null,
  ended_by: null,
  end_reason: null,
  end_receipt_id: null,
};
export function makePort() {
  return {
    listProducts: vi.fn<AssociationPort["listProducts"]>().mockResolvedValue(products),
    discover: vi.fn<AssociationPort["discover"]>().mockResolvedValue(discovery),
    create: vi
      .fn<AssociationPort["create"]>()
      .mockResolvedValue({ data: receipt, etag: `"curve-project-association:${ASSOCIATION}:v1"` }),
  };
}
export const projectRead: ProjectRead<ProjectOutlookProject> = { status: "ready", data: [sourceProject] };
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
