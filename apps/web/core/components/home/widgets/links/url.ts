/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export const normalizeQuickLinkUrl = (value: string): string | undefined => {
  const trimmedValue = value.trim();
  if (!trimmedValue) return undefined;
  const candidate = /^[a-z][a-z\d+.-]*:/i.test(trimmedValue) ? trimmedValue : `https://${trimmedValue}`;

  try {
    const parsedUrl = new URL(candidate);
    const isHttp = parsedUrl.protocol === "http:" || parsedUrl.protocol === "https:";
    const isRecognizableHost =
      parsedUrl.hostname === "localhost" || parsedUrl.hostname.includes(".") || parsedUrl.hostname.includes(":");
    return isHttp && isRecognizableHost ? parsedUrl.toString() : undefined;
  } catch {
    return undefined;
  }
};
