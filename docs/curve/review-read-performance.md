# Review-status read performance candidate

Status: local candidate under validation; integration remains governed by the existing PR gates.

The review-status endpoints previously probed Submit, Approve and Request changes independently after validating the read. Each probe repeated the full current authorization and runtime-integrity checks, including probes for actions excluded by the current lifecycle or retained decision. Quiet local authenticated reads showed approximately 4.983 seconds for Product status and 3.592 seconds for Technical status before this change. These single samples are diagnostic, not a service-level guarantee.

## Behavior

Product status considers Submit in Aligning and review decisions in PRD Review. Other states expose no Product action. Technical status considers Submit before submission, review decisions while a submitted revision has no decision, and no action after a decision. Every candidate action still passes the original complete authority check before it is exposed. Command handlers continue to perform their own fresh authorization and subject checks.

The initial READ authority check remains mandatory. These filters use its validated, transaction-locked records. They do not cache authority, skip runtime qualification, alter the command routes, change reviewer assignments, or change historical decisions. The response fields and action order remain unchanged.

## Qualification boundary

The [read-performance qualification](../../apps/api/plane/curve/two_stage_review/review-read-qualification-v1.json) (exact two-view replacement digests and predecessor pin) is an additive successor to the [two-stage runtime qualification](../../apps/api/plane/curve/two_stage_review/runtime-qualification-v1.json) (retained source, model, migration, catalog and writer inventory). The historical proof bytes remain unchanged.

The validator accepts exactly the Product and Technical review-view replacements. It inherits every model, migration, catalog, writer and exclusion value. Missing, altered or symlinked proof files deny qualification. Unlisted source replacements and attempts to add authority are rejected.

## Required verification

Real-database view tests must preserve available actions through upload, submission, approval, return, replacement and replay, and preserve current access restrictions. Qualification tests must reject changed proof bytes and unsupported deltas. The complete scope-reader regression must accept the declared successor while retaining its original reader proof. Measure authenticated status reads again after loading the candidate into the isolated local app; report pre/post samples and browser behavior separately from production readiness.

## Local validation results

All 59 focused native database cases passed in 209.13 seconds, including Product and Technical action transitions, feedback, replay, CSRF and payload validation, scope-reader concurrency and successor-proof rejection. All 56 repository checks passed. The API restart preserved all 18 synthetic stored document files by exact content hash.

With the regression runners stopped, authenticated sequential HTTP reads returned 200 in every sample:

| Read             | Before: one sample | After: median of three |  After: range |
| ---------------- | -----------------: | ---------------------: | ------------: |
| Product status   |            4.983 s |                0.645 s | 0.486–1.090 s |
| PRD source       |            0.471 s |                0.836 s | 0.412–0.905 s |
| Technical status |            3.592 s |                1.065 s | 0.394–1.115 s |
| Plan revision    |            2.246 s |                0.653 s | 0.375–0.656 s |

The endpoint changes target the two status reads. Variation in unchanged endpoints shows why these local samples must not be treated as a universal speedup or production capacity result. Browser refresh restored readable PRD content and both Approved statuses. Exact browser completion latency was not established by the observation tool.
