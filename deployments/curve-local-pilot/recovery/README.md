# Synthetic local pilot recovery exercise

This operator tool captures the existing local review database and fixed synthetic
protected catalog, then proves restoration into a new disposable target. It does
not restore over an existing installation or activate an operational installation.
The running review checkout and its source revision remain unchanged.

[Recovery tool](recovery.py) (capture, integrity checks and isolated restore) and
[refusal tests](test_recovery.py) (corruption, archive boundaries and cleanup)
are independent of the frozen application runtime and migration proofs.

## Capture boundary

Supply an explicitly authorized synthetic Compose project, its `api` and `db`
services, the exact clean application checkout and its full commit. The API must
mount that checkout's `apps/api` (application source directory) read-only at
`/code` (container source mount). The existing synthetic resolver validates file
ownership, modes, catalog structure and immutable object hashes during capture.

The capture acquires the catalog producer's shared file lock and SHARE locks on
all current public-schema tables. Reads remain available; writes can wait briefly.
It exports a PostgreSQL snapshot for the dump and data fingerprints, and releases
the locks on success or failure. Lock acquisition is bounded and holders expire
after 60 seconds. A failed or expired lock prevents a completed backup artifact.
Do not run concurrent DDL or modify protected files outside the catalog producer.
This is a cooperating local operator profile, not a general distributed snapshot.

Example invocation, replacing each uppercase argument with an operator-resolved
value; none is a credential:

```sh
python3 deployments/curve-local-pilot/recovery/recovery.py capture \
  --synthetic-local \
  --source SOURCE_CHECKOUT --source-commit FULL_COMMIT \
  --project SYNTHETIC_PROJECT \
  --api-container API_CONTAINER --db-container DB_CONTAINER \
  --user DATABASE_USER --database DATABASE_NAME \
  --root PROTECTED_ROOT --output PRIVATE_NEW_BACKUP_DIRECTORY
```

The destination must be new. Partial captures are removed. The completed directory
is private (0700), with private files (0600). It contains:

- `database.dump` (PostgreSQL custom archive, including sessions and password hashes).
- `protected.tar` (catalog and all referenced immutable object bodies).
- `manifest.json` (source commit, database version, file hashes, schema hash,
  table row counts and hashes, catalog identity and timing).

Keep all three outside Git and shared logs. Checksums detect corruption against
the trusted local manifest; they do not authenticate an untrusted replacement
manifest. This profile has no signing key or new credential generation.

## Verification and restoration exercise

```sh
python3 deployments/curve-local-pilot/recovery/recovery.py verify PRIVATE_BACKUP_DIRECTORY
python3 deployments/curve-local-pilot/recovery/recovery.py exercise PRIVATE_BACKUP_DIRECTORY \
  --source ORIGINAL_SOURCE_CHECKOUT
```

Verification rejects missing, changed, duplicate, linked, oversized or unsafe
archive members before restoration. It checks each catalog object's own digest
and byte count as well as archive hashes. No generic archive extraction is used.

The exercise uses the immutable local PostgreSQL and API image IDs captured in
the manifest. PostgreSQL 15.7 is the supported profile. It never pulls an image.
It creates a uniquely named database container without network, host ports or
host mounts, with a read-only root and disposable database storage. A temporary
migration container joins only that isolated network namespace and mounts the
exact original source read-only. Labels bind cleanup to this run's containers.
It cannot name an existing database as a restore target.

The exact native migrations first reconstruct the schema, which must match the
captured DDL before any data restore. PostgreSQL can rewrite array casts when
replaying deparsed dump DDL; that route failed exact schema comparison and is not
used to re-establish the qualified catalog. No runtime seal is changed to accept
a different catalog.

Only the new target's bootstrap rows are cleared, in a session using replication
mode. Data restoration temporarily disables triggers in that disposable target;
any restore error fails the exercise. These operations never target the source.
The exercise compares the schema DDL again, every public table's sorted row
fingerprint and all protected bytes. Trigger state is included in the schema check.
It also executes the unchanged native catalog-seal verifier after restoration.
Random psql restrict tokens are excluded from schema comparison; owners and grants
are intentionally omitted by the capture profile. Object files are restored into
a private temporary directory with owner-only permissions and removed afterward.

The default exercise does not start an API against the copy. An optional HTTP
read check re-establishes the exact source revision, current operator profile,
existing synthetic account and source access inside the isolated namespace:

```sh
python3 deployments/curve-local-pilot/recovery/recovery.py exercise PRIVATE_BACKUP_DIRECTORY \
  --source ORIGINAL_SOURCE_CHECKOUT \
  --operator-settings PRIVATE_SETTINGS_FILE \
  --access-file PRIVATE_SYNTHETIC_ACCESS_FILE \
  --target-file PRIVATE_SYNTHETIC_TARGET_FILE
```

All three private inputs are required together. The credential file must be
owner-only and contain the existing `approver` (synthetic email) and `password`
(local login secret) keys. The target contains `workspace` (slug), `initiative_id`
(UUID) and `state` (expected manual state). The settings are trusted operator
Python configuration; do not supply untrusted files. Inputs are mounted read-only
and never copied into the repository or returned in results.

[HTTP probe](http_probe.py) (isolated login and protected read verification) starts
the original WSGI application on an ephemeral loopback port in the copy's network
namespace. No port is published to the host. It restores the catalog under native
owner-only permissions, logs in through the normal session endpoint and verifies
the authenticated principal, manual state, version ETag and exact definition digest.
By default it sends no Gate2 command. It is an HTTP check, not browser acceptance;
the original demo's real browser journey has separate evidence.

Add `--pilot-controls` (isolated identity and injected-fault profile) to the same
exercise invocation to check anonymous access, an invalid password, role-bound
approval, a different workspace, runtime disablement, protected-object corruption,
and revocation of workspace membership while the session remains authenticated.
The access input then also needs `owner` and `code_reviewer` (existing synthetic
account emails). It sends two schema-valid APPROVE commands with valid session
CSRF, version and idempotency headers: the owner and code reviewer must both be
denied. The assigned technical approver's read must still offer APPROVE.

Faults affect only the new disposable copy. Flags, bytes and membership are
restored in finally blocks; the source demo is never modified. Protected denials
must match an unknown resource's status and body without an ETag. The Initiative,
draft, revision, control, decision and claim histories must remain unchanged.
Authentication sessions and no-effect security records are outside that final
business-graph comparison. This profile does not prove IdP integration, MFA,
distinct real human identities, revocation of every possible object grant, or
safe command behavior under every fault. Those remain separate qualifications.

The temporary API and database are removed afterward. This supplies no rollout
or production activation approval. Original permissions are not inferred from a
backup: the unchanged API checks the restored actor and current native authority.
Redis queues, Temporal, providers, object stores beyond this fixed catalog,
operator configuration and plaintext login credentials are not captured.

## Validation

```sh
python3 -m unittest discover -s deployments/curve-local-pilot/recovery -p 'test_*.py' -v
```

The twelve focused tests cover valid material, database corruption before any
restore process, object digest mismatch, missing objects, unsafe paths and links,
duplicate members, manifest path boundaries, cleanup after a failed startup and
refusal to remove a container carrying another run's ownership label, incomplete
operator inputs, overly broad credential-file permissions and refusal to run
pilot controls without the complete private HTTP profile.
The real restore exercise is separate evidence; unit tests do not substitute for it.

An observed synthetic run is a bounded qualification result, not a production
backup service, retention policy, RPO/RTO commitment or full R1 disaster-recovery
approval. Keep exact run results in the operator's private evidence directory.
