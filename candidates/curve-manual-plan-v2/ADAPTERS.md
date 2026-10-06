# Local authority and semantic adapters

Status: adapters integrated into the local Plane source after native ORM, protected
evidence and PostgreSQL qualification. The feature remains disabled; the local
file profile is not operationally qualified storage. The exact original input identity
remains immutable and separate from every current authorization observation.

## Native authority and local generations

The [policy adapter](../../apps/api/plane/curve/manual_plan_v2/policy.py) (native checks and transient
authority projection) calls the incumbent scoped reader independently for the
actor, every human owner and all three assigned reviewers while holding its
native locks. It checks the exact approved scoped PRD and controlling decision,
current Product/Initiative, risk, assignments, memberships and source observations.
The creator or an explicitly granted technical contributor may save. Native
membership alone never authorizes protected content or a save.

The [catalog adapter](../../apps/api/plane/curve/manual_plan_v2/synthetic.py) (owner-only material
capture, generations and atomic publication) persists a local observation ledger.
Each principal has a membership observation digest and a positive counter. A
separate source counter covers the aggregate of each principal's native source
fence. A counter advances only when the producer observes a change; it is not a
native database version, timestamp, hash interpreted as an integer, or a claim to
have seen every intermediate native change. Old principal entries remain even
when absent from one consumer's subset, preventing counter reset on reappearance.

The operator-side producer uses `prepare_native_catalog_authority` inside the
native transaction, then `publish_catalog` with the exact previous catalog digest.
Publication requires the next catalog generation, an owner-only stable lock file,
nonblocking exclusive lock, immutable retained material/plan/workspace identities,
monotonic grant counters, and empty-action tombstones for revoked principals.
It fsyncs a fresh bounded file and atomically replaces the catalog. This is a
library adapter, not an installed management command or an automatic background
permission synchronizer. Thirteen actual ORM tests cover producer refresh, stale
native observations, each actor/reviewer, original PRD and separate selected
evidence body/excerpt grants. Membership cannot replace a protected-object grant.

Consumers derive the native observations again and reject a stale ledger until
the producer refreshes it. They separately check every current Initiative and
object grant for every principal. The closed transient DTO binds original input
digest, current Initiative version, time, per-principal generations, source and
catalog generations, and a digest of all exact grants and observations. Aggregate
maximum grant counters are descriptive; the full exact grant inventory remains
in the final fence so a lower counter changing cannot be hidden by a maximum.

The same-machine owner-only files protect against untrusted request paths and
cooperating concurrent publishers. They do not claim to defeat an administrator
who can modify trusted code or arbitrary process memory, nor provide a distributed
cross-container grant store.

## Protected semantic bodies

The [semantic adapter](../../apps/api/plane/curve/manual_plan_v2/validation.py) (strict parser,
body-derived facts and inert plan validation) derives facts from these closed local
synthetic JSON editions. Each body is an exact original protected ObjectRef with
matching bytes, digest, length, material version and access envelope:

| Edition | Bound facts |
| --- | --- |
| `curve.synthetic-prd-body/v2` | Workspace/Initiative, requirement IDs/text/acceptance coverage and acceptance IDs/text |
| `curve.normalized-prd/v1-candidate` metadata with `curve.google-docs.normalized/v1-candidate` bytes | Existing approved PRD, conservative single plain-text tab with exact FR/AC traceability; native immutable metadata supplies ownership |
| `curve.synthetic-workflow/v2` | Workspace/workflow identity, fixed condition vocabulary and dependency artifacts |
| `curve.synthetic-quality-policy/v2` | Workspace/policy identity and required check IDs |
| `curve.synthetic-repository/v2` | Workspace/repository identity, exact base branch/commit, policy and context refs |
| `curve.synthetic-repository-policy/v2` | Workspace/policy/repository identity, allowed branches and required checks |

Requirement coverage is derived from the PRD; required checks are the union of
quality and repository policy requirements. The result must equal the catalog's
closed fact snapshot. Editing only that snapshot cannot weaken validation. Native
Initiative key, risk, code approver and proposed-delivery task set are independently
bound by the policy adapter. Native PRD metadata must identify one exact supported
schema/version pair and its original evidence snapshot; every selected evidence body and excerpt is retained
and authorized. These local body editions are not new public wire-schema approvals.

The normalized adapter consumes the retained approved bytes without rewriting
them or substituting a readiness assertion. Nested tabs, tables, footnotes,
non-text elements, unparsed declarations, duplicate sections/IDs, unknown references
and uncovered requirements fail closed. Nested heading text inside a section is
included, so it cannot silently discard a requirement. This narrow subset is an
admission limit, not complete Google document support or a live provider adapter.

## Worker and successor boundaries

The [Linux worker](../../apps/api/plane/curve/manual_plan_v2/validator_worker.py) (fixed child process
and closed receipt) has a 32 MiB encoded-job ceiling, 16 MiB material ceiling,
15 CPU seconds, 30-second parent wait, 512 MiB virtual address space, 32 descriptors,
16 KiB output-file ceiling and no core dumps. Bytecode writes are disabled before
restricted imports. Two nonblocking file locks limit concurrent jobs across API
processes sharing one container's temporary directory; this is not a distributed
limit across containers. The Mac path fails closed. Actual Linux tests cover valid
and invalid jobs, parser bounds, limits, competing processes and release of a slot
after killing its holder. Abrupt death of the API parent during a real validation
job and container-wide memory pressure remain operational acceptance cases.

The [successor loader](../../apps/api/plane/curve/scope_reopening_qualification.py)
(exact additive manual writer, then separate scope reader) preserves both historic
proofs and all 23 migration pins. The manual successor allows exactly two added
models, one migration, eleven new modules, the reviewed model/URL changes, and one
new draft writer inventory entry. Approval, controlling bindings, execution and
completion credit stay excluded. The scope-reader successor permits only its two
read modules and URL change. Structural validation alone supplies no authority;
the manual successor and migration catalog pins are installed with their exact
tested values; the separate scope-reader pin remains unset. The
[prospective qualification](qualification/README.md) (reviewed source/DDL proposal
and isolated complete-application tests) records the literal pins exercised with
the real loader before promotion. The installed test runner verifies the same
single implementation through the original read-only source bind. Neither code
promotion nor a successful test activates a workspace.

See the [promotion checklist](PROMOTION.md) (remaining database, proof and integrated
UI gates) and [verification record](VERIFICATION.md) (executed evidence and limits).
