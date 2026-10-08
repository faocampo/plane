/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { CurveSourceLink } from "@/components/curve/curve-source-link";

export function AuthFooter() {
  return (
    <div className="flex flex-col items-center gap-2 text-center">
      <span className="text-13 text-tertiary">AI-native product delivery with Plane-backed work management.</span>
      <CurveSourceLink compact />
    </div>
  );
}
