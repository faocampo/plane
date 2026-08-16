/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export function CurveEmptyState() {
  return (
    <section className="flex h-full items-center justify-center px-6" aria-labelledby="curve-title">
      <div className="max-w-lg space-y-2 text-center">
        <h1 id="curve-title" className="text-24 font-semibold text-primary">
          Curve
        </h1>
        <p className="text-14 text-secondary">Your AI-native product development workspace is ready.</p>
      </div>
    </section>
  );
}
