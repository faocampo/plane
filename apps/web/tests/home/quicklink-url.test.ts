import { describe, expect, it } from "vitest";
import { getQuickLinkUrlError, normalizeQuickLinkUrl } from "@/components/home/widgets/links/url";

describe("Quicklink URL helpers", () => {
  it.each([
    ["plane.so", "http://plane.so"],
    ["https://plane.so/docs", "https://plane.so/docs"],
    ["localhost:3000", "http://localhost:3000"],
    ["127.0.0.1:3000/path", "http://127.0.0.1:3000/path"],
    ["http://[::1]:3000", "http://[::1]:3000"],
  ])("normalizes a valid URL (%s)", (input, expected) => {
    expect(normalizeQuickLinkUrl(input)).toBe(expected);
  });

  it.each(["", "   ", "ddddd", "javascript:alert(1)", "http://bad_host", "https://999.999.999.999"])(
    "rejects an invalid URL (%s)",
    (input) => {
      expect(normalizeQuickLinkUrl(input)).toBeUndefined();
    }
  );

  it("extracts the backend field error", () => {
    expect(getQuickLinkUrlError({ data: { url: { error: "Invalid URL format." } } })).toBe("Invalid URL format.");
  });
});
