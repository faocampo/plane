/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type {
  ICurveInitiativeCreateRequest,
  ICurveInitiativeDraftUpdateRequest,
  ICurveInitiativeListFilters,
  ICurveInitiativeMutationResult,
  ICurveInitiativePage,
  ICurveInitiativeTransitionRequest,
  ICurveOperationMutationResult,
  ICurveOperationPage,
  ICurveOperationSummary,
  ICurveProductListFilters,
  ICurveProductPage,
  ICurveWorkspaceShell,
  TCurveOperationType,
} from "@plane/types";
import { APIService } from "../api.service";

const normalizeCurveEtag = (etag: unknown): string => {
  if (typeof etag !== "string" || etag.length === 0) throw new Error("Curve ETag is unavailable");
  return etag.startsWith("W/") ? etag.slice(2) : etag;
};

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
        etag: normalizeCurveEtag(response.headers.etag),
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
        etag: normalizeCurveEtag(response.headers.etag),
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
          "If-Match": normalizeCurveEtag(etag),
          "X-CSRFTOKEN": csrfToken,
        },
      }
    )
      .then((response) => ({
        operation: response.data as ICurveOperationSummary,
        etag: normalizeCurveEtag(response.headers.etag),
      }))
      .catch((error) => {
        throw error?.response;
      });
  }

  async listProducts(
    workspaceSlug: string,
    { state = "ACTIVE", pageSize = 100, cursor }: ICurveProductListFilters = {}
  ): Promise<ICurveProductPage> {
    return this.get(`/api/v1/workspaces/${workspaceSlug}/curve/products/`, {
      params: {
        state,
        page_size: pageSize,
        ...(cursor ? { cursor } : {}),
      },
    })
      .then((response) => response.data)
      .catch((error) => {
        throw error?.response;
      });
  }

  async listInitiatives(
    workspaceSlug: string,
    { state, productId, pageSize = 100, cursor }: ICurveInitiativeListFilters = {}
  ): Promise<ICurveInitiativePage> {
    return this.get(`/api/v1/workspaces/${workspaceSlug}/curve/initiatives/`, {
      params: {
        page_size: pageSize,
        ...(cursor ? { cursor } : {}),
        ...(state ? { state } : {}),
        ...(productId ? { product_id: productId } : {}),
      },
    })
      .then((response) => response.data)
      .catch((error) => {
        throw error?.response;
      });
  }

  async retrieveInitiative(workspaceSlug: string, initiativeId: string): Promise<ICurveInitiativeMutationResult> {
    return this.get(`/api/v1/workspaces/${workspaceSlug}/curve/initiatives/${initiativeId}/`)
      .then((response) => ({
        initiative: response.data,
        etag: normalizeCurveEtag(response.headers.etag),
      }))
      .catch((error) => {
        throw error?.response;
      });
  }

  async createInitiative(
    workspaceSlug: string,
    payload: ICurveInitiativeCreateRequest,
    idempotencyKey: string
  ): Promise<ICurveInitiativeMutationResult> {
    const csrfToken = await this.requestCSRFToken();
    return this.post(`/api/v1/workspaces/${workspaceSlug}/curve/initiatives/`, payload, {
      headers: {
        "Idempotency-Key": idempotencyKey,
        "X-CSRFTOKEN": csrfToken,
      },
    })
      .then((response) => ({
        initiative: response.data,
        etag: normalizeCurveEtag(response.headers.etag),
        location: response.headers.location as string | undefined,
      }))
      .catch((error) => {
        throw error?.response;
      });
  }

  async updateInitiativeDraft(
    workspaceSlug: string,
    initiativeId: string,
    payload: ICurveInitiativeDraftUpdateRequest,
    etag: string,
    idempotencyKey: string
  ): Promise<ICurveInitiativeMutationResult> {
    const csrfToken = await this.requestCSRFToken();
    return this.patch(`/api/v1/workspaces/${workspaceSlug}/curve/initiatives/${initiativeId}/`, payload, {
      headers: {
        "Idempotency-Key": idempotencyKey,
        "If-Match": normalizeCurveEtag(etag),
        "X-CSRFTOKEN": csrfToken,
      },
    })
      .then((response) => ({
        initiative: response.data,
        etag: normalizeCurveEtag(response.headers.etag),
      }))
      .catch((error) => {
        throw error?.response;
      });
  }

  async acceptInitiativeRefinement(
    workspaceSlug: string,
    initiativeId: string,
    etag: string,
    idempotencyKey: string
  ): Promise<ICurveInitiativeMutationResult> {
    return this.transitionInitiative(workspaceSlug, initiativeId, "accept-refinement", {}, etag, idempotencyKey);
  }

  async pauseInitiative(
    workspaceSlug: string,
    initiativeId: string,
    payload: ICurveInitiativeTransitionRequest,
    etag: string,
    idempotencyKey: string
  ): Promise<ICurveInitiativeMutationResult> {
    return this.transitionInitiative(workspaceSlug, initiativeId, "pause", payload, etag, idempotencyKey);
  }

  async resumeInitiative(
    workspaceSlug: string,
    initiativeId: string,
    payload: ICurveInitiativeTransitionRequest,
    etag: string,
    idempotencyKey: string
  ): Promise<ICurveInitiativeMutationResult> {
    return this.transitionInitiative(workspaceSlug, initiativeId, "resume", payload, etag, idempotencyKey);
  }

  async cancelInitiative(
    workspaceSlug: string,
    initiativeId: string,
    payload: ICurveInitiativeTransitionRequest,
    etag: string,
    idempotencyKey: string
  ): Promise<ICurveInitiativeMutationResult> {
    return this.transitionInitiative(workspaceSlug, initiativeId, "cancel", payload, etag, idempotencyKey);
  }

  private async transitionInitiative(
    workspaceSlug: string,
    initiativeId: string,
    action: "accept-refinement" | "pause" | "resume" | "cancel",
    payload: ICurveInitiativeTransitionRequest | Record<string, never>,
    etag: string,
    idempotencyKey: string
  ): Promise<ICurveInitiativeMutationResult> {
    const csrfToken = await this.requestCSRFToken();
    return this.post(`/api/v1/workspaces/${workspaceSlug}/curve/initiatives/${initiativeId}/${action}/`, payload, {
      headers: {
        "Idempotency-Key": idempotencyKey,
        "If-Match": normalizeCurveEtag(etag),
        "X-CSRFTOKEN": csrfToken,
      },
    })
      .then((response) => ({
        initiative: response.data,
        etag: normalizeCurveEtag(response.headers.etag),
      }))
      .catch((error) => {
        throw error?.response;
      });
  }
}
