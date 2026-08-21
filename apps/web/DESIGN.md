---
name: Curve
description: An evidence-led control room built on Plane's embedded work-management system.
colors:
  curve-accent: "var(--background-color-accent-primary)"
  canvas: "var(--background-color-canvas)"
  surface: "var(--background-color-surface-1)"
  layer: "var(--background-color-layer-1)"
  layer-strong: "var(--background-color-layer-2)"
  text-primary: "var(--text-color-primary)"
  text-secondary: "var(--text-color-secondary)"
  text-tertiary: "var(--text-color-tertiary)"
  border-subtle: "var(--border-color-subtle)"
  success: "var(--background-color-success-primary)"
  success-subtle: "var(--background-color-success-subtle)"
  warning-subtle: "var(--background-color-warning-subtle)"
  danger-subtle: "var(--background-color-danger-subtle)"
  backdrop: "var(--background-color-backdrop)"
typography:
  headline:
    fontFamily: "Inter Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "2rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Inter Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: 1.5
  body:
    fontFamily: "Inter Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Inter Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.25
rounded:
  sm: "0.25rem"
  md: "0.375rem"
  lg: "0.5rem"
  xl: "0.75rem"
spacing:
  xs: "0.25rem"
  sm: "0.5rem"
  md: "1rem"
  lg: "1.25rem"
  xl: "1.5rem"
  2xl: "2rem"
components:
  button-primary:
    backgroundColor: "{colors.curve-accent}"
    textColor: "var(--text-color-on-color)"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "0 0.5rem"
    height: "2rem"
  button-secondary:
    backgroundColor: "{colors.layer-strong}"
    textColor: "{colors.text-secondary}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "0 0.5rem"
    height: "2rem"
  status-card:
    backgroundColor: "{colors.layer}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.xl}"
    padding: "1.25rem"
  mobile-navigation:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-primary}"
    rounded: "0"
    width: "min(20rem, calc(100vw - 3rem))"
---

# Design System: Curve

## Overview

**Creative North Star: "The Auditable Control Room"**

Curve presents complex product-delivery infrastructure as a calm, attributable
operating surface. The hierarchy leads with the current outcome, action, and
evidence; implementation detail remains available in progressive disclosure.
Curve owns the product shell and lifecycle language. Plane appears inside that
shell as the embedded work-management foundation, with visible attribution.

The visual system extends Plane's semantic tokens and Propel components. The
source of truth is [variables.css](../../packages/tailwind-config/variables.css)
(Plane semantic color, typography, elevation, and theme tokens), while
[PRODUCT.md](./PRODUCT.md) (Curve product purpose and shell commitments) defines
the ownership boundary. Curve surfaces preserve the same light, dark, and
high-contrast theme behavior.

**Key Characteristics:**

- Curve-first shell ownership with explicit Plane-backed work-management areas.
- Neutral layered surfaces with a restrained blue operational accent.
- Outcome-first summaries followed by ordered evidence and technical detail.
- Status communication that combines language, iconography, and color.
- Compact, responsive controls that preserve keyboard and screen-reader behavior.

## Colors

The palette uses Plane's theme-aware semantic roles so Curve remains legible and
recognizable across light, dark, and high-contrast modes.

### Primary

- **Curve Operational Blue** (`--background-color-accent-primary`): primary
  actions, active navigation, live-event markers, and current-work emphasis.

### Neutral

- **Workspace Canvas** (`--background-color-canvas`): application ground behind
  the shell and operational cards.
- **Primary Surface** (`--background-color-surface-1`): navigation, dialogs, and
  stable shell regions.
- **Evidence Layer** (`--background-color-layer-1`): status cards, progress
  panels, update panels, and collapsible technical detail.
- **Primary Ink** (`--text-color-primary`): headings, stage labels, and values.
- **Supporting Ink** (`--text-color-secondary`): explanatory copy and secondary
  controls.
- **Evidence Ink** (`--text-color-tertiary`): timestamps, metadata, and stage
  descriptions.

### Tertiary

- **Verified Green** (`--background-color-success-primary`): completed evidence
  and successful terminal outcomes.
- **Attention Amber** (`--background-color-warning-subtle`): waiting,
  reconnecting, and cancellation-requested states.
- **Diagnostic Red** (`--background-color-danger-subtle`): safe failure and
  request-error states.

### Named Rules

**The Semantic Token Rule.** Curve components consume semantic theme roles; the
light, dark, and high-contrast palettes remain centralized in Plane's token
system.

**The Redundant Status Rule.** Every state uses readable text and an icon in
addition to color.

## Typography

**Display Font:** Inter Variable with the shared system sans-serif fallback.

**Body Font:** Inter Variable with the shared system sans-serif fallback.

**Label/Mono Font:** IBM Plex Mono with the shared monospace fallback for
identifiers, versions, ETags, and safe diagnostics.

**Character:** The type system is compact and operational. A single strong
headline identifies the surface; restrained titles, body copy, labels, and mono
evidence support fast scanning without introducing a competing display voice.

### Hierarchy

- **Headline** (semibold, `2rem`, `1.25` line height): one page outcome or task.
- **Title** (semibold, `1.125rem`, `1.5` line height): summary-card outcomes and
  major local sections.
- **Body** (regular, `0.875rem`, `1.5` line height): explanations and recovery
  guidance, normally constrained to approximately 70 characters.
- **Label** (medium, `0.75rem`, `1.25` line height): status pills, metadata, and
  compact controls.
- **Evidence value** (regular mono, inherited size): opaque identifiers and
  machine-owned values that must remain copyable and distinguishable.

### Named Rules

**The One Outcome Rule.** Each operational surface has one `h1`; subsequent
headings describe evidence regions rather than restating the page title.

## Layout

Curve uses a persistent workspace shell on screens at or above the medium
breakpoint (`48rem`). The sidebar carries Curve branding and the Product,
Delivery, Work management, and Platform information architecture. Plane-backed
destinations remain grouped and attributed under Work management.

Below `48rem`, workspace navigation becomes a modal drawer rather than sharing
width with the content. The drawer uses a backdrop, traps focus through the
dialog primitive, closes with Escape or backdrop activation, and restores focus
to the invoking control. Its width is capped at `20rem` while leaving `3rem` of
the viewport visible as spatial context.

Foundation content uses a centered maximum width of `72rem`, `1.25rem` mobile
inline padding, and `2rem` padding from the small breakpoint. Primary sections
stack in reading order, then become a two-column evidence layout at the large
breakpoint (`64rem`). The progress region keeps the larger share of the row.

**The Shell Ownership Rule.** Curve branding, navigation, breadcrumbs, and
lifecycle language frame every enabled Curve workspace; Plane-backed records
remain reachable inside the Work management group.

## Elevation & Depth

Curve uses tonal layers, fine semantic borders, and low ambient shadows. Status
cards and evidence panels use the shared raised-100 shadow; modal dialogs use the
shared backdrop and panel boundary. Depth identifies interaction level and
containment while preserving a quiet operational field.

### Shadow Vocabulary

- **Raised evidence** (`--shadow-raised-100`): status, progress, update, and
  technical-detail containers.

### Named Rules

**The Evidence Above Chrome Rule.** Elevation distinguishes evidence regions and
modal interaction; navigation structure relies primarily on surface and border
contrast.

## Shapes

Compact controls and navigation rows use gently curved small or medium corners
(`0.25rem` to `0.375rem`). Operational cards and state icons use larger corners
(`0.75rem`), while status indicators and step markers use fully round geometry.
The mobile navigation drawer meets the viewport edge with square outside
corners, reinforcing that it belongs to the application shell.

## Components

### Buttons

- **Shape:** compact medium corners (`0.375rem`) with heights from `1.25rem` to
  `2rem` according to task density.
- **Primary:** Curve Operational Blue, on-color text, and a concise verb that
  names the action.
- **Secondary:** a bordered raised layer for cancellation entry, retry, and
  reversible alternatives.
- **Hover / Focus:** semantic hover roles and a visible focus treatment inherited
  from the Propel button primitive.

The implementation contract is [helper.tsx](../../packages/propel/src/button/helper.tsx)
(shared Propel button variants, states, and sizes).

### Cards / Containers

- **Corner Style:** large operational corners (`0.75rem`).
- **Background:** Evidence Layer for status and delivery evidence.
- **Shadow Strategy:** Raised evidence only.
- **Border:** semantic subtle borders; success, warning, and danger borders track
  the displayed state.
- **Internal Padding:** `1.25rem`, increasing to `1.5rem` for the main summary at
  the small breakpoint.

### Navigation

Curve's logo and workspace selector establish product and workspace context.
Navigation is grouped by lifecycle responsibility; unavailable future
destinations are visibly disabled and labeled Later. On mobile, navigation uses
the modal drawer semantics defined in Layout. The Plane foundation remains
explicit through the Plane-backed badge and source attribution.

### Foundation Status

The Foundation status surface is an evidence projection over one
`FOUNDATION_PROBE` Operation. It lists and retrieves only that Operation type;
unrelated Operations never populate its summary or cancellation control.

Progress stages represent evidence actually recorded for the current Operation.
Request acceptance and atomic recording complete first; workflow acceptance
completes only after a qualifying projection; cancellation and failure retain
the completed stages and identify the remaining or failed stage. Terminal
success completes all five stages.

The source link renders only when configured with an exact 40-character public
Git commit SHA. Missing or mutable revisions fail closed to a non-link source
unavailable label. The detailed surface contract is the
[Foundation status surface brief](./.impeccable/surfaces/core-components-curve-curve-foundation-status-tsx.md)
(M0-S4 audience, interaction, evidence, and legal-attribution rules).

## Do's and Don'ts

### Do:

- **Do** lead with the current outcome and next available action.
- **Do** preserve the Curve-first shell around Plane-backed work-management
  capabilities.
- **Do** derive progress from the current Foundation Operation and its observed
  delivery evidence.
- **Do** use modal drawer semantics for Curve navigation below `48rem`.
- **Do** bind AGPL source attribution to an exact immutable public commit.

### Don't:

- **Don't** use an unrelated Operation as Foundation status or cancellation
  state.
- **Don't** infer completed workflow or worker stages from cancellation or
  failure alone.
- **Don't** allow a narrow viewport sidebar to compress the Foundation content.
- **Don't** render a source link for a branch name, short SHA, or missing
  revision.
- **Don't** present Plane as the owning product shell when Curve is enabled.
