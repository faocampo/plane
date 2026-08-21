/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { ExternalLink } from "lucide-react";

const sourceRepository = process.env.VITE_CURVE_SOURCE_REPOSITORY_URL || "https://github.com/faocampo/plane";
const sourceRevision = process.env.VITE_CURVE_SOURCE_REVISION;
const IMMUTABLE_GIT_REVISION_PATTERN = /^[0-9a-f]{40}$/i;

export const buildCurveSourceUrl = (repository: string, revision?: string): string | undefined => {
  if (!IMMUTABLE_GIT_REVISION_PATTERN.test(revision ?? "")) return undefined;
  return `${repository.replace(/\/$/, "")}/tree/${revision}`;
};

export const curveSourceUrl = buildCurveSourceUrl(sourceRepository, sourceRevision);

export function CurveSourceLink({
  compact = false,
  repository = sourceRepository,
  revision = sourceRevision,
}: {
  compact?: boolean;
  repository?: string;
  revision?: string;
}) {
  const url = buildCurveSourceUrl(repository, revision);
  if (!url) {
    return (
      <span className="text-11 font-medium text-placeholder" title="Configure an exact public Curve commit SHA">
        {compact ? "Source unavailable" : "Source code unavailable"}
      </span>
    );
  }

  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1 rounded-sm text-11 font-medium text-link-primary underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-accent-strong focus-visible:outline-none"
      aria-label={`Open source for Curve revision ${revision}`}
    >
      {compact ? "Source (AGPL)" : "Source code (AGPL)"}
      <ExternalLink className="size-3" aria-hidden="true" />
    </a>
  );
}
