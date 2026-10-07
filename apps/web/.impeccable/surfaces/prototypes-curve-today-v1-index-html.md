---
version: 1
slug: "prototypes-curve-today-v1-index-html"
primary_target: "prototypes/curve-today-v1/index.html"
related_targets: ["prototypes/curve-today-v1/today.css", "prototypes/curve-today-v1/today.js"]
---

# Today decision queue prototype

Operate-mode extension of Curve Home for the assigned technical approver: find a
pending decision and reach its Initiative's versioned plan and evidence. Synthetic,
read-only, local prototype; no app integration, live requests or approval writes.
The inherited Home surface remains the visual authority. UX-004 (clickable task
review) and UX-005 (screen contract) still require representative human review.

## Direction contract

THESIS: Make one person's current decision findable in a direct attention row.
No productivity scores or invented roll-up metrics.

OWN-WORLD: Existing Curve shell, neutral dark layers, blue action, Inter, compact
bordered rows. Preserve the approved logo and Plane attribution. Match the demo's
dark workspace for an approver returning to the same desktop or phone session.

STORY: Identify workspace and principal, understand why review is available, open
the exact Initiative, and read its plan and supporting evidence. Authority is
rechecked at the destination; the queue never grants it.

FIRST VIEWPORT: Persistent desktop sidebar; compact heading and access context;
attention queue on the left and role context on the right. One Review plan action.
On mobile the queue comes first and navigation moves into a modal drawer.

FORM: Local extension of the incumbent Home row composition; no concept seed or
new visual world. Signature interaction: a row opens the versioned destination
and Back restores the selected queue scenario. Only the mobile drawer has a brief
entry motion, disabled for reduced motion.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Required states

Current, loading, confirmed empty, partial, stale, failed and revoked access.
Partial results have no total; stale rows cannot open evidence; revoked access
clears titles and details. Fixture controls are visually separate from product
controls. Technical approver, owner and code reviewer produce distinct queues.
No action or count is inferred from a role label in the production contract.

## Boundaries

The prototype demonstrates navigation and copy, not backend queue delivery,
authentication, native authorization, operational acceptance or human UX sign-off.
The documented global design system remains unchanged.
