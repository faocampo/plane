/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type {
  ICurveOperationMutationResult,
  ICurveOperationPage,
  ICurveOperationSummary,
  ICurveWorkspaceShell,
  TCurveOperationType,
} from "@plane/types";
import { APIService } from "../api.service";

export class CurveService extends APIService {
  constructor(BASE_URL?: string) {
    super(BASE_URL || API_BASE_URL);
  }

  private async requestCSRFToken(): Promise<string> {
    const response = await this.get("/auth/get-csrf-token/", {
      params: { cache_bust: Date.now() },
    });
    const csrfToken = response.data?.csrf_token;
    if (typeof csrfToken !== "string" || csrfToken.length === 0) throw new Error("Curve CSRF token is unavailable");
    return csrfToken;
  }

  async retrieveWorkspaceShell(workspaceSlug: string): Promise<ICurveWorkspaceShell> {
    return this.get(`/api/v1/workspaces/${workspaceSlug}/curve/`)
      .then((response) => response.data)
      .catch((error) => {
        throw error?.response;
      });
  }

  async listOperations(
    workspaceSlug: string,
    pageSize = 1,
    cursor?: string,
    operationType?: TCurveOperationType
  ): Promise<ICurveOperationPage> {
    return this.get(`/api/v1/workspaces/${workspaceSlug}/curve/operations/`, {
      params: {
        page_size: pageSize,
        ...(cursor ? { cursor } : {}),
        ...(operationType ? { operation_type: operationType } : {}),
      },
    })
      .then((response) => response.data)
      .catch((error) => {
        throw error?.response;
      });
  }

  async retrieveOperation(workspaceSlug: string, operationId: string): Promise<ICurveOperationMutationResult> {
    return this.get(`/api/v1/workspaces/${workspaceSlug}/curve/operations/${operationId}/`)
      .then((response) => ({
        operation: response.data as ICurveOperationSummary,
        etag: response.headers.etag as string,
      }))
      .catch((error) => {
        throw error?.response;
      });
  }

  async createFoundationProbe(workspaceSlug: string, idempotencyKey: string): Promise<ICurveOperationMutationResult> {
    const csrfToken = await this.requestCSRFToken();
    return this.post(
      `/api/v1/workspaces/${workspaceSlug}/curve/foundation-probes/`,
      {},
      {
        headers: {
          "Idempotency-Key": idempotencyKey,
          "X-CSRFTOKEN": csrfToken,
        },
      }
    )
      .then((response) => ({
        operation: response.data as ICurveOperationSummary,
        etag: response.headers.etag as string,
        location: response.headers.location as string | undefined,
      }))
      .catch((error) => {
        throw error?.response;
      });
  }

  async cancelOperation(
    workspaceSlug: string,
    operationId: string,
    etag: string,
    idempotencyKey: string
  ): Promise<ICurveOperationMutationResult> {
    const csrfToken = await this.requestCSRFToken();
    return this.post(
      `/api/v1/workspaces/${workspaceSlug}/curve/operations/${operationId}/cancel/`,
      {},
      {
        headers: {
          "Idempotency-Key": idempotencyKey,
          "If-Match": etag,
          "X-CSRFTOKEN": csrfToken,
        },
      }
    )
      .then((response) => ({
        operation: response.data as ICurveOperationSummary,
        etag: response.headers.etag as string,
      }))
      .catch((error) => {
        throw error?.response;
      });
  }
}
