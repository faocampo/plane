# Two-stage document review

## Approved experience

The repository owner approved this interface and review model in the development conversation:

1. The Initiative owner uploads a requirements document. Product approves that exact PRD or requests changes.
2. After Product approval, the owner uploads an implementation plan. Technical approves that exact plan or requests changes.

The current experience has two approval stages. Code quality checks remain delivery evidence; there is no Code Approver assignment in the current Initiative creation and document-review flow.

A light document surface presents the current version, status and next action together. Reviewer responsibilities, activity and management controls expand on demand. Requested changes appear beside the document. A replacement must be uploaded before a rejected version can be submitted again. Updating an approved PRD requires renewed Product review and an updated Technical plan.

## New Initiative and existing work

A new Initiative can upload its PRD in Draft. Business intent is saved before alignment begins; the owner then sends the uploaded document for Product review. Existing work selection is not a prerequisite for this new-Initiative document flow.

New-work submissions bind the current Product and its version, business intent, document version and digests, risk tier, and both reviewer assignments. Existing-work submissions retain their original scope-revision and membership pins. Historical records preserve their schema edition and original subject.

Every protected read and command checks current participant access. The owner controls document uploads; only the assigned reviewer can decide the corresponding stage. Current assignment, source, context and version checks are repeated before command effects. Immutable submissions and decisions retain the reviewed version across replacement and reopening.

## Current delivery boundary

The implementation is an explicitly enabled local review candidate. Production storage, provider integration, deployment qualification and later milestone gates require their own evidence. Local tests and browser walkthroughs establish only their recorded scope.

See [approved-interface remediation](approved-interface-remediation.md) (implemented UX changes, verification evidence and remaining acceptance). The current application sources are [Initiative workspace](../../apps/web/components/curve/initiatives/initiative-workspace.tsx) (document-first composition), [document review](../../apps/web/components/curve/initiatives/local-document-review.tsx) (the two approval stages), [new Initiative context](../../apps/api/plane/curve/local_initiative_context.py) (current native participant authorization), and [new-work submission](../../apps/api/plane/curve/local_prd_new_work.py) (Product and document approval pins).
