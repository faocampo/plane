---
version: 1
slug: "s-curve-initiatives-manual-plan-panel-tsx-3b4c57bc"
primary_target: "apps/web/core/components/curve/initiatives/manual-plan-panel.tsx"
related_targets: []
---

# Manual plan draft panel

Scope: local extension of the Initiative workspace; Operate mode. The user reviews saved draft metadata and saves an already prepared protected definition. This candidate is not mounted in a live route; server qualification and the protected preparation flow remain release gates.

## Direction contract

THESIS: Make the boundary between a saved draft and approved work unmistakable. Lead with the draft state and one next action, then let the reader inspect revision evidence.

OWN-WORLD: Inherit Curve's neutral Plane semantic surfaces, blue primary action, Inter body type, compact Propel buttons and visible keyboard focus. No new design system or raster assets.

STORY: The reader sees whether a draft exists, checks the current revision and can save a prepared change. Refresh clears old protected information; an uncertain save keeps its command identity available for deliberate retry.

FIRST VIEWPORT: One section heading and status sentence, followed by a compact definition/revision summary. Save and Refresh sit beside the summary on desktop and wrap below it on mobile. History is a disclosed predecessor chain, without protected body previews or approval controls.

FORM: Ordinary extension, code-led incumbent. No seed applies to this local addition. Signature interaction: stale or inaccessible metadata disappears before a replacement request completes.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Constraints

Use synthetic preview data. Saving is manual and never starts execution, reserves tasks or grants approval. Do not mount or enable the candidate until backend qualification. Client checks never substitute for server authority. No browser storage of protected data or commands.
