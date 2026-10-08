/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { FormProvider, useForm } from "react-hook-form";
import { describe, expect, it, vi } from "vitest";

import type { IProject } from "@plane/types";
import ProjectCreateHeader from "@/components/project/create/header";

vi.mock("@plane/i18n", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@plane/propel/emoji-icon-picker", () => ({
  EmojiIconPickerTypes: { EMOJI: "emoji", ICON: "icon" },
  EmojiPicker: () => null,
  Logo: () => null,
}));
vi.mock("@/components/common/cover-image", () => ({
  CoverImage: ({ src }: { src?: string | null }) => <div data-testid="cover-image">{src ?? "none"}</div>,
}));
vi.mock("@/components/core/image-picker-popover", () => ({
  ImagePickerPopover: ({ label, onChange }: { label: string; onChange: (value: string) => void }) => (
    <button type="button" onClick={() => onChange("/uploads/new-cover.webp")}>
      {label}
    </button>
  ),
}));

function HeaderHarness({ handleFormOnChange }: { handleFormOnChange?: () => void }) {
  const methods = useForm<IProject>({
    defaultValues: {
      cover_image_url: "/static/project-cover.webp",
      logo_props: {},
    },
  });
  return (
    <FormProvider {...methods}>
      <ProjectCreateHeader handleClose={vi.fn()} handleFormOnChange={handleFormOnChange} />
    </FormProvider>
  );
}

describe("Project create header", () => {
  it("removes an optional cover without closing the project form", () => {
    render(<HeaderHarness />);

    expect(screen.getByTestId("cover-image")).toHaveTextContent("/static/project-cover.webp");
    fireEvent.click(screen.getByRole("button", { name: "Remove cover" }));

    expect(screen.getByTestId("cover-image")).toHaveTextContent("none");
    expect(screen.queryByRole("button", { name: "Remove cover" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "change_cover" })).toBeInTheDocument();
  });

  it("stores a selected cover in the project form and marks the form as changed", () => {
    const handleFormOnChange = vi.fn();
    render(<HeaderHarness handleFormOnChange={handleFormOnChange} />);

    fireEvent.click(screen.getByRole("button", { name: "change_cover" }));

    expect(screen.getByTestId("cover-image")).toHaveTextContent("/uploads/new-cover.webp");
    expect(handleFormOnChange).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Remove cover" })).toBeInTheDocument();
  });
});
