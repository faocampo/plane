/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Info } from "lucide-react";
import { cn } from "@plane/utils";

export const CURVE_AUTH_COPY = {
  signIn: {
    pageTitle: "Sign in",
    prompt: "New to Curve?",
    action: "Create account",
    heading: "Plan, build, and review with context.",
    subheading: "Welcome back to Curve.",
  },
  signUp: {
    pageTitle: "Create account",
    prompt: "Already have a Curve account?",
    action: "Sign in",
    heading: "Plan, build, and review with context.",
    subheading: "Create your Curve account.",
  },
  recoveryUnavailable:
    "Email password recovery is unavailable because this environment has no mail service. Ask the environment owner to reset your password.",
} as const;

export function CurveAuthBrand({ className }: { className?: string }) {
  return (
    <span
      className={cn("shadow-sm inline-flex items-center rounded-md bg-white px-2 py-1 ring-1 ring-black/5", className)}
    >
      <img src="/curve/curve-logo-light-v1.webp" alt="Curve" className="h-7 w-auto object-contain" />
    </span>
  );
}

export function CurvePasswordRecoveryUnavailable() {
  return (
    <div className="flex items-start gap-2 text-11 leading-4 text-tertiary" role="note">
      <Info className="mt-0.5 size-3.5 shrink-0 text-accent-primary" aria-hidden="true" />
      <span>{CURVE_AUTH_COPY.recoveryUnavailable}</span>
    </div>
  );
}
