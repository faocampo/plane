---
{
  "name": "Curve document review implementation checkpoint",
  "description": "Scoped PRD context, connected Technical review and two-stage navigation.",
  "colors":
    {
      "ink": "#22283d",
      "muted": "#60677c",
      "action": "#444ed9",
      "tint": "#eeefff",
      "selection": "#dfe2ff",
      "primary-hover": "#343eb8",
      "canvas": "#f7f8fc",
      "line": "#e6e8f1",
      "paper": "#ffffff",
      "approved": "#227455",
      "changes": "#96610d",
      "warning": "#fff4df",
    },
  "typography":
    {
      "headline":
        {
          "fontFamily": '"Curve Manrope", sans-serif',
          "fontSize": "24px",
          "fontWeight": 800,
          "lineHeight": 1.35,
          "letterSpacing": "-0.025em",
        },
      "body": { "fontFamily": '"Curve Manrope", sans-serif', "fontSize": "14px", "lineHeight": 1.65 },
      "label": { "fontFamily": '"Curve Manrope", sans-serif', "fontSize": "12px" },
    },
  "rounded":
    { "version": "6px", "control": "8px", "notice": "10px", "stage": "12px", "panel": "14px", "canvas": "16px" },
  "spacing":
    { "tight": "8px", "control": "12px", "compact": "16px", "canvas": "20px", "panel": "24px", "document": "28px" },
  "components":
    {
      "button-primary":
        {
          "backgroundColor": "{colors.action}",
          "textColor": "{colors.paper}",
          "rounded": "{rounded.control}",
          "padding": "12px 16px",
          "width": "100%",
        },
      "button-primary-hover": { "backgroundColor": "{colors.primary-hover}" },
      "saved-note-select":
        {
          "backgroundColor": "{colors.paper}",
          "textColor": "{colors.ink}",
          "rounded": "{rounded.control}",
          "padding": "8px 12px",
          "width": "100%",
        },
      "refresh": { "textColor": "{colors.action}", "rounded": "{rounded.control}", "padding": "8px 12px" },
      "stage-tab":
        {
          "backgroundColor": "{colors.paper}",
          "textColor": "{colors.ink}",
          "rounded": "{rounded.stage}",
          "padding": "16px",
        },
      "version-chip":
        {
          "backgroundColor": "{colors.tint}",
          "textColor": "{colors.action}",
          "rounded": "{rounded.version}",
          "padding": "3px 9px",
        },
      "review-panel": { "backgroundColor": "{colors.paper}", "rounded": "{rounded.panel}", "padding": "24px" },
      "status-notice":
        {
          "backgroundColor": "{colors.tint}",
          "textColor": "#414b8b",
          "rounded": "{rounded.notice}",
          "padding": "14px",
        },
    },
}
---

# Design System: Curve document review implementation checkpoint

## Overview

**Creative North Star: "The Shared Review Desk"**

The Shared Review Desk places a white document surface and a compact reviewer surface on a cool light canvas. Indigo gives navigation and refresh a consistent emphasis; green and amber distinguish recorded decisions with accompanying text. Manrope supplies a shared reading rhythm within this scoped review area.

This record captures the read-only PRD context, two-stage navigation shell and connected Technical v3 implementation checkpoint. For schema 1.2 Initiatives in eligible lifecycle states, the independent `VITE_CURVE_MANUAL_PLAN_V3_ENABLED` flag selects the Technical panel. Earlier schemas retain their historical manual-control path and separate v2 flag. Technical preparation, saved draft versions, saved-note decisions and exact-command recovery are connected in code. Full PRD upload and authoring, typed feedback ingestion and authenticated application acceptance remain pending. Approved prototype direction, this implementation checkpoint and full UX acceptance retain separate evidence scopes.

Sources: [prd-review-panel.tsx](prd-review-panel.tsx) (read-only PRD context and review status), [prd-review-panel.css](prd-review-panel.css) (document and reviewer styling), [document-review-stages.tsx](document-review-stages.tsx) (two-stage keyboard navigation), and [document-review-stages.css](document-review-stages.css) (scoped Manrope, canvas and stage styling). Additional implementation sources: [technical-review-panel.tsx](technical-review-panel.tsx) (current Technical materials, decisions and recovery), [technical-review-panel.css](technical-review-panel.css) (scoped interaction styles), [manual-plan-panel-v3.tsx](manual-plan-panel-v3.tsx) (current draft loading and version history), [manual-plan-content.tsx](manual-plan-content.tsx) (readable plan sections and source disclosure), and [initiative-workspace.tsx](initiative-workspace.tsx) (schema and independent feature-flag routing). The approved sibling prototype design and approval record supply visual direction; implementation source supplies this checkpoint’s behavior and values. [PRODUCT.md](../../../PRODUCT.md) (application product context and durable accessibility commitments) retains its independent scope.

**Key Characteristics:**

- Document context leads; reviewer status follows.
- Two visible stage choices describe Product and Technical approval.
- Evidence stays collapsed until requested.
- Styles remain scoped to the document review area.

## Colors

### Primary

Action indigo marks refresh, selected stages and focus. Pale tint groups version context and explanatory notices. The Technical extension adds selection for readable highlighted text and primary-hover for the main decision button. These two intentional interaction colors preserve the incumbent palette and are recorded in the frontmatter.

### Secondary

Approved green marks approval icons. Changes amber marks requested-change and rejected states; the pale warning surface supports assignment and synchronization guidance. Status text carries the meaning alongside color.

### Neutral

Ink, muted ink, paper, canvas and line distinguish reading content, metadata and surface boundaries. The frontmatter owns the extracted values.

## Typography

The review wrapper loads locally hosted Curve Manrope in weights 400 through 800, with sans-serif fallback. Headline text uses the headline token; body copy uses the body token and a 65ch maximum paragraph width. Metadata uses the label token. Section headings use 17px at weight 700; toolbar titles use 14px at weight 700. Version numbers use tabular numerals.

## Layout

A scoped canvas wraps two equally sized stage tabs, followed by the selected panel. The PRD region has an inline-size container: at 740px and above its grid places the flexible document on the left and a 280px reviewer column on the right, separated by 24px. Below that container width it stacks document first, reviewer second. At container widths up to 400px, document and reviewer padding reduce to 20px and toolbar padding to 16px.

At viewport widths up to 600px, stage controls wrap, reduce their gap and padding, and hide the numeric stage suffix. The stage names and approval roles remain visible. Evidence disclosure uses native details elements, initially collapsed.

## Elevation & Depth

Paper panels use a restrained ambient shadow (`0 6px 26px #29335509`). Cool dividers separate the document toolbar, reviewer identity and evidence. Stage background and border transitions take 160ms with ease timing; reduced-motion preference removes those transitions.

## Shapes

Panels use the panel radius, stage controls the stage radius and notices the notice radius. Version chips remain compact. Reviewer avatars are circular. Refresh and evidence summary controls provide a minimum 44px target height; stage controls have an 88px minimum height.

## Components

### Refresh

The quiet indigo text control refreshes read-only context. Hover adds a pale tint. Loading disables refresh and changes the cursor to waiting. Keyboard focus uses an indigo 3px outline with 3px offset.

### Stage navigation

Two labeled tabs select Product requirements and Implementation plan. Arrow keys, Home and End move selection and focus. Selected stages use an indigo border and pale fill. The shell accepts independently resolved panel content; selection carries navigation meaning.

### Document and reviewer surfaces

The document toolbar holds its label, submission metadata and version chip. The body presents accessible checkpoint context. The reviewer surface shows the assigned reviewer and recorded decision, including unavailable and assignment-warning states. Document content and private feedback retain their separate access requirements.

### Evidence and notices

Version and evidence details, plus review prerequisites, expand on demand. Status notices explain access and action availability. The PRD checkpoint provides read-only refresh and navigation. The connected Technical checkpoint adds the controls described below; broader PRD authoring and typed feedback ingestion remain pending.

### Technical review and current versions

The Technical panel automatically loads preparation, review status, referenced plan content and available saved decision notes. Matching current versions and reference fingerprints govern display. Readable sections put plan outcomes, scope, acceptance checks and recovery before the expandable technical source. Refresh and return-to-window refresh reload current context; in-flight or uncertain decisions preserve their recovery state.

The compact reviewer surface shows the assigned Technical reviewer, current status and server-allowed decisions. Decision choices wrap with a pale selected fill and indigo border. Decisions use an existing saved note for the selected intent; when only one matching note exists it is selected automatically. The saved-note selector is a full-width paper control with a subtle border, control radius and a 44px minimum height. Typed note creation remains pending.

The full-width primary control uses action indigo, paper text, 700 weight and control radius. Hover uses primary-hover; disabled state uses line and muted ink. Focus is a 3px indigo outline with a 3px offset. Native task checkboxes support applicable reservation actions with explicit labels.

Prepared plans can be saved or replaced within their disclosed section. Draft status automatically loads the matching current revision; older revisions are available through version history. Saving a draft and recording a Technical decision remain separate steps. Uncertain decisions expose “Recover decision”, which reuses the exact pending command, expected version and idempotency key. Uncertain draft saves expose “Retry same save”. While a draft save is in flight or has an unknown outcome, the child reports its pending state to the Technical panel: refresh, focus refresh, prepared-plan switching and Technical decisions wait for exact retry recovery. This keeps refresh from unmounting the pending draft. Pending recovery is session-local; component unmount clears its in-memory command. Version conflicts require refreshing current material before another decision.

## Do's and Don'ts

### Do:

- Do keep document content before reviewer status on narrow screens.
- Do pair decision colors with explicit status text.
- Do retain visible version context and collapsed evidence.
- Do preserve the surrounding application conventions outside this scoped surface.

### Don't:

- Do not interpret stage selection as approval or authority.
- Do not present connected Technical decisions as completed PRD upload, authoring, typed feedback ingestion or authenticated application acceptance.
- Do not infer full interface acceptance, merge, deployment or a global Plane theme change from this record.

## Local uploaded PRD integration checkpoint

The schema1.2 Product surface can use the local-upload panel behind `VITE_CURVE_LOCAL_PRD_ENABLED`. It shares the approved document-first layout, color palette, focus treatment and responsive hierarchy. File selection immediately uploads PDF/Markdown/text up to10MiB; its label and hint explain this action. The panel displays verified text as escaped plain text and PDFs in a sandboxed viewer with a download fallback. Document status currently reports saved upload versions; Product submission and approval wiring remains pending and is stated explicitly. Unknown upload outcomes retain the exact in-memory command for an explicit retry. Identity or Initiative-version changes remount and clear protected content; refresh cancels stale reads and revokes PDF URLs.

Component tests cover upload/read flow, exact uncertain retry, file validation, read-only access, inert markup and identity clearing. Full rendered desktop/mobile inspection and authenticated end-to-end acceptance of this added panel remain pending. Detector palette advisories refer to the stale root sidecar; the colors used here are already present in this scoped approved palette.

## Approved Initiative review desk — 2026-10-22

The owner approved the two-stage interface: Product reviews the PRD and Technical reviews the implementation plan. The Initiative route now extends the shared review desk palette to its canvas, navigation and controls. The selected Initiative uses the full content width. Search, portfolio filters and the Initiative list live in the initially collapsed **Find an Initiative** disclosure; filtered navigation and an empty selection expand it. Review responsibilities and supporting Initiative details expand separately. Draft, pause, resume and cancellation controls retain their existing authority requirements.

[initiative-workspace.css](initiative-workspace.css) (route-scoped palette and full-width composition) supplies the approved light colors without changing a saved theme preference. [local-document-review.tsx](local-document-review.tsx) (current Product and Technical status summaries) displays each stage's independently loaded status. The source panels connect uploads, submission, approval and requested-change feedback to native local APIs. An approval belongs to its exact document and submission; navigation never creates an approval.

Verification: 489 frontend tests across 36 files passed after the layout change. The authenticated initial screen was inspected locally. Complete authenticated upload and decision acceptance, responsive application inspection and publication remain pending at this checkpoint.

## Document readability and responsive confirmation — 2026-10-22

[local-document-text.tsx](local-document-text.tsx) (safe, structured uploaded Markdown previews) renders document headings below the application heading hierarchy, lists, emphasis and safe links. Raw HTML stays inert; image descriptions replace embedded images. Plain-text documents retain literal formatting. Markdown above 256,000 characters uses the same plain-text view to bound synchronous parsing. Styles use the existing review desk palette and typography.

Desktop and 390-pixel mobile application renders were inspected. Documents stack above reviewer status on mobile. A route-scoped correction keeps search and account controls within the mobile top bar. The two-stage replacement flow has authenticated evidence. A newly created Draft still requires resolution of the existing-work scope prerequisite before document upload; seeded walkthrough evidence does not close this onboarding gap.

## Current connected experience — 2026-10-22

This section updates the pending implementation and onboarding statements in the earlier checkpoints. A newly created Initiative can upload its PRD without an existing-work scope selection. The owner submits the document for Product review; requested changes remain visible beside the document, and a replacement can be submitted for renewed approval. Product approval unlocks implementation-plan upload and Technical review. Both stages support protected typed feedback and exact-version replacement. Updating an approved PRD requires renewed Product approval and a replacement Technical plan; prior decisions retain their original document versions.

Authenticated walkthroughs completed both stages for a new Initiative, including requested changes, replacement, resubmission and approval. The approved-PRD reopening walkthrough also completed renewed Product and Technical reviews. The current frontend regression passed 511 tests across 37 files. Remaining application acceptance and publication checks are tracked in [approved-interface-remediation.md](../../../../../docs/curve/approved-interface-remediation.md) (verification evidence and outstanding checks). The earlier checkpoint paragraphs retain their dated evidence scope.
