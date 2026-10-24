/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// oxlint-disable-next-line import/no-unassigned-import
import "@testing-library/jest-dom/vitest";

// jsdom does not implement Web Animations; menus query running animations
// while calculating scroll geometry. This environment has no running animations.
if (!Element.prototype.getAnimations) {
  // oxlint-disable-next-line no-extend-native -- jsdom-only Web Animations shim for upstream overlay geometry.
  Object.defineProperty(Element.prototype, "getAnimations", { configurable: true, value: () => [] });
}
