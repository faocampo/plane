# Manual plan candidate — documenter handoff

Disposition: preserve the incumbent design system. The supplied finish-review disposition is **ship** for this unmounted UI/client candidate with synthetic mocked data, with no material fixes requested. This documenter pass supports that bounded handoff; backend qualification and protected-definition preparation remain separate release gates. No browser or server was started, and no backend was reviewed.

## Evidence checked

- `apps/web/core/components/curve/initiatives/manual-plan-panel.tsx` (manual draft state, prepared-save controls, revision evidence, and recovery rendering) uses existing semantic colors, shared Propel buttons, Lucide icons, visible focus, and native disclosure semantics.
- `apps/web/.impeccable/surfaces/s-curve-initiatives-manual-plan-panel-tsx-3b4c57bc.md` (approved local direction and unmounted candidate constraints) is reflected in the outcome-first heading, explicit unapproved state, responsive actions, disclosed revision evidence, and retained same-save retry action.
- `apps/web/PRODUCT.md` (Curve product ownership, accessibility, and accountability principles), `apps/web/DESIGN.md` (incumbent Auditable Control Room design system), `apps/web/.impeccable/design.json` (incumbent design-system extensions), and `packages/tailwind-config/variables.css` (shared semantic theme and typography tokens) were compared with the candidate source.
- `apps/web/.impeccable/review/manual-plan/desktop.png` (saved draft with expanded evidence at desktop width), `apps/web/.impeccable/review/manual-plan/mobile.png` (saved draft with stacked metadata at mobile width), `apps/web/.impeccable/review/manual-plan/desktop-empty.png` (first-draft guidance), `apps/web/.impeccable/review/manual-plan/mobile-unavailable.png` (unavailable draft with disabled save), and `apps/web/.impeccable/review/manual-plan/mobile-unknown.png` (uncertain save with deliberate retry) were visually inspected. Text, actions, and metadata remain legible in the supplied states.
- `apps/web/.impeccable/review/manual-plan/measurements.json` (capture errors, viewport widths, rendered text, and computed colors) reports no errors and equal viewport/scroll widths for all five captures: 1440px desktop and 390px mobile. `.curve-local/verification/manual-plan-design-detect.json` (candidate design detector findings) contains an empty findings array.

## System summary

1. Palette: shared neutral surfaces, semantic primary and secondary ink, subtle borders, and the restrained blue primary action remain authoritative.
2. Type: shared Inter typography supplies the local 18px semibold section title, 14px body, and 13px metadata; the existing code treatment distinguishes digests.
3. Layout and shape: the candidate uses a 12px outer radius, 20px/24px inset, wrapping actions, and metadata that stacks below the small breakpoint; these local choices do not create new global rules.
4. Named rules: the Semantic Token Rule, Redundant Status Rule, and One Outcome Rule remain applicable; the panel contributes a section heading beneath the parent outcome heading.
5. Interaction and evidence: focus rings, native revision disclosure, text-and-icon status, and explicit save/approval separation carry the existing outcome-first operational character. There are no shipping raster assets.

## Preservation and non-canonized drift

No design-system edits were needed. `apps/web/PRODUCT.md` (product commitments), `apps/web/DESIGN.md` (normative incumbent tokens and visual rules), and `apps/web/.impeccable/design.json` (incumbent extension metadata and component examples) were left unchanged by this pass.

The existing sidecar places component examples and narrative under its extension object, includes a glyph in the Foundation status example, and paraphrases its overview. These pre-existing differences from the current documenter specification were not repaired or adopted as new rules: this task authorizes an ordinary local extension, not a system refresh. The supplied captures establish only the listed synthetic preview states; they do not establish backend correctness or a complete theme/accessibility qualification.
