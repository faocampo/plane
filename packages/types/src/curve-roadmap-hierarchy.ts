/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
export type CurveHierarchyMetadata = {
  id: string;
  schema_version: "1.0";
  workspace_id: string;
  product_id: string;
  version: number;
  name: string;
  created_at: string;
  updated_at: string;
};
export type CurveRoadmapMetadata = CurveHierarchyMetadata & {
  owner_user_id: string;
  horizon_start: string | null;
  horizon_end: string | null;
};
export type CurveMilestoneMetadata = CurveHierarchyMetadata & {
  roadmap_id: string;
  type: "RELEASE_VERSION" | "CALENDAR_PERIOD" | "PRODUCT_OUTCOME" | "INTERNAL_DEVELOPMENT_PHASE";
  position: number;
  target_start: string | null;
  target_end: string | null;
};
export type CurveFeatureMetadata = Pick<
  CurveHierarchyMetadata,
  "id" | "version" | "name" | "created_at" | "updated_at"
>;
export type CurveRoadmapPage = { results: CurveRoadmapMetadata[]; next_cursor: string | null };
export type CurveMilestonePage = {
  results: CurveMilestoneMetadata[];
  next_cursor: string | null;
  roadmap_version: number;
};
export type CurveFeaturePage = { results: CurveFeatureMetadata[]; next_cursor: string | null; is_editor: boolean };
