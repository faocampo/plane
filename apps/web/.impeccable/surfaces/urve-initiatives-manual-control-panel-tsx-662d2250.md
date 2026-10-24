---
version: 1
slug: "urve-initiatives-manual-control-panel-tsx-662d2250"
primary_target: "apps/web/core/components/curve/initiatives/manual-control-panel.tsx"
related_targets: ["apps/web/core/components/curve/initiatives/initiative-workspace.tsx"]
---

# Manual plan review and reservations

Scope: ordinary extension of the Initiative workspace; Operate mode. An authenticated viewer reviews an authorized plan definition, records a human decision and manages task reservations. The source entry is mounted but disabled unless `VITE_CURVE_MANUAL_PLAN_V2_ENABLED` is exactly `true`, and is restricted to `PLANNING`, `PAUSED` or `CANCELLED`.

## Direction contract

THESIS: Make the current plan state, next decision and reservation consequences immediately readable; approval never starts execution.

OWN-WORLD: Extend Curve's neutral Plane semantic surfaces, operational blue accent, Inter typography and compact Propel controls. Preserve the inherited system without new tokens, assets or visual identity.

STORY: Read protected material explicitly, inspect reservations, choose authorized decision evidence and confirm review. Release follows reconciliation; pause and cancellation retain reservations until explicit release.

FIRST VIEWPORT: The Manual plan heading and explanation precede the text-and-icon status and Refresh control. Definition disclosure, reservations, next decision and evidence follow in that order, wrapping naturally on mobile.

FORM: Ordinary code-led extension; no seed or comp applies. Signature interaction: identity/version changes and renewed focus clear prior protected content before replacement reads; access failures and uncertain outcomes hide it. A pending command remains only in session memory for deliberate retry.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, [DESIGN.md](../../DESIGN.md) (preserved inherited visual system), and every shipping raster carrying its provenance.

## Implementation and boundaries

- [manual-control-panel.tsx](../../core/components/curve/initiatives/manual-control-panel.tsx) (protected preparation, plan review, reservations, reconciliation and retry) owns this surface; [initiative-workspace.tsx](../../core/components/curve/initiatives/initiative-workspace.tsx) (authenticated Initiative detail integration) mounts its default-off entry.
- [manual-plan-panel.tsx](../../core/components/curve/initiatives/manual-plan-panel.tsx) (saved draft metadata and revision history) is nested only when current protected preparation is available. Its [existing brief](./s-curve-initiatives-manual-plan-panel-tsx-3b4c57bc.md) (draft-specific interaction contract) remains distinct.
- Material bodies require explicit reads. The interface checks current versions, matching evidence, human confirmation and selected reservations; each API remains responsible for authorization. Release also requires a reconciliation reference. Approval reserves tasks and does not execute work.
- Identity-keyed sessions and stable target values prevent prior-view metadata from surviving a context change. Refresh and material reads are blocked while a command is pending. Unknown outcomes retain the same command payload, expected version and idempotency key in memory; remounting discards it. No browser storage is used for protected material or commands.
- [review.md](../review/manual-gate2/review.md) (complete initial review) requested state iconography only. [verdict.md](../review/manual-gate2/verdict.md) (scoped iconography verdict) records resolved/ship for that correction. [documentation.md](../review/manual-gate2/documentation.md) (evidence, preserved system and qualification limits) records this documentation pass.
- The five screenshot states and [measurements.json](../review/manual-gate2/measurements.json) (1440/390 px synthetic preview measurements) are mock evidence. They do not qualify the live route, server authorization or browser/backend integration. Final integrated qualification remains a separate release gate; this brief does not enable the feature.
