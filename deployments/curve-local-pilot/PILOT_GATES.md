# Local pilot: delivery and acceptance gates

Status: 2026-10-07. This continuation is local, on
`feature/local-pilot-recovery` (unpublished recovery and experience work).
The delivered demo and published branches remain fixed while the user tests them.
Recovery qualification is evidence for an operating decision, not that decision.

## Current evidence

The qualified application source is
`8aede16b4aee1aa66eb0b9469c4c849b34250f6e` (fixed local demo runtime).
Its later published Plane documentation head is
`a6b0a8db15c42625712d083b8022cd4011eef892` (delivered branch).
The published Curve head is
`af5616a5ca990f54943b7b6123c1b3362d0e6486` (contracts and delivery documentation).
No frozen application module, migration or proof changes in this continuation.

- A private, coherent synthetic backup exists. The isolated restore reconstructed
  the exact schema through the original migrations, checked all 151 public
  tables and 24 protected objects, and passed the unchanged native catalog seal.
- The copied application authenticated the existing synthetic technical approver
  through the normal HTTP session endpoint and read the exact protected plan.
- Ten control cases passed, including two rejected role-inappropriate approval
  commands, uniform cross-workspace denial, disablement, corrupt material and
  membership revocation against a still-authenticated session. The controlling
  business graph remained unchanged. No approval was accepted in this exercise.
- The original demo has a separate Chromium approval/reconciliation/release
  journey on a secondary synthetic Initiative. Its primary example was reserved
  for user review. The browser recorded recoverable hydration errors; it is not
  evidence of a console-clean application or human acceptance.

See [recovery guide](recovery/README.md) (private inputs, supported capture and
restore boundaries) and [qualification record](recovery/qualification-2026-10-07.json)
(sanitized native restore and identity/fault results). Runtime evidence is not
new CI approval; the last delivered-head checks had no reported check-runs,
statuses or Actions runs.

The [persistence profile](recovery/PERSISTENCE.md) (owned-volume lifecycle and
failure handling) now qualifies synthetic stop/resume and crash/container
replacement, including rollback of an open transaction, complete row/schema
comparison, protected-store readiness and scoped disposal. Twenty-five focused
tests and real Docker lifecycle/ownership checks support this engineering gate.
This does not activate a persistent installation for the real cohort.

The [human UX review](UX_REVIEW_TODAY.md) (visual evidence, exact UX-004/005
decisions and recommended navigation alignment) is ready for Fede. The current
prototype's inherited Home location differs from the Product/Home blueprint;
that choice is explicit and remains pending. No Today integration has begun.

## Ordered gates

| Gate | Available now | Remaining exit evidence | Decision owner |
| --- | --- | --- | --- |
| 1. Operable local installation | Fixed demo; verified backup/restore; synthetic volume persistence across stop, crash and container loss; fault fencing and scoped cleanup | Actual persistent installation; operator and storage/retention decisions; host/VM failure, capacity and disk-pressure qualification; human recovery drill and activation | Pilot operator and product owner |
| 2. Actual participant identity | Native session login, role denials, active-membership revocation on the copy | Named private cohort; individual accounts and Initiative assignments; current source grants; overlap/risk policy; departure and lost-access walkthrough | Workspace administrator and assigned approvers |
| 3. Today and pending decisions | Isolated clickable queue prototype and proposed screen contract | Representative user task review; UX-004/005 acceptance; bounded authenticated queue design; coverage of partial pages, freshness and permissions; integrated implementation and checks | Product owner, participant and implementer |
| 4. Roadmap visibility | Product and Initiative boundaries defined | Narrow read projection tied to real Roadmap Item work bindings; unavailable-source states; permission and pagination evidence | Product owner and technical owner |
| 5. Pilot acceptance and next cut | Existing technical evidence plus this continuation | Human journey on the exact candidate; positive and denied/stale/failure paths; documented residual defects; operator readiness and explicit cut scope | Product owner and pilot operator |

Proceed in this order; the prototype can be reviewed while operation and identity
decisions are being prepared. Neither a restore success nor an automated design
review closes gates 1, 2, 3 or 5. No elapsed time, absent CI result or lack of user
objection is acceptance. Announce the scope before any new publication cut.

## Operator runbook and remaining choices

The running demo database and synthetic catalog use ephemeral storage. Do not
restart, recreate, reseed or tear it down while the user is testing. A backup's
persistent files do not make the running application persistent.

1. Record the current runtime commit, authorized project and private data paths.
   Keep credentials, database archives, sessions, password hashes and protected
   bodies outside Git and shared output. Use existing login and Git credentials.
2. Verify a private capture before recovery. Use the supported exercise to create
   a new labelled disposable target; never point it at the existing database.
   Exact native schema and catalog verification must precede the HTTP probe.
3. On an integrity or permission failure, stop the affected operation. Retain only
   safe correlation data, actor/resource identifiers under the agreed retention
   policy, error category and source revision. Do not log evidence bodies, secrets
   or request credentials. An unavailable check must not become a zero count.
4. Prepare persistence and stop/resume on a new installation before changing the
   delivered demo. Define the backup owner, retention and storage limits, recovery
   operator and alert route, and the scope of a disable action. Test interrupted
   startup and restore failure there; verify no effect escapes a fenced service.
5. For activation, bind the actual approved private cohort and Initiative roles to
   the selected workspace and source resources. Recheck current membership and
   object access on each operation. Never reuse the creator's authority for a
   different actor. Keep the recorded demo as evidence, not as the identity roster.
6. Record a human go/no-go for the exact candidate, remaining defects and recovery
   procedure. Capture the proposed publication scope separately before a new cut.

Open decisions are concrete: who operates and can disable the pilot; where its
state persists and how long backups/diagnostics are retained; which distinct
people may access which resources and approve each gate; the accepted risk tier
and any permitted role overlap; and who accepts the observed user journey.
The synthetic shared-password fixture proves none of those human assignments.

For HIGH risk, the three human gate roles remain distinct. STANDARD overlap
requires the prior workspace exception; LOW follows its approved template.
Do not turn successful synthetic tests into IdP/MFA deployment claims or infer
approval of D-003 (runtime topology), D-009 (retention), D-015 (private pilot
readiness), or D-016 (numeric pilot guardrails). A measured restore duration is
not a certified RPO/RTO, and no outcome-improvement claim is supported yet.

## Product basis

These immutable sources order the continuation and keep its claims bounded:

- [Local pilot delivery](https://github.com/faocampo/curve/blob/af5616a5ca990f54943b7b6123c1b3362d0e6486/docs/technical/local-pilot-delivery-2026-10-06.md)
  (five pilot deliverables, with operation and Today remaining).
- [Product requirements](https://github.com/faocampo/curve/blob/af5616a5ca990f54943b7b6123c1b3362d0e6486/docs/curve-ai-native-sdlc-prd.md)
  (effective principal, human gates, risk roles and pilot decisions).
- [Security and operations](https://github.com/faocampo/curve/blob/af5616a5ca990f54943b7b6123c1b3362d0e6486/docs/technical/security-and-operations.md)
  (resource-scoped access, safe signals and restoration boundaries).
- [Experience blueprint](https://github.com/faocampo/curve/blob/af5616a5ca990f54943b7b6123c1b3362d0e6486/docs/technical/curve-experience-blueprint.md)
  (UX-004 clickable review and UX-005 screen contract).
- [Dashboard reference](https://github.com/faocampo/curve/blob/af5616a5ca990f54943b7b6123c1b3362d0e6486/docs/design/mockups/dashboard-public-reference.md)
  (source-aware decisions for the signed-in user and truthful availability).
