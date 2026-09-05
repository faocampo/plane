# Curve

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Curve serves Example Organization product owners, delivery leads, engineers, agent operators,
technical approvers, quality approvers, and code approvers. The M0-S4
(API, SSE, and minimal Curve-first UI implementation packet) surface is for an
authorized workspace engineer or platform operator validating the local Curve
control path.

## Product Purpose

Curve is the organization’s AI-native product-development platform. It coordinates product
definition, planning, implementation, quality, and delivery evidence through
durable, accountable workflows. The local Foundation status surface lets an
authorized engineer create one harmless synthetic Operation, follow it through
the delivery kernel and Temporal worker, recover its event stream, cancel it
safely, and verify the terminal result.

## Positioning

Curve is the product users enter. It combines a Curve-owned product lifecycle,
governed evidence, human gates, and agent execution with Plane's embedded native
work-management capabilities. Plane remains authoritative for its projects,
work items, cycles, views, analytics, and collaboration records.

## Operating Context

- Curve is implemented additively in the public Plane fork.
- M0 runs locally in the existing Plane Docker stack with PostgreSQL and the
  approved Temporal development profile.
- The Curve shell is disabled by default and enabled only for allowlisted
  workspaces.
- M0-S4 uses synthetic internal data and a local-only Foundation probe.
- Operation state is authoritative; resumable server-sent events are a delivery
  projection.
- GitHub Project status is visual progress metadata.

## Capabilities and Constraints

- The Foundation probe supports authorized create, read, cancel, ordered event
  streaming, reconnect, stale-cursor resynchronization, and safe retry.
- Mutations require idempotency, current optimistic versions, audited policy
  evaluation, and workspace authorization.
- Errors use safe RFC 9457 Problem Details and exclude raw exceptions, protected
  bodies, credentials, stack traces, SQL, and cross-workspace identifiers.
- The probe action is unavailable outside local development.
- M0-S4 does not add initiative management, evidence management, provider
  configuration, WebSockets, production probing, merge, or deployment behavior.
- Existing Plane behavior remains unchanged while Curve is disabled.

## Brand Commitments

- Curve owns the primary product name, logo, application shell, global
  navigation, breadcrumbs, and lifecycle terminology.
- Plane-backed capabilities appear within Curve under Work management with
  visible Plane attribution and the required open-source notices/source link.
- The approved Curve logo geometry and assets are governed by
  `curve-brand.md` (approved Curve logo assets, usage rules, and derivative policy).
- The Foundation status information architecture is Product, Delivery, Work
  management, and Platform, with Foundation status under Platform.

## Evidence on Hand

- Curve PR #17: approved Curve-first shell, UX-004-M0-S4 (clickable prototype
  and task-based review), and UX-005-M0-S4 (work-package-linked screen contract).
- `curve-ai-native-sdlc-prd.md` (Curve product requirements and lifecycle contract).
- `ux-m0-s4-foundation-probe.md` (approved Foundation status flow, states,
  interaction bindings, and browser acceptance).
- `curve-foundation-probe-v2.png` (approved desktop success-state reference).
- `index.html` (approved clickable Foundation status prototype).
- `curve-v1.openapi.yaml` (normative Curve M0 API contract).
- No customer, commercial, production-readiness, or performance claim is implied
  by the synthetic local Foundation probe.

## Product Principles

1. Show the user's decision and current outcome before infrastructure detail.
2. Preserve exact workspace, artifact, policy, and commit attribution.
3. Keep irreversible or material decisions human-accountable.
4. Make retries, cancellation, reconnection, and recovery explicit and safe.
5. Extend Plane without repurposing or weakening its native behavior.

## Accessibility & Inclusion

User-facing Curve flows conform to WCAG 2.2 AA. The Foundation status flow must
work with keyboard-only navigation, visible focus, correctly restored dialog
focus, semantic headings and controls, non-color status cues, polite live-region
updates, reduced-motion preferences, and safe error recovery.
