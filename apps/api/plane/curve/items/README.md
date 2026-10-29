# Roadmap Item command candidate

This local candidate creates a linked Roadmap Item and Initiative in one
transaction. The Initiative begins as a draft. Its two reviewer assignments are
Product for the PRD and Technical for the implementation plan. Assigning a
reviewer does not establish approval.

The current Roadmap owner must have active native membership and Product access.
Creation rechecks the parent version, Feature and Milestone placement, reviewer
eligibility, and access to the prepared scope document. The Item, Initiative,
assignments, events, outbox entries, command receipt and audit commit together.

## Interrupted creation

The browser retains an opaque command identifier in tab storage before sending
creation. It retains no draft body or reviewer permissions there. A current,
authenticated actor may reconcile their original request with the receipt API.
A completed result returns the original Item and Initiative identifiers. An
unresolved result keeps creation locked because absence of a visible receipt
cannot establish that a request will never commit.

The cancellation endpoint accepts an empty JSON object and the original UUID
`Idempotency-Key` header. It uses session authentication and CSRF protection.
Its outcome is one of:

- `COMPLETED`: creation won; return the original linked pair.
- `CANCELLED`: cancellation reserved the original creation identity with an
  immutable terminal receipt. A delayed creation conflicts before side effects.
- `UNRESOLVED`: an existing unfinished receipt remains unchanged; keep the
  original attempt locked.

Creation and cancellation take the same native workspace lock through physical
commit. Cancellation is scoped to the current actor, workspace, Product,
Roadmap, command and original key. A current Product reader can settle their own
attempt after Roadmap ownership changes. Current membership and Product access
remain required. Repeating cancellation after a lost response is safe and returns
the same outcome. The existing recovery GET retains its original response
contract; it does not project cancellation markers.

The browser exposes cancellation only for a known unresolved attempt. It keeps
the original identity when cancellation is uncertain, and repeats cancellation
on explicit retry. A confirmed cancellation and successful locator cleanup are
required before a fresh command. The entered draft remains available for review;
a completed creation instead opens the original Item.

## Qualification and delivery

Additive migrations 0049–0053 preserve the previous policy identities, schema
seals and runtime source pins. New runtime flags default to disabled. Candidate
checks and synthetic local tests establish only their recorded scope. Full
browser acceptance through Product and Technical approvals, complete regression,
publication review and delivery remain separate gates.

## Historical approval integration gap found during runtime preparation

Before migration 0054, creation set `Initiative.mode` to `ROADMAP` while the local
document context and local plan authority accepted only `STANDALONE`. The
database function `curve_local_new_work_context` also limited its submission
edition to standalone Initiatives. This prevented the linked Item from completing
the local Product/Technical document journey. The installed successor below
addresses that integration gap.

The successor acceptance required Roadmap-backed document review across both
application authority and database guards. It must validate the current reciprocal
Item/Initiative link, Product, active Feature and Milestone placement; retain
current human membership and exact reviewer assignments; and bind approval to
the exact document and applicable Item scope. Changes to an approved subject
must invalidate its current approval projection. Preserve existing standalone
and retained-scope editions and their immutable evidence.

Acceptance must create a new Item, upload and submit its PRD, approve as the
assigned Product reviewer, upload and submit the implementation plan, and approve
as the assigned Technical reviewer. Cover changed subjects, lost membership,
wrong reviewers, interrupted responses and retries. A successful creation or
reviewer assignment alone does not satisfy this acceptance.

## Installed Roadmap document review successor

Migration 0054 adds a distinct Roadmap submission edition that pins the Item
identity and complete protected scope reference alongside the PRD and Product
context. Native authority checks the reciprocal link, live hierarchy, active
human participants and exact reviewer assignments. SQL guards enforce the same
subject and permit the Product-to-Technical lifecycle for Roadmap work.

The synthetic native journey covers creation, both document approvals, reopening
the PRD, replacement approval and invalidation of the older plan projection.
Authenticated local browser acceptance covers creation, both assigned reviewers,
and document removal/recovery when Technical membership is revoked/restored.
Historical review editions and evidence retain their original scope.

Authenticated browser recovery also covers a committed creation whose success
response was replaced with an unavailable response. Recovering the original
attempt opened its saved Initiative, and a native query confirmed exactly one
linked Item. A second browser scenario leaves the unresolved attempt through
the navigation warning, reloads the page, returns to the Roadmap, and recovers
the original Item using the retained receipt locator. The draft fields remain
empty and creation stays locked until recovery succeeds. A native query confirms
exactly one linked pair. Full regression and PR delivery retain separate gates.

The authenticated cancellation scenario drops a creation request before command
execution, confirms that the draft stays locked, and cancels the original attempt.
The browser then retains the draft, returns focus to its name and enables creation.
A native replay of the original request is rejected without creating either record.
A fresh browser submission subsequently creates its linked Item and Initiative.
The temporary synthetic fault is removed after verification.
