# Approved two-stage interface: remediation record

Status: interface approved; local implementation verified for the main document journeys. The candidate is published in the existing draft PR; hosted validation and remaining recovery acceptance are pending.

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

| Check                                                    | Result and scope                                                                                                                                                                                                                                          |
| -------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Frontend regression                                      | 516 tests passed across 37 files                                                                                                                                                                                                                          |
| Repository static checks                                 | 56 tasks passed; 753 existing warnings across packages, including 539 in web; no lint errors                                                                                                                                                              |
| Local-document and Initiative backend regression         | 333 tests passed                                                                                                                                                                                                                                          |
| Final new-work/runtime qualification                     | 19 tests passed after the formatting-only migration correction; executed SQL and catalog preserved                                                                                                                                                        |
| Complete host test groups                                | 156 tests passed against the pinned public contract reference                                                                                                                                                                                             |
| Historical migration target checks                       | 11 tests passed after correcting the historical catalog comparison                                                                                                                                                                                        |
| Retained-reversal cleanup and following ownership checks | 4 tests passed together in 301.14 seconds                                                                                                                                                                                                                 |
| Native compatibility suite                               | Original full run: 2,756 passed, 5 failed, 12 skipped and 1 setup error. Corrected focused regressions passed for all six failure/error cases. All 23 workflow follow-up cases passed, covering every original skip; see the final native evidence below. |
| Model consistency and Python static checks               | No model migration changes required; Curve Ruff checks passed                                                                                                                                                                                             |
| Generated validators                                     | Exact regeneration check passed from the reviewed schemas                                                                                                                                                                                                 |
| Publication disclosure review                            | All candidate files reviewed, including schema/SQL content, synthetic fixtures, generated-source provenance and font metadata/license; recheck changed bytes before publication                                                                           |

The compatibility work corrected two historical test issues: catalog assertions now run at their intended migration target, and a reversal that refuses retained evidence restores later migrations before the following test. A separate host-test import correction prevents duplicate Django model registration. Original failing runs remain distinct from successful reruns. The later broad run also showed that a successor guard can correctly refuse reversal before the historical plan guard is reached. The revised test checks that older guard directly against the real database, then checks complete-chain refusal and restoration. Its focused follow-up passed the empty round trip but found a catalog difference after retained-evidence refusal and successor restoration. Per-section catalog diagnosis confirmed that only trigger ordering differed, with no added or removed triggers. The current-chain test now uses the current catalog query with its constraint-name tie-breaker; the historical empty round trip retains its original catalog. All three corrected migration cases passed together with 17 runtime-qualification cases. No historical runtime schema bytes were rewritten to make these tests pass.

These results apply to the local candidate. The final PR delivery record identifies the tested commit and current PR checks. The full 516-test frontend suite passed after the live connection-recovery corrections; the final production web build also passed. All 56 repository checks passed again. Strict lint over the 58 changed script files reported zero warnings and zero errors.

## Connection-loss recovery

A live browser check stopped only the synthetic demo API, verified the unavailable state, restarted the API and refreshed the displayed document. Product and Technical approval statuses returned to Approved, and the retained document remained readable. All 18 stored document objects matched the saved backup before restart.

The check exposed misleading empty-state wording while status was unavailable. The document now says Document unavailable, and both approval stages show Status unavailable until current information can be read. A regression case covers failed reads, both stage labels, and recovery through Refresh; the complete interface suite passed 516 tests afterward. The corrected unavailable state was inspected in the live browser. This is read-failure recovery evidence; unknown mutation outcomes retain their separately scoped automated coverage.

## Stalled-request recovery

Curve review metadata, protected document/feedback reads, CSRF acquisition and writes now have a 60-second per-request deadline. A timeout before dispatch is a transport failure; a timeout after dispatch remains an unknown mutation outcome. Explicit retry retains the original command and idempotency key. Four additional client regressions cover timeout classification, bounded requests and exact-command replay. Protected-content tests also check the deadline. All 516 interface tests, 56 repository checks and the production web build passed after this change.

A local browser exercise paused the synthetic API with a 90-second automatic-resume safeguard. The refresh reached the unavailable state with Refresh enabled; after the service resumed, an explicit refresh restored readable PRD content and both Approved statuses. The database and document storage remained running and intact. This proves stalled-read recovery; live mid-mutation response loss remains a separate unverified case.

The full native suite exposed another historical test-target mismatch: a plan migration round trip restored all installed successors and then compared the current physical catalog against the earlier technical-review migration's pin. The corrected test checks both historical targets explicitly and verifies the restored installed catalog plus current qualification. Its isolated focused rerun passed in 505.31 seconds, including creation of a separate test database. The original full-run failure is retained, and the original complete native run is not reported as a full pass.

The continuing run exposed a Technical rollback test that left later migrations reversed after retained evidence refused the historical step. Its cleanup now restores every installed migration and verifies current qualification. The adjacent round-trip test now checks historical fingerprints at their matching targets. All three cases passed together in 181.84 seconds in the isolated database, including successful fixture creation immediately after the refused rollback. The scope-reader proof test now validates the pinned two-stage successor, retaining historical header-proof validation and exact current-source equality. Its complete 23-case regression passed in 124.11 seconds, including current-access checks, missing/tampered-proof rejection and concurrent reader/writer behavior. The four failures recorded by the original full run remain distinguishable from these passing corrected regressions.

The original full run subsequently recorded two further historical test assumptions. The forged-seal test now tampers with the active successor seal so the application independently rejects the self-consistent database proof; both variants passed in 16.72 seconds. The reopening rollback test now verifies current retained-evidence refusal, restores installed successors, and separately exercises the historical preservation guard while checking exact history. Its focused rerun passed in 82.07 seconds. These corrections change tests only. Six original full-run failures remain recorded separately from the passing corrected regressions; the complete run was still pending at that checkpoint.

## Complete native run and workflow-server follow-up

The original 2,774-case native run completed with 2,756 passed, 5 failed, 12 skipped and 1 setup error in 14,740.82 seconds. The five failures and setup error are the six historical migration/proof assumptions described above; their corrected focused regressions passed. The original full-run result remains retained separately from those corrections.

The 12 skipped cases needed a local Temporal time-skipping test server. Caching the SDK-selected server outside the isolated test network and mounting it read-only allowed all cases to execute. The first follow-up passed 22 cases and exposed a query racing the parent workflow's continue-as-new transition. The test now observes the old run's explicit continuation event and queries the identified successor run before asserting its state and final result. The complete 23-case workflow follow-up then passed in 48.54 seconds with no skips, including all 12 originally skipped cases. These follow-up corrections change tests only; runtime source and historical pins remain unchanged. This is combined full-run and focused-correction evidence, not a claim that the original full run passed unchanged.

## Live interrupted-write recovery

A separate synthetic Initiative exercised a lost response after a real Product submission committed. A temporary loopback-only proxy forwarded the normal authenticated command and dropped its successful 201 response after receiving it from the API. The browser displayed the unknown-result explanation and Retry same review. Before retry, the database showed exactly one submission, PRD Review state and Initiative version 4.

The explicit browser retry used the identical request body, idempotency key and version precondition. The server returned 200 with Idempotency-Replayed true; the database still showed exactly one submission at version 4. The interface recovered to In Product review with the normal reviewer actions. Raw response-byte hashes differed, so byte-for-byte response identity is not claimed; the verification establishes exact-command replay and unchanged authoritative state. The original proxy configuration was restored exactly and the temporary proxy stopped. All 20 synthetic stored document files, including the new recovery PRD, were backed up and verified by content hash.

## Integrity-check latency

A read-only execution-plan comparison identified substantial query-compilation overhead in the physical catalog check. The runtime now disables compilation only around the fresh catalog and database-verifier queries, then restores the caller's query-compilation and schema-search settings. Source hashes, migration hashes, current catalog comparison and database coverage verification still run on every qualification call. Four real-database cases verify both caller compilation settings, successful qualification, rejection of an added schema index, and settings restoration. They passed within the 20-test focused run. Test sessions used compilation disabled by default; the four cases explicitly exercise callers with it enabled and disabled.

Quiet authenticated HTTP measurements subsequently identified repeated full authority checks for actions impossible in the current review state. A separately pinned read-performance successor now filters those candidates before checking every action that could be exposed. The initial READ and all command authority checks remain intact; historical proof bytes, migrations, models and catalog pins remain unchanged. All 59 focused native database cases and 56 repository checks passed.

Product status measured 4.983 seconds before the change and a median 0.645 seconds across three quiet after-change samples; Technical status measured 3.592 seconds before and a median 1.065 seconds afterward. All reads returned 200. Browser Refresh restored the readable PRD and both Approved statuses. These are local diagnostic samples with one before sample, not production latency acceptance. See [review-read performance](review-read-performance.md) (scope, additive qualification, sample ranges and verification).

## Owner UX acceptance

The repository owner accepted the implemented interface on 2026-10-22 against candidate `d57397ae06dbd472e64eb1b35049c85d291cd2e4`. The accepted flow is Product approval of the PRD followed by Technical approval of the implementation plan, with no Code Approver stage. The current PR head was verified at that commit after acceptance. This closes the owner UX review gate; the remaining validation and integration requirements below retain their scope.

## Final local delivery checks

The full repository build passed all 15 tasks in 30.347 seconds at `45ff994d34121d3ceb051c52abf80fd1cd0ef767`. The delivery-grant web-test command exercised all 47 web test files: its first run passed 550 assertions but failed with an unhandled font-loader timer after the project-header test environment closed. That test still mocked the former emoji-picker package. Updating the mock to the component's current package restored isolation; the rerun passed all 550 tests across 47 files in 19.46 seconds, with no unhandled errors. This correction changes one test import only. Build and test tooling still emit existing warnings; these results are not warning-free claims.

The branch's available CodeQL analyses refer to older commits. No exact-head hosted CI or CodeQL result is available for this candidate, and old zero-result analyses do not establish current-head clearance.

## Remaining acceptance and delivery

1. Complete authorized browser recovery checks. Native tests cover current access, revocation during I/O and replay. A temporary membership-revocation test in the synthetic demo awaits specific owner authorization; that mutation has not been performed. Unknown-outcome recovery has automated coverage. Live read interruption and post-commit submission response-loss recovery are verified above.
2. Complete current-head technical validation before integration. Owner UX review is accepted for the candidate recorded above. The existing draft PR and its description have been updated; the remote head is verified. Hosted CI remains unavailable while repository Actions is disabled.

Storage initialization is required for the local document directory. Production provider/storage activation, release qualification and later milestones retain their own gates.

Implementation sources: [Initiative workspace](../../apps/web/components/curve/initiatives/initiative-workspace.tsx) (document-first composition), [review desk styles](../../apps/web/components/curve/initiatives/initiative-workspace.css) (light route palette), and [local document review](../../apps/web/components/curve/initiatives/local-document-review.tsx) (two-stage status coordination).

Approved behavior: [two-stage document review](two-stage-document-review.md) (current review model, new-Initiative context and delivery boundary). Visual record: [design checkpoint](../../apps/web/components/curve/initiatives/DESIGN.md) (approved styling and dated implementation evidence).
