---
version: 1
slug: "core-components-curve-curve-foundation-status-tsx"
primary_target: "core/components/curve/curve-foundation-status.tsx"
related_targets:
  [
    "core/components/curve/curve-foundation-state.ts",
    "core/components/curve/curve-mobile-navigation.tsx",
    "core/components/curve/curve-source-link.tsx",
    "core/components/curve/curve-workspace-sidebar.tsx",
    "core/hooks/use-curve-foundation.ts",
  ]
---

# Curve Foundation Status Surface Brief

## Scope and visitor mode

- **Mode:** Operate.
- **Audience:** an authorized workspace engineer or platform operator validating
  Curve's local M0 control path.
- **Job:** run one harmless Foundation probe, follow its durable state, recover
  the stream, cancel safely, and verify the terminal outcome.
- **Primary action:** Run foundation probe, or Run again after a terminal state.
- **Proof:** ordered progress stages, resumable live updates, immutable Operation
  identifiers and versions, and a safe terminal result.

## Shell and navigation contract

Curve owns the application identity, global workspace navigation, breadcrumb
language, and lifecycle grouping. Plane-backed projects, views, analytics, and
collaboration records live inside Curve's Work management group with visible
Plane attribution.

At widths below `48rem`, navigation is a modal drawer. It overlays the content,
renders a backdrop, traps focus, responds to Escape and backdrop activation, and
returns focus to the invoking navigation toggle. Selecting a Curve destination
also closes the drawer. Desktop navigation remains persistent and resizable.

## Operation isolation contract

The surface lists, retrieves, streams, and cancels only Operations whose
`operation_type` is `FOUNDATION_PROBE`. The list request uses the server-side
operation-type filter before selecting the latest result. A mismatched detail
projection is discarded. The cancellation action also checks the type before
issuing a mutation.

This contract prevents an unrelated workflow, research, or future delivery
Operation from being labeled or cancelled as the Foundation probe.

## Evidence and progress contract

Operation state is authoritative; SSE is the resumable delivery projection.
Progress communicates evidence already recorded for the current Operation:

1. Request accepted: the authorized command returned the Operation.
2. Operation recorded: the Operation and delivery event committed atomically.
3. Workflow started: a qualifying queued, running, waiting, or successful
   projection proves Temporal acceptance.
4. Worker completed: successful terminal evidence proves the synthetic activity
   completed.
5. Status received: the successful terminal projection reached the browser.

Cancellation preserves completed stages and leaves later stages waiting. Failure
preserves completed stages and marks the next evidenced stage as failed. The UI
does not convert terminal cancellation or failure into implied completion.

## State and recovery contract

- Connection health is visible as Connecting, Updates live, Reconnecting,
  Resync required, or Updates offline.
- A stale resume cursor exposes a deliberate Resync status action.
- Safe Problem Details preserve the last confirmed state and expose a retry.
- Cancellation uses a modal confirmation with initial focus on Keep running and
  focus restoration to the Cancel probe trigger.
- Status, progress, and errors combine text, iconography, and semantic color.
- Motion respects reduced-motion preferences.

## AGPL source contract

Visible source attribution resolves to the configured public Plane-fork
repository at an exact 40-character Git commit SHA. A missing revision, branch
name, or short SHA produces a non-interactive source-unavailable label. This
fail-closed behavior prevents a deployed Curve surface from claiming a mutable
or unverifiable source revision.

## Implementation evidence

- [curve-foundation-status.tsx](../../core/components/curve/curve-foundation-status.tsx)
  (Foundation outcome, evidence, recovery, cancellation, and technical-detail UI).
- [curve-foundation-state.ts](../../core/components/curve/curve-foundation-state.ts)
  (contract validation and evidence-based progress projection).
- [use-curve-foundation.ts](../../core/hooks/use-curve-foundation.ts)
  (Foundation Operation isolation, API state, SSE resume, and cancellation).
- [curve-mobile-navigation.tsx](../../core/components/curve/curve-mobile-navigation.tsx)
  (responsive modal workspace-navigation drawer).
- [curve-source-link.tsx](../../core/components/curve/curve-source-link.tsx)
  (immutable public source-revision validation and attribution).
- [DESIGN.md](../../DESIGN.md) (Curve visual-system and shell-ownership contract).

## Unresolved decisions

None within M0-S4. Future Curve surfaces may extend the lifecycle navigation and
evidence model through their own approved work-package contracts.
