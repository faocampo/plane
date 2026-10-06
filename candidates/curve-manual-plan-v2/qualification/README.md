# Prospective complete-application qualification

Status: disposable integration evidence, 2026-10-06. Host runtime and workspace
activation remain unchanged. This is distinct from the earlier DDL experiment.

The [reviewed integration manifest](reviewed-integration.json) (exact source bytes,
patched files and proposed literal pins) defines the application under test.
The [proposed manual successor](proposed-manual-successor.json) (closed additive
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

The [assembly script](stage_application.py) (bounded temporary application)
verifies both historical proof files, all 23 migration bytes, every predecessor
runtime source and every candidate source before assembling under container
`/tmp` (disposable test storage). It applies the explicit promotion patch, checks
the resulting core bytes, copies the one candidate implementation, and substitutes
only the two reviewed literal pins. It never obtains an approval from the observed
runtime, fills an unknown digest automatically, skips qualification, or edits the
host checkout. Both original historical proofs remain byte-identical.

The [promotion patch](../promotion.patch) (two core runtime changes and one test
assertion update) registers models/routes and extends the policy constraint.
The historical read-successor test now compares current sources to the complete
reviewed chain; its historical bytes, closed delta and adversarial cases remain
checked. This change does not treat the historical read proof as writer authority.

The [isolated runner](run_isolated.py) (phase selection and bounded stdin archive)
uses the original read-only API mount and existing image. `authority` uses the
unchanged baseline test database. `installed`, `migration`, `persistence` and
`regression` use the separate disposable candidate test database. Do not run two
candidate database phases concurrently. `--fresh-db` explicitly recreates only the
selected test database; ordinary reruns reuse the migrated temporary database.
Children have closed stdin, so test setup cannot wait for an interactive answer.

```sh
python3 candidates/curve-manual-plan-v2/qualification/run_isolated.py authority
python3 candidates/curve-manual-plan-v2/qualification/run_isolated.py installed
python3 candidates/curve-manual-plan-v2/qualification/run_isolated.py migration
python3 candidates/curve-manual-plan-v2/qualification/run_isolated.py persistence
python3 candidates/curve-manual-plan-v2/qualification/run_isolated.py regression
```

The [test cleanup fixture](../postgres_tests/conftest.py) (atomic immutable-table
cleanup) restores candidate TRUNCATE guards before the incumbent final full-catalog
check. Guards remain active throughout every test body; unmanaged seals survive
cleanup. Deliberate raw-SQL attacks use a complete graph captured from a real save,
then verified and rolled back. A positive direct-SQL control precedes the eight
omissions and eight substitutions. No production proof or guard is patched out.

Read the [verification record](../VERIFICATION.md) (actual results) and
[promotion checklist](../PROMOTION.md) (remaining integration and operational gates).
These checks do not qualify Gate 2, a mounted browser journey or a complete pilot.
