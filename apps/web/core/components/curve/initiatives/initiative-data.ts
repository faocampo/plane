/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ICurveInitiative, ICurveProblemDetails } from "@plane/types";

export const CURVE_INITIATIVE_CONFLICT_STATUSES = new Set([409, 412, 428]);
export const CURVE_INITIATIVE_PERMISSION_STATUSES = new Set([401, 403, 404]);

export const mergeCurveInitiatives = (current: ICurveInitiative[], incoming: ICurveInitiative[]) => {
  const incomingById = new Map(incoming.map((initiative) => [initiative.id, initiative]));
  const merged = current.map((initiative) => incomingById.get(initiative.id) ?? initiative);
  const currentIds = new Set(current.map((initiative) => initiative.id));
  return [...merged, ...incoming.filter((initiative) => !currentIds.has(initiative.id))];
};

export const toSafeCurveProblem = (error: unknown, fallbackTitle: string): ICurveProblemDetails => {
  const response = error as
    | {
        status?: number;
        data?: { type?: string; title?: string; correlation_id?: string };
      }
    | undefined;
  const status = response?.status ?? 500;
  const permissionLimited = CURVE_INITIATIVE_PERMISSION_STATUSES.has(status);
  const conflict = CURVE_INITIATIVE_CONFLICT_STATUSES.has(status);

  return {
    type:
      typeof response?.data?.type === "string"
        ? response.data.type
        : "https://curve.x3m.internal/problems/request-failed",
    title: permissionLimited ? "Initiatives are unavailable" : conflict ? "The Initiative changed" : fallbackTitle,
    status,
    ...(typeof response?.data?.correlation_id === "string" ? { correlation_id: response.data.correlation_id } : {}),
  };
};
