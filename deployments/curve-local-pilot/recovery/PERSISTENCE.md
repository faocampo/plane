# Persistent storage qualification for the synthetic pilot

[Persistence driver](persistence.py) (owned volume lifecycle and failure handling)
extends recovery without changing application runtime, migrations, native seals,
the demo or remote refs. Separate PostgreSQL and protected-object named volumes
survive shutdown and container replacement during the exercise. Its owned resources
are removed afterward.

This is engineering evidence for a future operating profile. It does not migrate
the demo, leave a new service active, select retention, enable providers or approve
participant identities. There are no host ports or external network. PostgreSQL's
trust mode is confined to this disposable namespace; it is not a shared-environment
credential or deployment design.

## Run and recover from interruption

Use the verified synthetic backup, original source and existing private inputs.
Create a new owner-only directory for the journal first.

```sh
python3 deployments/curve-local-pilot/recovery/persistence.py exercise PRIVATE_BACKUP \
  --synthetic-local --source ORIGINAL_SOURCE_CHECKOUT \
  --operator-settings PRIVATE_SETTINGS_FILE \
  --access-file PRIVATE_SYNTHETIC_ACCESS_FILE \
  --target-file PRIVATE_SYNTHETIC_TARGET_FILE \
  --journal NEW_PRIVATE_JOURNAL
```

The journal destination must be new; its parent must be owner-only and owned by
the operator. Atomic, flushed writes use mode 0600. The journal holds stage,
resource ownership and safe case names, never credentials or evidence bodies.
Keep it private because resource topology is operator data.

Before resource creation, the driver validates backup hashes, exact source,
immutable local image IDs and complete private HTTP inputs. Existing container
or volume names are refused, even with a matching label. Resources are recorded
as managed only after checking absence; cleanup checks ownership again.

Normal completion, errors, Ctrl-C and SIGTERM trigger scoped cleanup. A killed
host process or unavailable Docker daemon may leave resources; incomplete disposal
is not success. Once Docker is available, use the exact trusted journal:

```sh
python3 deployments/curve-local-pilot/recovery/persistence.py cleanup \
  --journal PRIVATE_JOURNAL
```

Cleanup is idempotent for removed resources and refuses mismatching ownership.
Never edit a journal to adopt another installation. A partial initialization is
not a ready service: clean its target and start a fresh exercise from the backup.
Neither restart path runs the demo seed script.

## Qualification boundaries

| Boundary | Required evidence |
| --- | --- |
| Restore | Original migrations reconstruct exact DDL; all 151 fixture tables, schema and native seal match. |
| Protected persistence | Initialize once with owner-only permissions; check catalog, complete inventory and every object digest. Initialization cannot overwrite an existing store. |
| API readiness | Persisted objects mount read-only and are verified before WSGI starts. Normal login and native protected read succeed; no Gate 2 command. |
| Graceful stop/resume | Every post-login row persists; compare rows/schema/seal before another API read. |
| Crash/replacement | Kill PostgreSQL with an open synthetic-user update, remove its container and recreate on the same volume. Committed rows survive; the open transaction rolls back. |
| Storage failure | Read-only initialization fails. Broad permissions and corrupt bytes prevent readiness. Exact repair precedes the next authenticated read. |
| Ownership | Refuse same-name resources, including matching-label collisions; failed initialization and journal cleanup preserve them. |
| Disposal | Remove only managed helpers/database and volumes. Failure leaves the journal for explicit recovery. |

Database bounds: 512 MiB, one CPU, 128 PIDs, read-only root and no Docker log
driver. API probe: 1 GiB, one CPU, 128 PIDs. Store helpers: 256 MiB, one CPU,
64 PIDs, no capabilities and no-new-privileges. These are qualification defaults,
not measured pilot capacity. Migration helpers retain existing recovery bounds.
No per-volume disk quota or disk-exhaustion behavior was qualified.

PostgreSQL `fsync`, `full_page_writes` and `synchronous_commit` must be on.
Process/container crashes were tested; Mac power loss, Docker VM loss and device
failure were not. All database rows include login-created sessions, but continued
acceptance of a particular browser cookie across restart was not tested. Each
new API probe reauthenticates and checks current native authority.

The store checker is an operator readiness gate, not a substitute for per-request
authorization. The prior identity/fault exercise separately tested native denials
after disablement, corruption and membership revocation.

## Tests and activation boundary

```sh
python3 -m unittest discover -s deployments/curve-local-pilot/recovery -p 'test_*.py' -v
```

Twenty-five tests cover backup, persisted-object, journal, ownership, missing-volume,
failed-initialization and cleanup boundaries. The Docker lifecycle exercise and
separate native ownership checks provide evidence beyond those unit tests.

[Qualification record](persistence-qualification-2026-10-07.json) (final native
results, ownership checks, tool hashes and acceptance limits) records the exact
run. The final lifecycle completed in 299.306 seconds, including 149.625 seconds
for restore, with 151 tables and 24 objects checked. These observed local durations
are not an RPO/RTO commitment. All owned resources were removed.

See [pilot gates](../PILOT_GATES.md) (operator and activation decisions) and
[UX review](../UX_REVIEW_TODAY.md) (human decisions for Today). Real retention,
encryption, backup ownership, participant roles, current grants and activation
remain subject to the approved private profile and D-003/D-009 decisions.
Synthetic success does not certify RPO/RTO or authorize a new publication cut.
