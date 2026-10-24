# Two-stage review runtime candidate

This candidate assigns Product review to the PRD and Technical review to the implementation plan. Initiative schema `1.2` carries those two assignments. Ordinary repository reviews, required checks, acceptance criteria, and retained evidence remain part of the plan.

## Current implementation boundary

- Initiative policy version 2 validates the two human reviewer assignments.
- Scoped PRD version 2 binds observation, submission, Product decisions, and retries to the two-stage Initiative edition.
- Manual plan version 3 validates and stores implementation-plan drafts using the two current reviewers. Its saved revisions retain the exact PRD subject, scope, protected inputs, validation receipt, and authorization decision.
- The Technical-review subject adapter consumes exact version-3 plan revisions, identities, and validation receipts. It requires Product and Technical assignments and uses the shared task-reservation transition kernel, preserving cross-edition exclusivity, release generations, and history. Native authorization, atomic storage, and HTTP routes use the version-3 successor.
- Version-3 Technical-review contracts define submission, approval, requested changes, reconciliation, release, material reads, and status. Embedded plan identity/save schemas are flattened from the exact version-3 source contracts. The pinned manifest rejects altered, additional, missing, or linked contract files.
- Native Technical-review authority resolves current two-stage reviewers, protected document grants, and task access. Preparation is limited to the creator or a current technical contributor; decisions and release require the current Technical Reviewer. Retained Code-review assignments are excluded from the new release authority. Technical decisions persist through the version-3 transaction guards.
- Version-3 command, preparation, status, and material endpoints now connect to the successor orchestration. Shared reservation models accept only an exact active receipt from their selected writer; competing records are verified under their stored edition. Technical writes require the exact qualified version-3 database guards and catalog.
- Saving a plan draft keeps `controlling` false. A separate Technical decision records plan approval and reserves its tasks. The complete document interaction experience still requires frontend integration.

The current plan HTTP routes use `/manual-plan-drafts/v3/`, with `current/`, `status/`, and `revisions/<revision_id>/` reads. Session authentication, CSRF, exact Initiative preconditions, bounded requests, current access, and private response caching rules remain enforced. The local synthetic storage adapter requires the explicit version-3 feature switch and fixed protected storage root.

## Preserved history

Historical Initiative, PRD, and plan editions keep their original contracts and evidence. The shared physical plan tables dispatch validation by the exact stored edition. A version-3 save cannot append to an incompatible version-2 revision chain or reuse an older authorization receipt.

The [runtime qualification](runtime-qualification-v1.json) (exact supported source, migration, model, writer, and physical catalog inventory) is an additive successor to the retained header qualification. The trusted validator checks every predecessor proof and the declared source delta, then compares the complete current runtime against the pinned inventory. A missing, altered, or unqualified source or migration denies the writer. Runtime configuration cannot generate or approve a replacement qualification.

The [plan migration](../migrations/0028_manual_plan_two_stage.py) (versioned SQL validation and immutable coverage seal) installs the new guards while retaining earlier seals. Reverse migration must preserve retained records and restore the predecessor catalog exactly.

## Verification scope

The [native persistence tests](../tests/manual_plan_v3/test_persistence.py) (real PostgreSQL save, revision, replay, access, HTTP, concurrency, and immutable record graph checks) use a real submitted and approved PRD with synthetic protected material. The former Code reviewer's access is revoked in that fixture. The [qualification tests](../tests/test_two_stage_runtime_qualification.py) (source, policy inventory, migration, and proof corruption denial) cover the additive runtime boundary.

The [Technical transition tests](../tests/manual_plan_v2/host/test_two_stage_gate2_domain.py) (two-stage subject validation, reviewer access, historical and current reservation conflicts, retry, hold, reconciliation, and release) exercise the pure transition kernel. Persisted Technical decisions are exercised separately by the native lifecycle tests.

The [Technical contract tests](../tests/manual_plan_v3/test_technical_contracts.py) (action preconditions, cross-edition rejection, exact embedded plan schemas, bounded input, and manifest integrity) validate the version-3 API vocabulary used by native dispatch.

The [Technical authority tests](../tests/manual_plan_v3/test_technical_authority.py) (real saved PRD/plan, current reviewer decisions, former Code-reviewer revocation, Product-role denial, document-access loss, and explicit local enablement) exercise native policy against the test database. The Technical decision writer requires its qualified storage successor.

These tests establish their local candidate scope. Full authenticated browser acceptance, PR publication, integration, and runtime activation require their own evidence.

## Technical storage successor

The [Technical migration](../migrations/0029_technical_review_two_stage.py) (additive policy identity, immutable coverage seal, and retained-evidence rollback guard) installs the [forward guards](technical-review-v3-forward.sql) (versioned Technical records and complete transaction checks) and retains the [reverse guards](technical-review-v3-reverse.sql) (exact predecessor restoration). Historical migration and contract bytes remain intact.

The [native decision tests](../tests/manual_plan_v3/test_technical_decisions.py) (submission, approval, reconciliation, release, original replay, wrong approver, stale version, and revoked rationale access) run with a real saved two-stage PRD and plan. The migration's physical catalog was qualified in a rolled-back PostgreSQL transaction, including the policy constraint, coverage seal, verifier, and empty reversal. Full browser integration and user acceptance remain separate delivery gates.

## Connected local document experience

The local document panels now provide PRD upload and Product decisions followed by implementation-plan upload and Technical decisions. New Initiatives use Product/business-intent submission pins; existing-work submissions retain their original scope pins. Both paths retain two reviewer assignments. See [two-stage document review](../../../../../docs/curve/two-stage-document-review.md) (approved experience and authority boundary) and [interface remediation](../../../../../docs/curve/approved-interface-remediation.md) (current browser and test evidence). The historical manual-plan writer described above retains its independent reservation and execution-readiness scope.
