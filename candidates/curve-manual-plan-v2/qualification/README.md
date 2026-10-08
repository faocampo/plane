# Complete-application qualification and source promotion

Status: exact qualified bytes promoted into local Plane source, 2026-10-06.
Workspace activation remains off. The prospective qualification checkpoint is
`27a16ae`; it is distinct from the earlier DDL experiment.

The [reviewed integration manifest](reviewed-integration.json) (exact source bytes,
patched files and proposed literal pins) records the application tested before promotion. Its relative source paths
describe the historical candidate at `27a16ae`, not a second runnable copy.
The [installed manual successor](../../../apps/api/plane/curve/manual_plan_draft_reconstruction_qualification_v2.json) (closed additive
qualification) has digest
`sha256:b4f16de1a78f0ffb7f62df770f6fe2e50636da3961e22bb193ba5e914b87215b`.

The expected physical catalog was reviewed against the explicit DDL delta:
three tables, 26 columns, six new functions, one replaced verifier, 12 indexes,
27 added constraints with one replaced policy constraint, and 33 added triggers
including internal foreign-key triggers. All other catalog rows remain intact.
Its literal pin is
`sha256:4f0c5e4b1ba7c5e00a3cf35fa55092cb71f571fa34a564f2859af7a46b0b67e8`.
The full proposed migration digest is
`sha256:2d27fec515cb31ba5f2ed95052e21723385679392defeaea67686a93fa3c3b50`.

The historical `qualification/stage_application.py` (bounded temporary application),
retained in Git at `27a16ae`, verified both historical proof files, all 23 migration bytes, every predecessor
runtime source and every candidate source before assembling under container
`/tmp` (disposable test storage). It applied the explicit promotion patch, checked
the resulting core bytes, copied the one candidate implementation, and substituted
only the two reviewed literal pins. It did not derive approval from the observed runtime, automatically fill unknown
digests, skip qualification, or edit the host checkout. Both original historical proofs remain byte-identical.

The [promotion patch](../promotion.patch) (two core runtime changes and one test
assertion update) records the changes now applied to models/routes and the policy
constraint, together with the qualified proof and migration.
The historical read-successor test now compares current sources to the complete
reviewed chain; its historical bytes, closed delta and adversarial cases remain
checked. This change does not treat the historical read proof as writer authority.

The [isolated runner](run_isolated.py) (installed-source phase selection)
now uses the single implementation through the original read-only API mount and
existing image. All database phases use this project's disposable test database;
run them sequentially. `--fresh-db` explicitly recreates only that test database.
`all` runs the runtime suite; `regression` runs the 186 historical cases. Host-only
doubles remain a separate unittest command and cannot qualify persistence.
No prospective assembly or alternate source mount remains in the current runner.

```sh
python3 candidates/curve-manual-plan-v2/qualification/run_isolated.py all
python3 candidates/curve-manual-plan-v2/qualification/run_isolated.py installed
python3 candidates/curve-manual-plan-v2/qualification/run_isolated.py migration
python3 candidates/curve-manual-plan-v2/qualification/run_isolated.py persistence
python3 candidates/curve-manual-plan-v2/qualification/run_isolated.py regression
```

The [test cleanup fixture](../../../apps/api/plane/curve/tests/conftest.py) (atomic immutable-table
cleanup) restores candidate TRUNCATE guards before the incumbent final full-catalog
check. Guards remain active throughout every test body; unmanaged seals survive
cleanup. Deliberate raw-SQL attacks use a complete graph captured from a real save,
then verified and rolled back. A positive direct-SQL control precedes the eight
omissions and eight substitutions. No production proof or guard is patched out.

Read the [verification record](../VERIFICATION.md) (actual results) and
[promotion checklist](../PROMOTION.md) (remaining integration and operational gates).
These checks do not qualify Gate 2, a mounted browser journey or a complete pilot.
