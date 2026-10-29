/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { useEffect, useRef } from "react";
import { useBlocker } from "react-router";
import { Button } from "@makeplane/propel/components/button";
export function ItemNavigationGuard({ pending }: { pending: boolean }) {
  const blocker = useBlocker(pending);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (blocker.state === "blocked") heading.current?.focus();
  }, [blocker.state]);
  if (blocker.state !== "blocked") return null;
  return (
    <section role="alert" className="mb-6 rounded-lg bg-warning-subtle p-5">
      <h2 ref={heading} tabIndex={-1} className="text-16 font-semibold">
        Finish recovering this item
      </h2>
      <p className="mt-2 max-w-prose text-14">
        The save may still be running. Keep this page open to recover its result with the same request.
      </p>
      <div className="mt-4 flex flex-wrap gap-3">
        <Button label="Stay and recover" variant="primary" size="lg" stretch="auto" onClick={() => blocker.reset()} />
        <Button
          label="Leave without confirming"
          variant="secondary"
          size="lg"
          stretch="auto"
          onClick={() => blocker.proceed()}
        />
      </div>
    </section>
  );
}
