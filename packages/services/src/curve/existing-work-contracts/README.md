# Existing-work candidate client contracts

This is typed transport and ephemeral read-state groundwork. It does not connect
rendered screens, enable any default-off backend setting, qualify a provider,
create a controlling binding, or confer native or gate authority.

## Surface and editions

- `project-association.service.ts` (association create, exact detail and END transport)
  uses Product preconditions for create and association preconditions for END.
  END continues to return unavailable while the backend's authoritative dependency
  guard is absent. A source creation-time observation is not current source
  freshness.
- `scope-proposal.service.ts` (finite C1 replacement and current/exact
  revision reads)
  accepts only the original `1.0` revision edition. Its returned Initiative ETag
  describes that immutable revision and is not a fresh write precondition.
- `scoped-prd-v1.service.ts` (explicit C2a metadata and command transport) requires
  `curve.scoped-prd/v1-candidate` and `EXACT_EXISTING_WORK_SCOPED_PRD_V1` on every
  command. Its mutation ETag is a strong numeric Initiative version. It is never
  interchangeable with Product, association, legacy Initiative, or Operation ETags.

Backend current native membership, artifact/evidence access, all reviewer guards,
and policy remain authoritative on every request. Successful metadata reads,
state labels, assignment labels and cached DTOs do not establish command authority.
No source names, descriptions, task bodies, member emails or protected rationale
are added to metadata DTOs. Decision rationale exists only in explicit command
input and the in-flight request. The client does not log, persist, replay, or place
it in read state. Returned client errors discard Axios request/config/body and
server error bodies, and Ajv diagnostics are cleared after validation.

## Validation and state

`manifest.json` (exact backend schema sources and SHA-256 pins) tracks raw-byte
mirrors. The legacy PRD read schema and earlier contracts are untouched.
`generate-existing-work-validators.mjs` (deterministic static Ajv generation)
uses the existing Ajv/format plugins and pinned repository formatter at build time;
there is no browser schema compilation, `eval`, or runtime `Function` construction.
Run it with `--check` to verify the committed generated outputs without writing.
The generator never fetches a schema or modifies backend sources.

Runtime decoders reject extra fields and wrong editions and bind workspace,
Product, Initiative, exact requested identity, known scope coordinates and known
checkpoint coordinates. They verify member ordering/uniqueness, counts, reviewer
assignment identities, and canonical metadata SHA-256 digests using Web Crypto.
A digest verifies the DTO's internal consistency, not source-body content, live
freshness or permission. Missing Web Crypto fails closed. Request bodies are
bounded to 64 KiB, responses to 256 KiB, and strings must encode losslessly as UTF-8.
The six-field Operation acceptance projection is separately closed because the
current scoped OpenAPI only describes that response; it does not supply its own
schema. Its workspace, type, status, version, ETag and exact Location are checked.
It has no Initiative field or completed checkpoint/decision body. Even a terminal
replay cannot be used as a fresh approval projection.

Every mutation needs an explicit safe numeric version and caller-owned idempotency
key. No automatic retry or replacement key is created. Pre-dispatch transport
failure/cancellation is distinct from `MUTATION_OUTCOME_UNKNOWN`: after POST dispatch,
network loss, cancellation, server 5xx, or an unverified successful response cannot
prove no effect. Aborting a request is never a domain cancellation. The unknown
outcome error retains no payload, key or rationale. Callers must reconcile current
state or preserve the exact original input, version and key if they explicitly
choose a replay; switching to a new key is a new command. Requests snapshot caller
input before awaiting CSRF. All reads/commands use the existing session transport.

`existing-work-read-state.ts` (cancellable latest-read slot) stores only decoded
read results. Refresh immediately clears old protected data; newer loads and
`clear()` invalidate older completions even if abort is ignored. Consumers must
clear on navigation, logout and access changes. It exposes no capabilities,
authenticated screen, mutation queue, persistence or absent-resource inference.

`scope-reopening-preconditions.service.ts` (separate minimal advisory precondition
read) implements only the approved protected GET. Its closed
`curve.scope-reopening-precondition/v1-candidate` edition returns the known
workspace/Initiative IDs, Initiative/scope revision pins, eligibility and pending
state. It exposes no Product, old source/member, association or checkpoint data.
The server requires current human ProductApprover authority and the exact read
ACL; eligibility is never a client write grant. The numeric response ETag must
match the returned Initiative version, and callers may supply a known Initiative
version to reject a stale response. Initial discovery may omit that expectation.

The reopening mutation and its new C1 revision edition remain unsupported here.
A new C1 revision edition fails closed instead of widening `1.0`. Pending reopening
can
make legacy review metadata and C2a protected GETs unavailable. That is not proof
of an absent PRD. Recovery will need an explicit freshly authorized observation
capture/new submission flow; a GET must never silently trigger that mutation.
The existing standalone UI fixture demo remains separate.

## Verification

`apps/web/tests/curve/existing-work-client.test.ts` (source-imported transport,
closed-wire, redaction and stale-state regression cases) uses
`fixtures/existing-work-v1.json` (synthetic candidate requests and metadata with
independently computed canonical digests), plus
`fixtures/existing-work-utf8.json` (Python-computed canonical accented, astral and
CJK metadata digest fixtures). No account, credential, real source or
live request is used. Schema parity is checked against the backend in this repo.
The original Curve candidate schema bytes were also independently compared during
implementation; a sibling Curve checkout is not required to run these tests.

From the web app, run `pnpm test tests/curve/existing-work-client.test.ts` and the
broader `pnpm test tests/curve`. Use `pnpm exec tsc -p
tests/curve/tsconfig.existing-work.json` to type-check the source-imported tests
and
services against this checkout's DTOs under the web app's ES2022 target. Run the
normal package build/type/lint checks, plus
`node packages/services/generate-existing-work-validators.mjs --check` at repo root.
If dependencies are symlinked to another worktree, source-imported tests still
exercise these services, but type/build checks must resolve this checkout's types
rather than silently accepting the sibling's old declarations.

## Native association prerequisite

`project-association-preconditions.service.ts` (closed advisory native-project
precondition GET) discovers the server-owned installation UUID and current Product
version for an exact authorized workspace/Product/source selection. Its separate
`curve.project-association-precondition/v1-candidate` schema adds no source body,
role or command authority. An ACTIVE association ID is returned only for the
selected Product; a conflict elsewhere is redacted. Archived or unavailable
Product/project selections fail closed. The returned strong Product ETag must
match the DTO exactly. Existing CREATE still independently checks authority,
version, uniqueness and idempotency. No mutation or automatic retry is performed.

`packages/services/tests/project-association-preconditions.test.ts` (synthetic,
source-imported read transport and schema parity coverage) can be run from the
repository root with the web app's existing Vitest binary:

```sh
apps/web/node_modules/.bin/vitest run \
  --config packages/services/tests/vitest.association-read.config.mjs
packages/services/node_modules/.bin/tsc \
  -p packages/services/tests/tsconfig.association-read.json
```

The dedicated test configuration resolves the already-installed web test runner
and this checkout's source types; it does not require changing shared dependency
links or overwriting another checkout's built packages.
