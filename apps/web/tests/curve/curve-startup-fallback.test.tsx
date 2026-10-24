// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
import React, { act } from "react";
import { renderToString } from "react-dom/server";
import { hydrateRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { HydrateFallback } from "../../app/root";

it("hydrates the same accessible loading content", async () => {
  const host = document.createElement("div");
  host.innerHTML = renderToString(<HydrateFallback />);
  expect(host.querySelector('[role="status"]')?.textContent).toBe("Loading Curve…");
  document.body.append(host);
  const onRecoverableError = vi.fn();
  let root: ReturnType<typeof hydrateRoot> | undefined;
  try {
    await act(async () => {
      root = hydrateRoot(host, <HydrateFallback />, { onRecoverableError });
    });
    expect(onRecoverableError).not.toHaveBeenCalled();
    expect(host.querySelector('[role="status"]')?.textContent).toBe("Loading Curve…");
  } finally {
    await act(async () => root?.unmount());
    host.remove();
  }
});
