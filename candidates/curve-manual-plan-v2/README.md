# Manual draft v2: integrated local source

Current Gate2 integration supersedes the historical pending items below. See the
[Gate2 implementation](../curve-manual-gate2-v2/README.md) (separate pinned writer,
exclusive claims and default-off UI) and [current evidence](../curve-manual-gate2-v2/VERIFICATION.md)
(prospective and installed-source verification). The pure kernel now lives in the
single installed runtime; original draft/scope proof bytes remain unchanged.

Status: qualified source promoted into the restored Plane application, 2026-10-06.
The feature remains explicitly disabled by default. No workspace, provider,
shared deployment, plan approval or automatic execution is activated.

The single implementation is now [manual_plan_v2](../../apps/api/plane/curve/manual_plan_v2/)
(eleven modules and unchanged canonical contract JSON). It retains immutable draft
revisions, exact protected input identities, native/object authority, bounded Linux
validation, atomic policy/audit/event/outbox/idempotency, original replay with a
current ETag, protected current/history reads and separate metadata-only status.
Four registered session/CSRF routes remain unavailable when the feature is off.

The [migration](../../apps/api/plane/curve/migrations/0024_manual_draft_reconstruction.py)
(two models, closed SQL graph guards and a separate seal) and
[manual successor proof](../../apps/api/plane/curve/manual_plan_draft_reconstruction_qualification_v2.json)
(exact additive source/model/catalog qualification) are the exact bytes exercised
in the disposable application. Both earlier proof files and all 23 historical
migrations remain byte-identical. No second runnable draft implementation remains
in this candidate directory.

The [verification record](VERIFICATION.md) (executed evidence and limits),
[adapter definitions](ADAPTERS.md) (native observations and protected local files),
[promotion checklist](PROMOTION.md) (remaining scope-reader, UI, Gate 2 and pilot
work), and [qualification history](qualification/README.md) (prospective proposal
and current reproduction) describe the boundary. The pure [Gate 2 kernel](../../apps/api/plane/curve/manual_gate2_v2/domain.py)
(uninstalled reservation transitions) remains separate and has no ORM or writer.

## Verification commands

Run from the Plane repository root using the existing isolated unit environment:

```sh
.curve-local/unit-venv/bin/python -m unittest discover \
  -s apps/api/plane/curve/tests/manual_plan_v2/host -v
python3 candidates/curve-manual-plan-v2/qualification/run_isolated.py all
python3 candidates/curve-manual-plan-v2/qualification/run_isolated.py regression
```

The [runtime tests](../../apps/api/plane/curve/tests/manual_plan_v2/)
(actual native authority, migration, graph/API, SQL and Linux tests) use the
original read-only source bind and disposable PostgreSQL profile. Run database
phases sequentially. Host doubles run only with the separate unittest command;
they are deliberately outside pytest collection and cannot qualify database behavior.
Node.js and the sibling Curve checkout support exact JavaScript/contract parity.
The [unit requirements](requirements-unit.txt) (local dependency pins) reproduce
that host environment.

## Remaining operational limits

The local protected catalog is bounded at 1 MiB, 128 Initiatives, 128 plans,
512 objects and 16 MiB captured material. Native membership never substitutes for
per-object grants. Every selected PRD body and excerpt is retained conservatively.
Only a restricted plain-text subset of the original normalized PRD is admitted.
The validator requires Linux; the Mac path fails closed. Its two file-lock slots
cover API processes in one container, not distributed container concurrency.
Abrupt API-parent death and aggregate resource pressure still need operational
acceptance. Protected definition preparation, a mounted authenticated browser
journey, Gate 2 persistence and complete pilot operations remain work.
