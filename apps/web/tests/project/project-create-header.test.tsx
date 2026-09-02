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
  ImagePickerPopover: ({ label }: { label: string }) => <button type="button">{label}</button>,
}));

function HeaderHarness() {
  const methods = useForm<IProject>({
    defaultValues: {
      cover_image_url: "/static/project-cover.webp",
      logo_props: {},
    },
  });
  return (
    <FormProvider {...methods}>
      <ProjectCreateHeader handleClose={vi.fn()} />
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
});
