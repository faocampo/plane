# Gate2 qualification evidence

All evidence is synthetic and local. The final prospective suite passed **23 tests
in 359.34 seconds**: 20 Gate2 tests and three exact historical migration gates.
Installed-source verification follows; no pending result is a pass.

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
- The typed browser-client/component suite passed 44 cases. They include the
  existing draft client, strict response/material validation, explicit review,
  stale/unknown results, same-command retry, authority clearing and prepared
  replacement isolation. These are component/client tests with synthetic transports.
- Targeted TypeScript and Python Ruff checks pass. Full application checks and
  authenticated browser-to-backend pilot acceptance are distinct evidence.

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

The prospective assembly is captured in the pre-promotion local commit.
Run its [assembler](qualification/assemble_prospective.py) (closed source overlay)
using a Python environment with Ruff, then the [test runner](qualification/run_isolated.py)
(isolated disposable database). The assembler asserts the exact old source hashes
and reviewed unpinned migration digest. Never feed it a hash observed from a changed
runtime as a replacement approval.

Database phases run sequentially. Tests restore teardown-only truncate guards
around Django fixture cleanup, then independently verify the physical catalog.
Test bodies never turn guards off or monkeypatch the trusted qualification loader.
Historical migration tests temporarily reverse empty successors, check the exact
old catalog/refusal, and restore the full installed leaf before current qualification.
