# Local PRD upload candidate

Status: implemented LOCAL-only upload, protected-read endpoints, connected Product and Technical review panels, and native approval commands. Authenticated walkthroughs cover both stages, requested changes, replacement and renewed approval. Publication and broader delivery qualification are tracked in [interface remediation](../../../../../docs/curve/approved-interface-remediation.md) (current verification evidence and remaining acceptance).

## Behavior

An Initiative creator can upload a PDF, Markdown or UTF-8 text document up to 10 MiB while the Initiative is Draft or Aligning. Each upload produces an immutable original, a lossless review snapshot and an append-only native source version. Product and Technical remain the two current approvers.

Authorization resolves active native humans, workspace membership, Product state, current reviewer assignments and source-project access for the actor and both approvers. The creator or an assigned approver can read the document. Workspace administration alone does not grant document access. Reopening, membership changes and stale Initiative versions are checked again around protected I/O.

The configured storage directory is absolute, private to the application account and traversed without following symlinks. Original and snapshot reads verify size, digest, ownership and file identity. Current settings are `CURVE_LOCAL_PRD_ENABLED` and `CURVE_LOCAL_PRD_STORAGE_ROOT`; the default is disabled with no configured root. Existing workspace, scoped-review and LOCAL-environment gates also apply.

## HTTP contract

All routes are under `/api/v1/workspaces/{slug}/curve/initiatives/{initiative_id}/local-prd/v1/`.

| Method and path                    | Purpose                                                                                                                 |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `POST sources/`                    | Upload raw document bytes and create the next source version.                                                           |
| `GET sources/current/`             | Read the current source, Initiative version and upload availability; an authorized empty state contains `source: null`. |
| `GET sources/{source_id}/`         | Read the exact retained source metadata.                                                                                |
| `GET sources/{source_id}/content/` | Retrieve the verified original document after current access checks.                                                    |

Upload uses a session and CSRF header, `If-Match: "{initiative_version}"`, `X-Curve-Source-Version: {current_source_version}` (zero for the initial upload), and `Idempotency-Key`. Content type is `application/pdf`, `text/markdown` or `text/plain`; the body contains the file bytes directly. The request-size middleware applies the 10 MiB upload bound before the generic request-body limit.

A successful creation returns 201, the exact `curve.local-prd-source/v1-candidate` metadata, a source-detail Location and the Initiative ETag. A currently authorized retry returns 200 with the same source record and `Idempotency-Replayed: true`. Reusing a key with changed content is a conflict. The source version is independent of the Initiative version and must match before creating a replacement.

Responses use `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. Text content is served as plain text. PDF content uses a sandbox content-security policy. Error responses contain fixed codes and a safe correlation identifier.

## Persistence and recovery

The native source, successful audit event, domain event, outbox entry and completed idempotency record commit in one database transaction. An exact policy decision records current authority. File preparation occurs outside database locks, followed by fresh authorization and a native-state comparison before persistence.

Prepared objects are retained after uncertain database outcomes so recovery cannot erase a committed document. A governed cleanup process must establish that an object is unreferenced before removing it; automatic orphan cleanup remains pending. Production storage lifecycle qualification remains a separate delivery requirement.

Migration 0030 (immutable uploaded-source persistence) preserves tenant and predecessor identity and refuses reversal with retained source versions. Migration 0031 (upload policy and atomic-command coverage) preserves its predecessor catalog and refuses reversal with retained command evidence. Historical external-document bindings retain their existing identity and behavior.

## Verification boundary

Database and HTTP tests cover source version history, immutable records, migration reversal, exact retries, changed-content conflicts, access revocation during preparation, transactional rollback on event failure, CSRF enforcement, private downloads and request-size limits. The connected browser provides upload, Product decisions and Technical linkage. Current walkthrough and regression evidence appears in [interface remediation](../../../../../docs/curve/approved-interface-remediation.md) (verified scenarios and remaining delivery checks).

## Browser service

`CurveLocalPrdService` (typed local upload and protected-read client) reads current source metadata, uploads raw files with both version preconditions and retrieves verified bytes. It validates exact source scope, closed metadata, canonical digest, response Location, ETag and explicit replay state. Unsupported file extensions and oversized uploads are rejected before transport. Mutation transport retains uncertain outcomes after network loss or unverifiable success and never retries automatically. Protected content is checked against its stored size and SHA-256 digest before a Blob is returned; text is exposed as plain text. The consuming view must clear content on identity changes and revoke object URLs. The client also validates current review metadata, exact submission and decision records, posts Product review commands with version and retry headers, and retrieves digest-verified private feedback. Unknown command outcomes remain explicit and never trigger automatic retries. The Product panel now consumes these actions, requires feedback, displays current decisions and retains exact pending commands for explicit retries. The linked remediation record tracks authenticated acceptance and Technical linkage.

## Local Product review records

`local_prd_review.py` (immutable submission/decision record validation) defines the local-file review successor. A submission pins the uploaded source ID/version/metadata digest, normalized content digest, exact scope revision/membership digest, risk tier and the two current reviewer assignments. An approval or changes request names that submission and its digest, the Product gate assignment and decision maker. Standard/high risk requires distinct Product and Technical people; low risk retains the approved overlap allowance. A decision requires an Initiative version later than submission and a timestamp at or after submission.

Changes requested requires a private plain-text feedback reference. The feedback input validator rejects empty/whitespace, NUL, invalid Unicode and content exceeding 16 KiB. Feedback text is excluded from review metadata. Current-subject matching rejects replacement uploads even when their raw bytes are identical, changed scope, reviewer assignments and risk.

Migration 0032 persists these records through append-only LocalPrdSubmission and LocalPrdDecision models. Composite references keep source, submission and decision in the same workspace and Initiative. Database guards repeat metadata/digest/reviewer/feedback checks, and a unique submission reference permits one decision per submission. Retained review evidence prevents migration reversal. The consuming command performs current authorization and atomic Initiative transitions; the browser consumes these action results. Constructing or validating a record supplies no permission or effective approval. No external provider identity is synthesized for an uploaded source.

## Current review authority

`local_prd_review_authority.py` (transaction-bound current review eligibility) reuses native source access and checks exact Initiative/source identity before submission. The creator can submit, including when the creator is the assigned Product reviewer. Technical assignment alone does not grant submission. Reads retain historical submission and decision metadata while separately reporting whether the submission matches the current uploaded source, scope, risk and reviewer assignments.

The decision preflight requires Product-review state, the current Product reviewer, an undecided exact submission, its immediately following Initiative version, and matching current source/scope/reviewer pins. A returned PRD requires a replacement before resubmission. External checkpoints retain their original action path. This preflight is not an accepted command: the consuming command adds policy evidence, exact retry handling, protected feedback storage and atomic effects.

## Local review lifecycle

Migration 0033 adds explicit current local submission and controlling local decision references to Initiative. The lifecycle guard retains the external-checkpoint branch and handles local records separately. A native local submission moves Aligning to Product review; approval moves Product review to Planning; changes requested returns to Aligning. A replacement source and new submission can then proceed to review. Pause, resume and cancel preserve the controlling local references. Draft preparation still precedes submission.

Transitions require exact scope and reviewer pins, the latest uploaded source, the expected prior version, matching actor identity, and submission/decision insertion in the same transaction. Local records use the existing database transaction-provenance mechanism, including savepoint-safe top-level transaction IDs. Composite workspace/Initiative references prevent cross-scope pointers. Empty rollback restores the prior catalog; active local references prevent reversal.

Native lifecycle tests exercise these database transitions directly through helpers. They do not prove command-level authorization evidence, audit/outbox atomicity, idempotent HTTP acceptance or browser operation; separate command/API tests cover those server boundaries; browser operation is recorded separately in the remediation evidence.

## Local review commands and API

`local_prd_review_services.py` (atomic local Product commands) implements submission, approval and changes requested. It validates current native authority before protected storage access and repeats the full authority check before committing. Submission or decision, Initiative transition, domain event, outbox, audit and completed retry record commit together. A matching retry returns its original record under current actor authorization; reusing a key with changed command data is rejected. Migration 0034 adds the exact local review policy identity and runtime coverage seal.

`local_prd_review_views.py` (session-authenticated review API) exposes routes under the Initiative local-prd/v1 prefix:

- GET review/current/ returns current source, latest submission/decision, whether the subject still matches, Initiative version/state and available actions.
- POST review/commands/ accepts SUBMIT, APPROVE or REQUEST_CHANGES with exact source identifiers/digests. Decisions also require exact submission identifiers/digests; changes requested requires feedback text. If-Match, Idempotency-Key and CSRF headers apply.
- GET review/submissions/{id}/ and review/decisions/{id}/ return retained scoped metadata.
- GET review/decisions/{id}/feedback/ returns private plain text after authorization before and after storage access.

Successful commands return 201, exact retries return 200, and both provide Location, Initiative ETag and Idempotency-Replayed. Responses disable caching and content sniffing. Feedback content has a sandbox policy and never appears in decision metadata. These API actions remain subject to the local-only activation and storage configuration.

## New-Initiative submission edition

`local_prd_new_work.py` (closed version-2 submission validation) binds the current Product, Product version and business intent alongside the document, risk and two reviewer assignments. A new Initiative can upload in Draft, save its business intent, enter alignment and submit without selecting existing work. `local_initiative_context.py` (fresh native participant access) checks the owner, actor and both reviewers. Retained scope revisions continue through their original authorization path. Migration 0042 (additive new-work database guards and policy identities) accepts the explicit new edition while preserving immutable historical submissions.
