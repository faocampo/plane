# Existing Projects outlook candidate

Status: **LOCAL CLICKABLE CANDIDATE — OWNER REVIEW PENDING**.

This additive, read-only view makes existing Plane projects useful within Curve.
It does not adopt a project into a Curve lifecycle, create a Product/Initiative,
import data, reconstruct approval history, or establish M2 completion. Native
work, comments, history, membership and feature configuration remain authoritative.
No source or backend authority changes are included.

## Source authority and scope

The candidate is based on Plane commit
`e2556004ab253a2289677df14c193d845613b722` (protected PRD metadata review base).
Its separate local branch is `feat/curve-projects-outlook` (native Projects outlook).
The companion Curve requirements retain their authority:

- `docs/technical/coding-handoff.md` (current integration and activation gates).
- `docs/technical/pending-stages.md` (M2 roadmap/linkage boundaries).
- `docs/technical/curve-experience-blueprint.md` (required owner UX review).
- `docs/curve-ai-native-sdlc-prd.md` (native Plane authority and D-013 no-import policy).

The source list endpoints are existing session-authenticated Plane routes:

- `GET /api/workspaces/{slug}/projects/` (authorized native project discovery).
- `GET /api/workspaces/{slug}/members/` (native workspace roster for lead labels).
- `GET /api/workspaces/{slug}/projects/{id}/modules/` (selected-project Modules).
- `GET /api/workspaces/{slug}/projects/{id}/cycles/` (selected-project Cycles).

No new endpoint, credential, persistent cache, server projection, database table,
entity association, background worker, or model/provider call is introduced.
The existing APIs return complete unpaginated arrays; requests are bounded to
two directory reads and at most two selected-project reads per refresh. This is
not a server-side pagination or large-workspace performance qualification.

## Screen contract

- Audience: a workspace member finding current native work and recorded dates.
- Location: Work management → Projects, inside the existing Curve shell.
- Primary flow: search projects → choose one → inspect Project lead, Module
  targets, Cycle ends and source coverage → open the native work/source record.
- Primary action: Open project work; the native Projects directory remains linked.
- No automatic project selection and no source reads for every project in the list.
- Project lead uses only `project_lead` and the current scoped roster. No lead is
  distinct from an unresolved lead name; creator/default assignee/email do not
  substitute for it.
- Module targets are native nullable date-only values. Completed/cancelled modules
  are excluded from the earliest-target list. Paused does not imply blocked.
- Cycle ends are native timezone-qualified instants. The original date/time/offset
  is displayed. An ended cycle says nothing about delivered work.
- Display at most five earliest Module targets and five current/upcoming Cycle
  ends, with displayed/available count disclosure and a link to each source list.
- No project deadline, Curve Milestone, delivery forecast, health, or completion
  percentage is inferred. Blockers are explicitly **not assessed**.
- Coverage is per-source availability and missing usable dates, never a promise
  that all commitments/dependencies were found. Successful empty data is distinct
  from disabled, restricted, membership-required, failed, denied or not loaded.
- Read timestamps describe this request's observation, not a source update time.

The view inherits `apps/web/DESIGN.md` (Curve semantic tokens, responsive shell,
compact controls and evidence-led hierarchy). It has one page heading, labeled
search, keyboard-selectable project buttons, native anchors, visible focus, textual
status and loading/error announcements. On narrow screens list and details stack.

## Isolation and read policy

Each request is scoped to the current authenticated account and workspace. Project
sources additionally bind the selected native project and its workspace ID. Scope
or selection changes abort old requests; generation/identity checks discard old
responses even if transport cancellation fails. Previously rendered data is hidden
synchronously on scope changes and when refresh begins. Refresh/focus/reconnect
revalidate native access, rather than preserving a previous authorization result.
Unmount aborts all pending requests.

Only active projects are shown. Public project discovery and workspace-admin status
do not grant source access: no selected source request occurs without a current
native project membership. Feature-disabled sources and guests without an explicit
`guest_view_all_features` grant are suppressed before request, in addition to the
unchanged server permission checks. Denial clears the affected projected data.
The full native session still owns authentication/revocation behavior; this candidate
is not a new cross-service consistency fence or independently qualified auth system.

The view deliberately avoids the native project detail and work-item list reads that
schedule recent-visited updates. It also avoids aggregate stats and issue-relation
expansions. Code inspection found differing visibility/count semantics that need
separate actor/scope tests before reuse; this is an improvement candidate, not a
reproduced live security finding. No live API calls were made for this work.

## Review state inventory

Review normal, loading, empty directory, search-empty, project not selected,
source-empty, missing lead/date, disabled feature, membership-required,
restricted guest, source error, access denial and retry. Also review repeated
selection, rapid project changes, account/workspace changes during requests,
refresh during requests, keyboard focus, mobile stacking, dark theme and native
link destinations. No confirmation dialog is needed because the view has no writes.

A fixture-only review harness is supplied:

- `apps/web/tests/review/projects-outlook.html` (isolated review entry point).
- `apps/web/tests/review/projects-outlook.tsx` (fictional records/state controls).
- `apps/web/tests/review/projects-outlook.config.ts` (local preview configuration).
- `apps/web/tests/review/projects-outlook-stubs.ts` (fail-closed account/source stubs).

Run from `apps/web` (web application):

```sh
node node_modules/vite/bin/vite.js --config tests/review/projects-outlook.config.ts
```

Open the localhost URL printed by Vite with `/tests/review/projects-outlook.html`.
The review uses the real pure presentation component and shared design tokens.
It never mounts the authenticated application, a live adapter, or source-connected
container. All links remain in its in-memory router and reveal the intended native
destination. Fixture controls do not affect persisted records.

## Owner task-based review

1. Find a project by name/identifier and identify its actual Project lead.
2. Select the project and identify the earliest recorded Module target and Cycle
   end. Explain why neither is a project deadline or delivery-completion signal.
3. Identify a missing source/date and distinguish it from an empty successful read.
4. Open the native work and source links; verify the destination shown in the preview.
5. Recover from partial source failure, then repeat at a narrow viewport and by keyboard.

Record the candidate commit, reviewer, task outcomes and requested changes in the
approved review channel. Synthetic tests and screenshots do not constitute owner
acceptance. Authenticated Mac QA remains a separate, authorized step with the real
workspace and membership matrix; live providers remain on that computer.

## Next gate: prospective association contract

The smallest future association candidate must define current explicit authority,
same-workspace native project references, the new Curve intent's starting state,
allowed cardinality, existing-record/history preservation, current evidence/access,
audit, concurrency/idempotency, reconciliation ownership and reversible unlinking.
It must forbid inferred historic PRD/plan/code approvals and must not repurpose or
copy native IDs. Whether such a forward-looking association is consistent with
D-013 (new-initiative/no-import policy) needs an explicit reviewed disposition.

That contract is not approved or implemented here. No UI link, source read or local
candidate review establishes lifecycle migration, a Curve roadmap, Feature Delivery,
WorkItemBinding, past gate success, activation or M2 completion.
