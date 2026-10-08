// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
/** Synthetic harness only: real native destinations are intentionally unavailable. */
import type { AnchorHTMLAttributes } from "react";
export default function ReviewLink({ children, className }: AnchorHTMLAttributes<HTMLAnchorElement>) {
  return (
    <button type="button" disabled className={className} title="Native destination unavailable in this isolated review">
      {children}
    </button>
  );
}
