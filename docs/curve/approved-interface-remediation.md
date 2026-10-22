# Approved two-stage interface: remediation record

Status: interface approved; local implementation verified for the main document journeys. The candidate is published in the existing draft PR; compatibility, latency and recovery acceptance remain pending.

The owner approved the new interface on 2026-10-22: Product approves the PRD, then Technical approves the implementation plan. This approval establishes the design direction. Application verification and integration evidence are recorded separately below.

## Delivered experience

The Initiative opens on its document and approval status. A light canvas, white document surfaces, indigo actions, icons and explicit status labels carry the approved visual direction. Search and filters, reviewer responsibilities, supporting details and management actions expand on demand.

A new Initiative accepts a PRD upload without requiring existing work. Selecting a PDF, Markdown or text file uploads it; one explicit action submits the saved version for Product review. Product approval unlocks implementation-plan upload and Technical review. The assigned reviewer can approve or request changes with protected feedback. Replacement documents retain earlier decisions in history and require their own approval.

Updating an approved PRD explains and starts renewed Product and Technical reviews. The old plan stays readable under its original approval context, while current approval controls require an updated plan. Current creation and review use exactly two approval roles. Historical contract editions retain their original records; repository quality checks remain delivery evidence.

## UX findings and remediation

| Finding                                              | Delivered change                                                                                       | Verification                                                   |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------- |
| Too much information and too many competing controls | Document-first, full-width composition with supporting information collapsed                           | Signed-in application inspection and frontend tests            |
| Dark and visually flat presentation                  | Light route palette, local Manrope typography, document panels and stage icons                         | Desktop and 390-pixel mobile inspection                        |
| Three approval roles complicate the process          | Product PRD and Technical plan stages with two assigned reviewers                                      | Native and client contract tests; both authenticated approvals |
| Approval status is difficult to understand           | Both tabs show document needed, ready, waiting, changes requested or approved                          | State-transition tests and authenticated walkthroughs          |
| Document handling requires too many steps            | File selection uploads; an explicit action submits the displayed version                               | PRD and plan uploads, replacement and submission walkthroughs  |
| Feedback can appear stale after replacement          | Current readiness reflects the replacement while previous feedback stays visible                       | Regression test and Product replacement walkthrough            |
| Documents are hard to read                           | Structured Markdown headings, lists and emphasis; literal plain text; PDF viewer and download fallback | Frontend tests and rendered application inspection             |
| Mobile top bar clips controls                        | Route-scoped sizing keeps search and account controls within the viewport                              | Corrected 390-pixel render inspected                           |

## Verified application journeys

- **New Initiative:** create, upload PRD, enter alignment, submit for Product review, request changes, upload a replacement, resubmit and approve. Upload the implementation plan, submit for Technical review, request changes, replace, resubmit and approve. Both stage summaries display Approved.
- **Approved PRD update:** reopen after confirmation, replace the PRD and obtain renewed Product approval. The original plan remains readable and shows Update needed. Replace it and obtain renewed Technical approval. Both stages display Approved again.
- **Reviewer separation:** the Product account has no Technical decision controls; the assigned Technical account records the Technical decision.
- **Persistence:** the approved documents and both decisions remain available after restarting the local API. The demo database was preserved.
- **Responsive reading:** desktop and 390-pixel mobile surfaces were inspected. Document content precedes reviewer controls on narrow screens.

All application evidence uses synthetic data in an isolated local environment.

## Delivery checkpoint

[Plane PR #17](https://github.com/faocampo/plane/pull/17) (approved two-stage interface and consolidated workflows) contains the initial published checkpoint `466c94b06aea8f5c4cc74070a0214c17ac852b52`. The remote head was verified and the PR remains a draft. All 337 reviewed file hashes match after commit hooks. The formatter initially changed 14 byte-pinned JSON files; their exact reviewed bytes were restored and those contract directories were added to the existing formatter exclusions. Generator parity and all 56 repository checks passed afterward.

Both current-head CI dispatch attempts were rejected because GitHub Actions is disabled for the repository. No CI result is claimed for this candidate. The production web build passed. All 20 focused rollback and integrity regression tests passed in 359.18 seconds.

## Validation evidence

| Check                                                    | Result and scope                                                                                                                                                                                                                                                                    |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Frontend regression                                      | 511 tests passed across 37 files                                                                                                                                                                                                                                                    |
| Repository static checks                                 | 56 tasks passed; 753 existing warnings across packages, including 539 in web; no lint errors                                                                                                                                                                                        |
| Local-document and Initiative backend regression         | 333 tests passed                                                                                                                                                                                                                                                                    |
| Final new-work/runtime qualification                     | 19 tests passed after the formatting-only migration correction; executed SQL and catalog preserved                                                                                                                                                                                  |
| Complete host test groups                                | 156 tests passed against the pinned public contract reference                                                                                                                                                                                                                       |
| Historical migration target checks                       | 11 tests passed after correcting the historical catalog comparison                                                                                                                                                                                                                  |
| Retained-reversal cleanup and following ownership checks | 4 tests passed together in 301.14 seconds                                                                                                                                                                                                                                           |
| Remaining native compatibility suite                     | Latest broad run: 519 passed, then a historical test setup failed because a successor correctly refused reversal first. The ordering-only catalog mismatch is corrected; all three migration cases and 17 qualification cases passed. Full compatibility acceptance remains pending |
| Model consistency and Python static checks               | No model migration changes required; Curve Ruff checks passed                                                                                                                                                                                                                       |
| Generated validators                                     | Exact regeneration check passed from the reviewed schemas                                                                                                                                                                                                                           |
| Publication disclosure review                            | All candidate files reviewed, including schema/SQL content, synthetic fixtures, generated-source provenance and font metadata/license; recheck changed bytes before publication                                                                                                     |

The compatibility work corrected two historical test issues: catalog assertions now run at their intended migration target, and a reversal that refuses retained evidence restores later migrations before the following test. A separate host-test import correction prevents duplicate Django model registration. Original failing runs remain distinct from successful reruns. The later broad run also showed that a successor guard can correctly refuse reversal before the historical plan guard is reached. The revised test checks that older guard directly against the real database, then checks complete-chain refusal and restoration. Its focused follow-up passed the empty round trip but found a catalog difference after retained-evidence refusal and successor restoration. Per-section catalog diagnosis confirmed that only trigger ordering differed, with no added or removed triggers. The current-chain test now uses the current catalog query with its constraint-name tie-breaker; the historical empty round trip retains its original catalog. All three corrected migration cases passed together with 17 runtime-qualification cases. No historical runtime schema bytes were rewritten to make these tests pass.

These results apply to the local candidate. The final PR delivery record identifies the tested commit and current PR checks. The full 511-test frontend suite passed after pre-commit corrections; a final ten-test client rerun passed after correcting a renamed test reference. All 56 repository checks passed again. Strict lint over the 58 changed script files reported zero warnings and zero errors.

## Integrity-check latency

A read-only execution-plan comparison identified substantial query-compilation overhead in the physical catalog check. The runtime now disables compilation only around the fresh catalog and database-verifier queries, then restores the caller's query-compilation and schema-search settings. Source hashes, migration hashes, current catalog comparison and database coverage verification still run on every qualification call. Four real-database cases verify both caller compilation settings, successful qualification, rejection of an added schema index, and settings restoration. They passed within the 20-test focused run. Test sessions used compilation disabled by default; the four cases explicitly exercise callers with it enabled and disabled.

Full request and browser latency still require quiet-runtime measurement; isolated query timings under regression load are diagnostic evidence only.

## Remaining acceptance and delivery

1. Finish the full native compatibility run and resolve any actual failures.
2. Measure local request latency without concurrent regression load and address the observed delay while preserving current authorization and integrity checks. One earlier qualification call took 2.574 seconds, including 1.973 seconds in database execution; that diagnostic is not request-latency acceptance.
3. Complete authorized browser recovery checks. Native tests cover current access, revocation during I/O and replay. A temporary membership-revocation test in the synthetic demo awaits specific owner authorization; that mutation has not been performed. Unknown-outcome recovery has automated coverage; live network interruption remains unverified.
4. Complete current-head validation and owner review before integration. The existing draft PR and its description have been updated; the remote head is verified. Hosted CI remains unavailable while repository Actions is disabled.

Storage initialization is required for the local document directory. Production provider/storage activation, release qualification and later milestones retain their own gates.

Implementation sources: [Initiative workspace](../../apps/web/components/curve/initiatives/initiative-workspace.tsx) (document-first composition), [review desk styles](../../apps/web/components/curve/initiatives/initiative-workspace.css) (light route palette), and [local document review](../../apps/web/components/curve/initiatives/local-document-review.tsx) (two-stage status coordination).

Approved behavior: [two-stage document review](two-stage-document-review.md) (current review model, new-Initiative context and delivery boundary). Visual record: [design checkpoint](../../apps/web/components/curve/initiatives/DESIGN.md) (approved styling and dated implementation evidence).
