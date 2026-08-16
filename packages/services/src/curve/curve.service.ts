/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { ICurveWorkspaceShell } from "@plane/types";
import { APIService } from "../api.service";

export class CurveService extends APIService {
  constructor(BASE_URL?: string) {
    super(BASE_URL || API_BASE_URL);
  }

  async retrieveWorkspaceShell(workspaceSlug: string): Promise<ICurveWorkspaceShell> {
    return this.get(`/api/v1/workspaces/${workspaceSlug}/curve/`)
      .then((response) => response.data)
      .catch((error) => {
        throw error?.response;
      });
  }
}
