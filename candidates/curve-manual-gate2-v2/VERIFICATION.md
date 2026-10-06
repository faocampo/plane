# Gate2 qualification evidence

All evidence is synthetic and local. The final prospective suite passed **23 tests
in 359.34 seconds**: 20 Gate2 tests and three exact historical migration gates.
The installed-source suite passed **100 tests in 1417.36 seconds** at local commit
`8aede16b4aee1aa66eb0b9469c4c849b34250f6e`: 57 manual, 23 scope and 20 Gate 2
cases. All **186 historical regressions pass in 525.07 seconds** at that same commit,
with the new product feature defaults disabled and the complete successor enforced.
Integration is `a69559f990c995f0d2c930306544979afd005d93`. An initial combined
run passed 69 tests then stopped at a historical assertion requiring the older
scope-reader inventory. The test now validates the unchanged reader proof followed
by the exact pinned Gate 2 successor before comparing all installed source hashes.
No runtime, schema, migration or proof byte changed for this test correction.

- The initial expanded suite passed 15 native PostgreSQL/API cases in 269.67 s.
  It includes complete PREPARE/APPROVE/RECONCILE/RELEASE and original replay,
  actual session/CSRF, wrong/stale authority, same/different-key concurrent
  commands, complete positive raw SQL graph, twenty component omission/substitution
  attacks, retained mutation/truncate guards, pause/cancel, started work, wrong
  generations, post-approval editing refusal and complete migration reversal.
- Three ownership/revision cases passed in 87.63 s: competing Initiatives,
  release/reacquisition generation, original approval retry, loss of membership,
  unassociated native project movement, replacement definition read and resubmit.
  The final suite also checks newly associated project movement and proof/seal gates.
- Before mounting, the typed browser-client/component suite passed 44 cases. They include the
  existing draft client, strict response/material validation, explicit review,
  stale/unknown results, same-command retry, authority clearing and prepared
  replacement isolation. These are component/client tests with synthetic transports.
- Full application TypeScript and all **380 web tests across 33 files** pass through
  the normal Turbo dependency build. The manual client/panel subset now contains
  45 cases including the default-off mount. The installed pure host suites pass
  **107 manual plus 31 scope-reader tests**. Python Ruff checks pass.
  Authenticated browser-to-backend pilot acceptance remains separate evidence.

The [visual review](../../apps/web/.impeccable/review/manual-gate2/review.md)
(bounded desktop/mobile review) and its verdict record cover synthetic rendering,
not API persistence or user acceptance. No protected real document, credential,
provider call, model call or production service was used.

## Preservation

The manual proof remains
`sha256:b4f16de1a78f0ffb7f62df770f6fe2e50636da3961e22bb193ba5e914b87215b`.
The scope-reader proof remains
`sha256:c2e37caa561e943bf4f2883c62d8ed889c74a55809fa1f5ffc93aed5d4ce093e`.
All 24 previous migration files remain byte-identical to that predecessor.

The reviewed 0025 physical catalog is
`sha256:4d33761d55c0f0cb509af13a729cdb6a7479c7b8ca662fc843f856bce33adb08`.
The separate prospective proof records exact source/migration bytes; it is not a
production activation record. Superseded DDL experiment pins are historical only.

## Reproduction

The complete prospective assembly is preserved at local commit
`8fc8e15fb36fa0a8aa7890b40971c8df814c0753`. The executable overlay was removed on
promotion so only the installed runtime remains. The [integration record](qualification/reviewed-integration.json)
(exact candidate, proof, migration and catalog pins) records that transition.

Run the [installed test runner](qualification/run_isolated.py) (original read-only
source mount and disposable database) from the repository root:

```sh
python3 candidates/curve-manual-gate2-v2/qualification/run_isolated.py all
python3 candidates/curve-manual-gate2-v2/qualification/run_isolated.py regression
pnpm exec turbo run check:types test --filter=web
node packages/services/check-manual-gate2-contracts.mjs
```

The complete web typecheck includes the existing test sources. Its no-emit project
uses `composite: false` because those tests import cross-package implementation
sources; strict checking and coverage are unchanged. ES2022 browser compatibility
is retained when sorting newly allocated arrays. Panel test errors come from the
same public service package as the rendered app, so uncertain-command behavior is
verified with the actual class identity.

Database phases run sequentially. Tests restore teardown-only truncate guards
around Django fixture cleanup, then independently verify the physical catalog.
Test bodies never turn guards off or monkeypatch the trusted qualification loader.
Historical migration tests temporarily reverse empty successors, check the exact
old catalog/refusal, and restore the full installed leaf before current qualification.
