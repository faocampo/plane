# Today: proposed decision queue

Open [prototype](index.html) (isolated synthetic Home-to-plan journey) in a browser.
It works from disk, loads repository-local fonts and the approved Curve logo,
and makes no API calls. Its source-attribution link explicitly opens the already
published Plane foundation revision. No authentication secret is needed.

This is a proposed extension of existing Home, not a live queue. It neither
integrates into the application nor records an approval. The example does not
represent current demo state. Human UX-004 (task review) and UX-005 (screen
contract acceptance) remain pending.

## Proposed screen contract

| Element                   | Production authority and behavior                                                                                                                                                                                    |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Workspace and principal   | Active session and selected workspace; clear all previous actor/workspace cache on switch or revocation. A displayed role label cannot authorize an action.                                                          |
| Assigned queue            | Only Initiatives the current principal can access and whose native current `allowed_actions` includes the relevant decision. Gate 2 technical review is the first bounded slice; do not extrapolate to all gates.    |
| Pending row               | Exact Initiative, gate, manual state, source revision and current version. A direct route preserves the queue context; its destination revalidates actor, access, evidence and version.                              |
| Count                     | Confirmed complete results only, covering every cursor page. Partial or failed sources have an unknown total. Never count another user's or workspace's pending decisions.                                           |
| Plan and evidence         | Read through the existing protected reader. Summaries cannot substitute for reading the exact material. The prototype bodies and identifiers are explicitly fictional.                                               |
| Decision write            | Remains in the Initiative's existing explicit confirmation flow with current version, allowed action, protected rationale, idempotency and native checks. No auto-approval, title inference or queue write shortcut. |
| Refresh                   | Revalidate current principal and source facts. Retained stale data is labelled and cannot grant action. Retry must not replay a decision.                                                                            |
| Roadmap and personal work | This queue does not invent Roadmap Item bindings. My work and Inbox retain task and notification ownership.                                                                                                          |

The backend queue transport and bounded aggregation strategy are **not yet
selected or implemented**. Do not ship an unbounded per-Initiative fan-out, a
global privileged snapshot, or reuse an operation creator's access. Define cursor
stability, per-source failure reporting, current-actor cache keys and freshness
before integration; use the native object/gate policy as the decision authority.

## State and interaction inventory

Use Prototype controls to select current, loading, empty, partial, stale, failed
or revoked access. The technical approver has one fictional current decision;
owner and code reviewer have no eligible approval in this fixture. These are
demonstration values, not an authorization implementation.

- Current: one Review plan action opens the versioned destination and evidence.
- Loading: no count and no decision action while current facts are unresolved.
- Empty: explicitly confirmed absence, distinct from unavailable results.
- Partial: verified row remains visible; total unknown and source gap explicit.
- Stale: earlier content labelled; refresh required before evidence navigation.
- Failed: no implied zero, with a retry that only changes the local fixture.
- Revoked: remove titles and evidence immediately, including an open detail route.
- Mobile: modal navigation closes with Escape/backdrop and restores focus.
- Keyboard: skip link, visible focus, native selects/disclosures and route heading
  focus; reduced motion disables the drawer transition.

The narrow preview uses the current dark demo language and local Inter assets.
Integrated light/dark/high-contrast coverage and production component reuse remain
integration requirements; a dark static prototype is not evidence of all themes.

## Automated qualification

[Browser record](browser-qualification.json) (29 passing Chromium checks) covers
the synthetic journey, role and availability fixtures, removal of revoked detail,
mobile focus containment, Escape/backdrop recovery and reduced motion. It observed
zero JavaScript errors and zero network requests. Desktop and mobile captures and
the fresh design review are preserved under
[review evidence](../../.impeccable/review/curve-today-v1/) (screenshots and scoped
finish/documentation records). The design review disposition is `ship` for this
isolated review artifact; it does not accept the product gates below.

To reproduce, use [browser verifier](verify.mjs) (local fixture and keyboard
checks) with an existing Puppeteer installation; `CURVE_PUPPETEER_MODULE` selects
its module path without downloading dependencies:

```sh
CURVE_PUPPETEER_MODULE=EXISTING_PUPPETEER_MODULE node \
  apps/web/prototypes/curve-today-v1/verify.mjs \
  apps/web/.impeccable/review/curve-today-v1
```

Run from the repository root. It launches a separate headless browser on the
local static file and closes it afterward; it never opens the running demo.

## Representative task review — pending

Ask a participant to find their pending technical decision, identify its workspace
and version, and read the relevant plan/evidence without prompting. Then show a
partial queue, stale evidence and revoked access. Record whether they understand
what is unknown, why a decision is unavailable and where recovery occurs.

Capture completion and confusion points, keyboard/mobile usability, the exact
candidate revision, and the participant's acceptance or requested changes. A
successful automated browser check or design reviewer verdict cannot replace
this product decision. No timing or productivity improvement is claimed.

See [pilot gates](../../../../deployments/curve-local-pilot/PILOT_GATES.md)
(ordered operation, identity, experience and human acceptance work),
[Home brief](../../.impeccable/surfaces/core-components-home-root-tsx.md)
(incumbent cross-project attention composition), and
[prototype brief](../../.impeccable/surfaces/prototypes-curve-today-v1-index-html.md)
(development-only direction and finish contract).
