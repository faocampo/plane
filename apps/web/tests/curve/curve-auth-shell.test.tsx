/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CURVE_AUTH_COPY, CurveAuthBrand, CurvePasswordRecoveryUnavailable } from "@/components/curve/curve-auth-brand";
import { EAuthenticationErrorCodes, authErrorHandler } from "@/helpers/authentication.helper";

describe("Curve authentication shell", () => {
  it("presents Curve as the product on unauthenticated routes", () => {
    render(<CurveAuthBrand />);

    expect(screen.getByRole("img", { name: "Curve" })).toHaveAttribute("src", "/curve/curve-logo-light-v1.webp");
    expect(CURVE_AUTH_COPY.signIn.subheading).toBe("Welcome back to Curve.");
    expect(CURVE_AUTH_COPY.signUp.subheading).toBe("Create your Curve account.");
  });

  it("explains the local recovery path when mail delivery is unavailable", () => {
    render(<CurvePasswordRecoveryUnavailable />);

    expect(screen.getByRole("note")).toHaveTextContent(
      "Email password recovery is unavailable because this environment has no mail service."
    );
    expect(screen.getByRole("note")).toHaveTextContent("Ask the environment owner to reset your password.");
  });

  it("returns a precise non-enumerating error for a rejected password", () => {
    const error = authErrorHandler(EAuthenticationErrorCodes.AUTHENTICATION_FAILED_SIGN_IN);

    expect(error?.title).toBe("Sign-in unsuccessful");
    expect(error?.message).toBe("The email or password is incorrect. Check your details and try again.");
  });
});
