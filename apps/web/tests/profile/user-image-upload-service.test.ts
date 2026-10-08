/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { EFileAssetType } from "@plane/types";
import { APIService } from "@/services/api.service";
import { FileService } from "@/services/file.service";
import { FileUploadService } from "@/services/file-upload.service";

const { getFileMetaDataForUpload, generateFileUploadPayload } = vi.hoisted(() => ({
  getFileMetaDataForUpload: vi.fn(),
  generateFileUploadPayload: vi.fn(),
}));

vi.mock("@plane/services", () => ({ getFileMetaDataForUpload, generateFileUploadPayload }));

describe("User image upload service", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it("completes the signed-upload sequence before returning the user asset", async () => {
    const file = new File(["avatar"], "avatar.png", { type: "image/png" });
    const uploadPayload = new FormData();
    const signedAsset = {
      asset_id: "asset-1",
      asset_url: "/uploads/avatar.png",
      upload_data: { url: "http://minio.test/uploads", fields: { key: "asset-1-avatar.png" } },
    };
    getFileMetaDataForUpload.mockResolvedValue({ name: "avatar.png", size: 6, type: "image/png" });
    generateFileUploadPayload.mockReturnValue(uploadPayload);
    const post = vi.spyOn(APIService.prototype, "post").mockResolvedValue({ data: signedAsset } as never);
    const upload = vi.spyOn(FileUploadService.prototype, "uploadFile").mockResolvedValue(undefined);
    const patch = vi.spyOn(APIService.prototype, "patch").mockResolvedValue({ data: undefined } as never);

    const result = await new FileService().uploadUserAsset(
      { entity_identifier: "", entity_type: EFileAssetType.USER_AVATAR },
      file
    );

    expect(post).toHaveBeenCalledWith("/api/assets/v2/user-assets/", {
      entity_identifier: "",
      entity_type: EFileAssetType.USER_AVATAR,
      name: "avatar.png",
      size: 6,
      type: "image/png",
    });
    expect(generateFileUploadPayload).toHaveBeenCalledWith(signedAsset, file);
    expect(upload).toHaveBeenCalledWith("http://minio.test/uploads", uploadPayload);
    expect(patch).toHaveBeenCalledWith("/api/assets/v2/user-assets/asset-1/");
    expect(result).toEqual(signedAsset);
  });

  it("returns the backend diagnostic when signed-upload creation fails", async () => {
    const file = new File(["avatar"], "avatar.png", { type: "image/png" });
    getFileMetaDataForUpload.mockResolvedValue({ name: "avatar.png", size: 6, type: "image/png" });
    vi.spyOn(APIService.prototype, "post").mockRejectedValue({
      response: { data: { error: "Object storage is unavailable" } },
    });

    await expect(
      new FileService().uploadUserAsset({ entity_identifier: "", entity_type: EFileAssetType.USER_AVATAR }, file)
    ).rejects.toEqual({ error: "Object storage is unavailable" });
  });
});
