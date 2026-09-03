/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { describe, expect, it } from "vitest";

import { normalizeQuickLinkUrl } from "@/components/home/widgets/links/url";

describe("Quicklink URL validation", () => {
  it("normalizes recognizable website addresses", () => {
    expect(normalizeQuickLinkUrl("example.com/docs")).toBe("https://example.com/docs");
    expect(normalizeQuickLinkUrl("http://localhost:3000/x3m")).toBe("http://localhost:3000/x3m");
  });

  it("rejects malformed or unsupported addresses before submission", () => {
    expect(normalizeQuickLinkUrl("ewrwerwe")).toBeUndefined();
    expect(normalizeQuickLinkUrl("mailto:hello@example.com")).toBeUndefined();
    expect(normalizeQuickLinkUrl("https://")).toBeUndefined();
  });
});
