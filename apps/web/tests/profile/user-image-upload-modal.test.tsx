/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EFileAssetType } from "@plane/types";
import { UserImageUploadModal } from "@/components/core/modals/user-image-upload-modal";

const { uploadUserAsset, deleteOldUserAsset, deleteUserAsset, setToast, acceptedFile } = vi.hoisted(() => ({
  uploadUserAsset: vi.fn(),
  deleteOldUserAsset: vi.fn(),
  deleteUserAsset: vi.fn(),
  setToast: vi.fn(),
  acceptedFile: new File(["avatar"], "avatar.png", { type: "image/png" }),
}));

vi.mock("@/services/file.service", () => ({
  FileService: class {
    uploadUserAsset = uploadUserAsset;
    deleteOldUserAsset = deleteOldUserAsset;
    deleteUserAsset = deleteUserAsset;
  },
}));
vi.mock("react-dropzone", () => ({
  useDropzone: ({ onDrop }: { onDrop: (files: File[]) => void }) => ({
    getRootProps: () => ({}),
    getInputProps: () => ({
      "data-testid": "avatar-file-input",
      type: "file",
      onChange: () => onDrop([acceptedFile]),
    }),
    isDragActive: false,
    fileRejections: [],
  }),
}));
vi.mock("@plane/propel/button", () => ({
  Button: ({ loading: _loading, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean }) => (
    <button {...props} />
  ),
}));
vi.mock("@plane/propel/icons", () => ({ UserCirclePropertyIcon: () => <span aria-hidden="true" /> }));
vi.mock("@plane/propel/toast", () => ({
  TOAST_TYPE: { ERROR: "error" },
  setToast,
}));
vi.mock("@plane/ui", () => ({
  EModalPosition: { CENTER: "center" },
  EModalWidth: { XL: "xl" },
  ModalCore: ({ isOpen, children }: { isOpen: boolean; children: React.ReactNode }) =>
    isOpen ? <div role="dialog">{children}</div> : null,
}));
vi.mock("@plane/utils", () => ({
  checkURLValidity: vi.fn(() => true),
  getAssetIdFromUrl: vi.fn(() => "asset-1"),
  getFileURL: vi.fn((value: string) => value),
}));

describe("User image upload", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("URL", { ...URL, createObjectURL: vi.fn(() => "blob:avatar-preview") });
  });

  it("uploads the selected file as a user avatar and returns its asset URL", async () => {
    uploadUserAsset.mockResolvedValue({ asset_url: "/uploads/avatar.png" });
    const onSuccess = vi.fn();
    render(<UserImageUploadModal isOpen value={null} onClose={vi.fn()} onSuccess={onSuccess} handleRemove={vi.fn()} />);

    fireEvent.change(screen.getByTestId("avatar-file-input"), { target: { files: [acceptedFile] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload & Save" }));

    await waitFor(() =>
      expect(uploadUserAsset).toHaveBeenCalledWith(
        { entity_identifier: "", entity_type: EFileAssetType.USER_AVATAR },
        acceptedFile
      )
    );
    expect(onSuccess).toHaveBeenCalledWith("/uploads/avatar.png");
    expect(setToast).not.toHaveBeenCalled();
  });

  it("keeps the modal usable and reports an actionable upload failure", async () => {
    uploadUserAsset.mockRejectedValue({ error: "Object storage is unavailable" });
    render(<UserImageUploadModal isOpen value={null} onClose={vi.fn()} onSuccess={vi.fn()} handleRemove={vi.fn()} />);

    fireEvent.change(screen.getByTestId("avatar-file-input"), { target: { files: [acceptedFile] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload & Save" }));

    await waitFor(() =>
      expect(setToast).toHaveBeenCalledWith({
        type: "error",
        title: "Image not uploaded",
        message: "Object storage is unavailable",
      })
    );
    expect(screen.getByRole("button", { name: "Upload & Save" })).toBeEnabled();
  });
});
