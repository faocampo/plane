# Local implementation-plan review

The approved interface has two human stages: Product approves the PRD; Technical approves the implementation plan. A local plan revision refers to a real local PRD submission and its approved decision. It retains those exact IDs and digests rather than assigning them external-provider checkpoint or artifact identities.

## Current preparation boundary

`local_plan_authority.py` (current native eligibility for local plan preparation) resolves existing native workspace, scope, source and reviewer access. Preparation requires a standalone Initiative in Planning, its current local submission and controlling approved decision, and a submission that still matches the latest source, edition-specific context, risk and reviewer assignments. External checkpoint references must be absent. Upload additionally requires the Initiative creator, the expected Initiative version, and exact submission/decision pins supplied by the caller. Technical reviewers may read this preparation context; their assignment does not grant creator upload permission.

This result is transaction-bound preparation evidence. A consuming upload or review command must record its policy decision, recheck authority after protected I/O and commit its audit, state and retry result atomically. It is not a completed upload or Technical approval.

## Revision identity

`local_plan_review.py` (immutable local plan revision validation) defines `curve.local-plan-revision/v1-candidate`. Each revision retains its workspace and Initiative, source version and predecessor, exact approved PRD submission/decision pins, protected original and normalized snapshot references, uploader and timestamp. First revisions have no predecessor; later revisions name a different retained revision. Timestamps follow the Product decision, and the preparation Initiative version follows the approval version.

The document is PDF, Markdown or plain text, up to 10 MiB. Its normalized snapshot uses the existing lossless local-upload representation. Reference metadata excludes document content and filename. A canonical digest covers the complete closed record. Validation proves structural identity; current authority, predecessor persistence, protected-byte integrity and atomic command effects are separate requirements.

## Remaining delivery work

The local upload and review routes are connected to the Technical document panel. A changed PRD invalidates eligibility of its earlier plan while retaining historical records. Authenticated walkthroughs have verified upload, feedback, replacement, resubmission and approval. Current acceptance and remaining regression/publication work are recorded in [interface remediation](../../../../../docs/curve/approved-interface-remediation.md) (verification evidence and remaining delivery checks).

## Persistence

`local_plan_models.py` (append-only plan revisions) and migration 0035 (local plan revision table and database guards) retain each document revision with explicit local PRD submission, approval and predecessor references. Composite foreign keys bind all three references to the same workspace and Initiative. Revision versions are unique per Initiative and each successor names the preceding version.

Database insert guards validate the closed payload shape, canonical digest, exact approval identity and approved state, document reference limits and media types, and version/time ordering. Update, delete and truncate guards preserve saved revisions. A retained revision prevents migration reversal. Runtime qualification covers the new model, source inventory, migration and physical catalog. These storage checks support the consuming upload/review commands; they do not themselves grant upload permission or Technical approval.

## Native upload command

`local_plan_services.py` (atomic local plan upload) accepts bounded document bytes after creator authorization and exact Product-approval checks. It requires both the Initiative version and current plan revision version. The request digest includes content, media type, versions and approval pins. An exact retry returns its retained revision; a reused key with different content or pins conflicts.

The command prepares original and normalized snapshot objects outside database locks, then repeats native authorization and compares the current approval/revision observation before committing. Revision metadata, event, outbox, audit and completed retry result commit together. Prepared files are retained on uncertain outcomes until reference-aware cleanup can prove safe erasure. `local_plan_policy.py` (upload authorization evidence) and migration 0036 (exact upload policy identity and catalog seal) bind each accepted operation to the qualified local policy. The HTTP transport consumes this server command; the Technical document panel consumes the current upload and preview results.

## Upload and preview API

`local_plan_views.py` (session-authenticated plan transport) exposes the Initiative `local-plan/v1/revisions/` collection for raw PDF, Markdown or text uploads. Requests require `If-Match`, `Idempotency-Key`, `X-Curve-Plan-Version`, and the exact `X-Curve-Prd-Submission-Id`, `X-Curve-Prd-Submission-Digest`, `X-Curve-Prd-Decision-Id` and `X-Curve-Prd-Decision-Digest` values. Current values come from `revisions/current/`, which returns the retained revision, Product submission and approval, Initiative version, and upload availability.

Successful uploads return 201; exact retries return 200. Both provide Location, Initiative ETag and explicit Idempotency-Replayed. Revision metadata and protected bytes are available from `revisions/{id}/` and `revisions/{id}/content/`. Content reads verify the normalized snapshot and its exact retained original, then repeat current native access and compare the authority observation. Text is served as plain text; all responses disable caching and sniffing, and document content uses a sandbox policy. The upload middleware bounds this route at 10 MiB independently of the generic request-body limit.

These routes cover plan preparation. The review API below supplies Technical submission, decisions and feedback. The document-first interface consumes both preparation and review results.

## Technical submission and decision records

`local_plan_review.py` (exact Technical review subjects and decisions) defines closed canonical submission and decision records. A submission pins the plan revision, its content digest, the approved Product submission and decision, and the assigned Technical reviewer. A decision pins that submission and records either approval or a change request. Change requests require a protected plain-text feedback reference of at most 16 KiB; approvals carry no feedback reference.

`local_plan_models.py` (append-only review persistence) and migration 0037 (Technical submission and decision tables) retain one submission per plan revision and one decision per submission. A change request therefore requires a new document revision before another submission. Scoped foreign keys, payload guards and canonical digests prevent cross-Initiative references and mismatched reviewer or document identities. Database guards reject changes to retained records and reversal while records exist. Initiative versions may remain equal during plan preparation and Technical review; document and submission identities provide the immutable review subject.

The consuming command and transport behavior is described below. The connected interface presents these records; execution readiness remains separate delivery work.

## Current Technical action authority

`local_plan_authority.py` (fresh native review permissions) resolves the latest plan revision and its saved submission and decision under the Initiative lock. It verifies the current Product approval, two assigned approvers, membership, source access and Initiative version. Only the creator can submit an unsubmitted current plan. Only the assigned Technical reviewer can approve or request changes on its exact pending submission. A previous decision prevents a second decision; a change request permits a replacement revision and a new submission. Pending and approved reviews prevent fresh uploads.

The authority observation includes revision, submission and decision identities so a review change during protected storage I/O invalidates the earlier observation. A separate internal read-result action lets the creator retrieve a retained upload result while review is locked. `local_plan_services.py` (atomic uploads and exact retries) checks for an existing retry record before requiring a fresh upload grant. It returns only a matching saved result and records a replay audit; a new retry key still requires upload eligibility. The current Product-approval and Initiative-version checks remain required for upload-result reads.

## Atomic Technical commands

`local_plan_review_services.py` (submit, approve and request-changes transactions) requires the exact plan revision, Product submission and approval, Initiative version, and a retry key. A decision additionally names the Technical submission; a change request requires nonempty protected feedback. The service validates the stored snapshot against the exact original document outside locks, then repeats current native authorization and compares the revision/review observation before saving effects.

Submission or decision metadata, a distinct review-record event, outbox delivery, audit and retry outcome commit together. The Initiative remains in Planning at its existing version; the review record supplies its immutable subject and outcome. Exact retries return the retained record under current authorized-role checks without producing another review event. Failed commits roll back metadata effects while prepared feedback stays available for reference-aware recovery.

`local_plan_review_policy.py` (native Technical authorization evidence) and migration 0038 (additive exact review-policy identity) retain policy decisions without changing earlier policy editions. Reversal refuses retained command-policy evidence. Full runtime qualification includes the new commands, source files, model constraint and migration.

## Technical review API

`local_plan_review_views.py` (authenticated status, commands and protected feedback) exposes `local-plan/v1/review/current/`, `commands/`, and `{submissions|decisions}/{id}/` under the Initiative route. Decision feedback is available at `decisions/{id}/feedback/`. Current status includes the revision, its Product submission/approval, Technical submission/decision, current-revision eligibility and available actions.

Commands accept closed JSON bodies with action, exact plan and Product pins, and submission pins when deciding; only change requests accept feedback. They require session authentication, CSRF, Initiative ETag and a retry key. Created outcomes return 201; exact retries return 200. Both carry Location, ETag and Idempotency-Replayed. Feedback is protected plain text with no-store, nosniff and sandbox response controls. Reads recheck access after storage I/O. Current upload availability reflects pending and approved review locks; exact retained upload retries still work through the upload endpoint.

## New-Initiative context

New-work PRD submissions bind Product identity/version and business intent in place of existing-work scope pins. Plan preparation dispatches current-subject validation using the stored PRD edition. Migration 0042 (new-work submission validation and exact successor policy identities) preserves historical scoped review behavior.
