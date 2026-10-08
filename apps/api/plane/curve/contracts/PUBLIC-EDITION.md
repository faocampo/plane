# Public contract consumer edition

This vendored bundle uses the sanitized Curve public contract edition from
[Curve revision 00fb40d](https://github.com/faocampo/curve/tree/00fb40dad746a4e4ec2aefe9bc0f629e1118d716)
(public schema identifiers, fictional fixtures and publication boundaries).
Plane-specific Initiative 1.1 extensions retain their existing behavior with
reserved-domain schema identifiers. Data shapes and policy decisions remain
covered by repository tests.

The [consumer manifest](public-consumer-edition-v1.json) (exact local contract
inventory and SHA-256 pins) is bound by the [integrity checker](check-integrity.mjs)
(complete file inventory, byte checks and unchanged local capability constraints).
Check integrity with `node apps/api/plane/curve/contracts/check-integrity.mjs`.
Adding, removing or changing a contract requires a reviewed manifest and pin
update; the checker never regenerates pins at validation time.

Historical context and runtime-evidence records are replaced with explicit
public-reference notices. This publication supplies no human approval,
execution receipt, live-runtime proof or deployment authority. Private approval
evidence must bind its exact approved subject; previous approvals cannot be
transferred to sanitized bytes or fictional people.

This source cleanup changes newly emitted schema and Problem Details identifiers
to a reserved example domain. It does not rewrite persisted events, audit data
or remote repository history. Before activating this edition against an existing
deployment, verify queued-event/replay compatibility and bind the complete
consumer bundle under its private deployment procedure. Real provider access,
protected snapshot storage and new lifecycle capabilities remain gated.

The source branch and Git history retain the original records for recovery.
History rewriting, hosting-provider removal, deployment and data migration are
separate operations. Reverting this source change restores the previous code and
contract bundle together; it does not reverse a database mutation because this
cleanup performs none.
