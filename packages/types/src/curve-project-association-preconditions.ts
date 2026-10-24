/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
/** Current advisory availability. This read never grants command authority. */
export type CurveProjectAssociationPreconditionsV1 = {
  schema_version: "curve.project-association-precondition/v1-candidate";
  policy_edition: "LOCAL_NATIVE_PROJECT_ASSOCIATION_PRECONDITION_READ_V1";
  workspace_id: string;
  product_id: string;
  product_version: number;
  provider_installation_id: string;
  source_project_id: string;
  observed_at: string;
} & (
  | { availability: "AVAILABLE" | "ASSOCIATED_ELSEWHERE"; association_id: null }
  | { availability: "ASSOCIATED_WITH_SELECTED_PRODUCT"; association_id: string }
);
