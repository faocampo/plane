/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { API_BASE_URL } from "@plane/constants";
import type { CurveExistingWorkMutation } from "@plane/types";
import type { AxiosResponse } from "axios";
import { APIService } from "../api.service";
import { CurveExistingWorkError, isCurveUuid, isCurveVersion, requireCurve } from "./existing-work-validation";

export function curveExistingWorkRoot(workspaceSlug: string) {
  requireCurve(typeof workspaceSlug === "string" && workspaceSlug.trim().length > 0);
  return `/api/v1/workspaces/${encodeURIComponent(workspaceSlug)}/curve/`;
}
export function curveExistingWorkId(id: string) {
  requireCurve(isCurveUuid(id));
  return encodeURIComponent(id);
}
export function curveExistingWorkMutation(options: CurveExistingWorkMutation): CurveExistingWorkMutation {
  requireCurve(isCurveVersion(options.expectedVersion));
  const key = options.idempotencyKey;
  requireCurve(
    typeof key === "string" &&
      key.length >= 1 &&
      key.length <= 255 &&
      key.trim().length > 0 &&
      Array.from(key).every((character) => character.charCodeAt(0) >= 32 && character.charCodeAt(0) !== 127)
  );
  // Reject unpaired surrogates rather than silently replacing their UTF-8 bytes.
  requireCurve(new TextDecoder("utf-8", { fatal: true }).decode(new TextEncoder().encode(key)) === key);
  return { ...options };
}
export function curveExistingWorkEtag(response: AxiosResponse, expected: string): string {
  // Never normalize a weak validator into a strong write precondition.
  requireCurve(response.headers.etag === expected);
  return expected;
}
export abstract class CurveExistingWorkTransport extends APIService {
  constructor(baseURL = API_BASE_URL) {
    super(baseURL);
  }

  protected async safely<T>(work: () => Promise<T>): Promise<T> {
    try {
      return await work();
    } catch (error) {
      if (error instanceof CurveExistingWorkError) throw error;
      const candidate = error as { code?: unknown; name?: unknown; response?: { status?: unknown } } | null;
      if (candidate?.code === "ERR_CANCELED" || candidate?.name === "AbortError")
        throw new CurveExistingWorkError("CANCELLED");
      const status = candidate?.response?.status;
      if (typeof status === "number" && Number.isInteger(status) && status >= 400 && status <= 599) {
        throw new CurveExistingWorkError(
          status === 409 || status === 412
            ? "CONFLICT"
            : status === 400 || status === 413 || status === 422 || status === 428
              ? "INVALID"
              : "UNAVAILABLE",
          status
        );
      }
      throw new CurveExistingWorkError("TRANSPORT");
    }
  }
  protected checkCancellation(signal?: AbortSignal): void {
    if (signal?.aborted) throw new CurveExistingWorkError("CANCELLED");
  }
  protected async finishRead<T>(value: Promise<T>, signal?: AbortSignal): Promise<T> {
    const data = await value;
    this.checkCancellation(signal);
    return data;
  }
  protected async read(path: string, signal?: AbortSignal): Promise<AxiosResponse> {
    if (signal?.aborted) throw new CurveExistingWorkError("CANCELLED");
    const response = await this.get(path, { signal, headers: { "Cache-Control": "no-store" } });
    if (signal?.aborted) throw new CurveExistingWorkError("CANCELLED");
    requireCurve(response.status === 200);
    return response;
  }
  protected async verifyMutation<T>(signal: AbortSignal | undefined, decode: () => T | Promise<T>): Promise<T> {
    try {
      const result = await decode();
      if (signal?.aborted) throw new CurveExistingWorkError("MUTATION_OUTCOME_UNKNOWN");
      return result;
    } catch {
      // The server may have committed even if its successful response cannot be verified.
      throw new CurveExistingWorkError("MUTATION_OUTCOME_UNKNOWN");
    }
  }
  protected async mutate(
    path: string,
    payload: object,
    options: CurveExistingWorkMutation,
    etag: string
  ): Promise<AxiosResponse> {
    const { signal, idempotencyKey } = options;
    if (signal?.aborted) throw new CurveExistingWorkError("CANCELLED");
    const csrf = await this.get("/auth/get-csrf-token/", {
      signal,
      params: { cache_bust: Date.now() },
      headers: { "Cache-Control": "no-store" },
    });
    const csrfToken: unknown = csrf.data?.csrf_token;
    requireCurve(typeof csrfToken === "string" && csrfToken.length > 0);
    if (signal?.aborted) throw new CurveExistingWorkError("CANCELLED");
    // No implicit retry, persisted command, cached authority, or retained rationale.
    try {
      const response = await this.post(path, payload, {
        signal,
        headers: {
          "Content-Type": "application/json",
          "Cache-Control": "no-store",
          "X-CSRFTOKEN": csrfToken,
          "If-Match": etag,
          "Idempotency-Key": idempotencyKey,
        },
      });
      if (signal?.aborted) throw new CurveExistingWorkError("MUTATION_OUTCOME_UNKNOWN");
      return response;
    } catch (error) {
      const status = (error as { response?: { status?: unknown } } | null)?.response?.status;
      // A received 4xx is a rejected command. Network loss, abort, and 5xx are not proof of no effect.
      if (typeof status === "number" && Number.isInteger(status) && status >= 400 && status < 500) throw error;
      throw new CurveExistingWorkError(
        "MUTATION_OUTCOME_UNKNOWN",
        typeof status === "number" && Number.isInteger(status) && status >= 500 && status <= 599 ? status : undefined
      );
    }
  }
}
