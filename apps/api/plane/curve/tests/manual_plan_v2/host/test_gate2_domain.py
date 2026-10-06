"""Pure transition evidence. No database exclusivity, ORM authority or IO claims."""

# ruff: noqa: E402
from dataclasses import replace
import sys
import os
import unittest
from unittest.mock import patch
import uuid

import bootstrap

bootstrap.install()
sys.path.insert(0, str(bootstrap.RUNTIME_ROOT.parents[1]))
# The installed pure kernel needs no Celery bootstrap. Use the same explicit
# no-Celery import profile as the bounded validator worker; host settings stay local.
with patch.dict(os.environ, {"DJANGO_SETTINGS_MODULE": "plane.settings.curve_worker"}):
    from plane.curve.manual_gate2_v2 import domain as g
from manual_plan_v2.validation import ROOT, canonical_json, digest, metadata_digest, validate_definition
from test_draft_core import fixture


def subject(other=False):
    identity = fixture("input-identity.valid")
    revision = fixture("revision.valid")
    facts = fixture("immutable-semantic-facts")
    raw = (ROOT / "fixtures" / "definition.valid.json").read_bytes()
    if other:
        definition = fixture("definition.valid")
        new_id = str(uuid.uuid4())
        for data in (identity, revision, facts, definition):
            data["initiative_id"] = new_id
        revision["id"], revision["draft_id"] = str(uuid.uuid4()), str(uuid.uuid4())
        raw = canonical_json(definition)
        identity["definition_ref"] = dict(identity["definition_ref"], digest=digest(raw), size_bytes=len(raw))
        identity["digest"] = metadata_digest(identity)
        revision["definition_ref"] = identity["definition_ref"]
        revision["digest"] = metadata_digest(revision)
    receipt = validate_definition(raw, identity, facts)
    return g.prepare_subject(
        revision=revision,
        identity=identity,
        receipt=receipt,
        definition=raw,
        facts=facts,
        controlling_prd_decision_id="30000000-0000-4000-8000-000000000071",
    )


def authority(value):
    data = value.data
    identity = data["input_identity"]
    gate = next(x for x in identity["gate_assignments"] if x["gate_type"] == "PLAN_APPROVAL")
    return g.CurrentAuthority(
        gate["approver_user_id"],
        data["workspace_id"],
        data["initiative_id"],
        gate["approver_user_id"],
        value.digest,
        tuple(sorted({*identity["human_owner_ids"], *(x["approver_user_id"] for x in identity["gate_assignments"])})),
        value.tasks,
        "sha256:" + "c" * 64,
    )


class Gate2Transitions(unittest.TestCase):
    def setUp(self):
        self.subject = subject()
        self.authority = authority(self.subject)
        self.rationale = "sha256:" + "d" * 64

    def transition(self, ledger=None, **kwargs):
        values = dict(
            ledger=ledger or g.Ledger(),
            subject=self.subject,
            authority=self.authority,
            action="APPROVE",
            idempotency_key="approval",
            rationale_digest=self.rationale,
        )
        values.update(kwargs)
        return g.transition(**values)

    def test_subject_detaches_and_binds_exact_identity_scope_and_receipt(self):
        value = self.subject.data
        value["input_identity"]["human_owner_ids"] = []
        self.assertNotEqual(value, self.subject.data)
        self.assertEqual(len(self.subject.tasks), 2)
        self.assertIn("semantic_facts_digest", self.subject.data)
        self.assertIn("controlling_prd_decision_id", self.subject.data)
        self.assertNotEqual(self.subject.digest, subject(True).digest)

    def test_all_tasks_acquired_and_history_retained_without_execution_field(self):
        original = g.Ledger()
        ledger, decision, replay = self.transition(original)
        self.assertFalse(replay)
        self.assertEqual(len(ledger.claims), 2)
        self.assertEqual(len(ledger.history), 2)
        self.assertEqual(len(ledger.decisions), 1)
        self.assertEqual(original, g.Ledger())
        self.assertTrue(all(c.state == "ACTIVE" and c.generation == 1 for c in decision.claims))
        self.assertNotIn("execution", repr(decision).lower())

    def test_native_member_creator_bot_or_wrong_assignment_never_grants_approval(self):
        for auth in (
            replace(self.authority, actor_id=self.subject.data["input_identity"]["human_owner_ids"][0]),
            replace(self.authority, current_technical_approver_id=str(uuid.uuid4())),
            replace(self.authority, human=False),
            replace(self.authority, workspace_id=str(uuid.uuid4())),
            replace(self.authority, initiative_id=str(uuid.uuid4())),
        ):
            with self.subTest(auth=auth), self.assertRaises(g.Gate2Denied):
                self.transition(authority=auth)

    def test_changed_subject_and_lost_material_or_task_access_deny(self):
        for auth in (
            replace(self.authority, current_subject_digest="sha256:" + "f" * 64),
            replace(self.authority, material_readers=()),
            replace(self.authority, accessible_tasks=self.subject.tasks[:1]),
            replace(self.authority, lifecycle="PAUSED"),
        ):
            with self.subTest(auth=auth), self.assertRaises(g.Gate2Denied):
                self.transition(authority=auth)

    def test_second_initiative_overlap_has_no_partial_delta_or_disclosure(self):
        ledger, _, _ = self.transition()
        other = subject(True)
        with self.assertRaises(g.Gate2Denied) as error:
            self.transition(ledger, subject=other, authority=authority(other))
        self.assertEqual(len(ledger.claims), 2)
        self.assertEqual(len(ledger.decisions), 1)
        self.assertNotIn(self.subject.data["initiative_id"], str(error.exception))

    def test_replay_returns_original_without_a_second_history_effect(self):
        ledger, decision, _ = self.transition()
        again, replayed, replay = self.transition(ledger)
        self.assertTrue(replay)
        self.assertIs(again, ledger)
        self.assertEqual(replayed, decision)
        with self.assertRaises(g.Gate2Denied):
            self.transition(ledger, rationale_digest="sha256:" + "e" * 64)
        with self.assertRaises(g.Gate2Denied):
            self.transition(ledger, authority=replace(self.authority, accessible_tasks=()))

    def test_request_changes_never_reserves_and_requires_fresh_subject(self):
        ledger, decision, _ = self.transition(action="REQUEST_CHANGES")
        self.assertEqual(decision.claims, ())
        self.assertEqual(ledger.claims, ())
        with self.assertRaises(g.Gate2Denied):
            self.transition(ledger, idempotency_key="new-approval")

    def test_pause_cancel_and_access_loss_retain_same_identity_and_generation(self):
        for cause in ("PAUSED", "CANCELLED", "ACCESS_LOST"):
            ledger, _, _ = self.transition()
            held = g.hold(
                ledger=ledger,
                initiative_id=self.subject.data["initiative_id"],
                cause=cause,
                cause_digest=self.rationale,
            )
            self.assertTrue(all(c.state == "HELD" and c.generation == 1 for c in held.claims))
            self.assertEqual(len(held.history), 4)
            repeated = g.hold(
                ledger=held, initiative_id=self.subject.data["initiative_id"], cause=cause, cause_digest=self.rationale
            )
            self.assertEqual(repeated, held)
            other = subject(True)
            with self.assertRaises(g.Gate2Denied):
                self.transition(held, subject=other, authority=authority(other))

    def reconciliation(self, ledger, **kwargs):
        values = dict(
            ledger=ledger,
            subject=self.subject,
            authority=self.authority,
            exact_claims=tuple((c.task, c.generation) for c in ledger.claims),
            unresolved_work=(),
            rationale_digest=self.rationale,
        )
        values.update(kwargs)
        return g.reconcile(**values)

    def test_release_requires_fresh_exact_reconciliation_and_current_approver(self):
        ledger, _, _ = self.transition()
        for changes in (
            dict(unresolved_work=self.subject.tasks),
            dict(exact_claims=((self.subject.tasks[0], 2),)),
            dict(authority=replace(self.authority, accessible_tasks=())),
        ):
            with self.subTest(changes=changes), self.assertRaises(g.Gate2Denied):
                self.reconciliation(ledger, **changes)
        receipt = self.reconciliation(ledger)
        with self.assertRaises(g.Gate2Denied):
            self.transition(
                ledger,
                action="RELEASE",
                idempotency_key="release",
                reconciliation=receipt,
                authority=replace(self.authority, native_fence_digest="sha256:" + "a" * 64),
            )

    def test_partial_release_and_reacquisition_keep_history_and_increment_generation(self):
        ledger, original, _ = self.transition()
        receipt = self.reconciliation(ledger, exact_claims=((self.subject.tasks[0], 1),))
        released, decision, replay = self.transition(
            ledger, action="RELEASE", idempotency_key="release", reconciliation=receipt
        )
        self.assertFalse(replay)
        self.assertEqual([c.state for c in released.claims], ["RELEASED", "ACTIVE"])
        replayed, old, _ = self.transition(released)
        self.assertIs(replayed, released)
        self.assertEqual(old, original)
        # A retry never restores the first task's old controlling claim.
        self.assertEqual(replayed.claims[0].state, "RELEASED")
        self.assertEqual(len(released.history), 3)
        self.assertEqual(len(decision.claims), 1)

    def test_current_reassigned_technical_approver_can_reconcile_release_with_access(self):
        ledger, _, _ = self.transition()
        new_actor = str(uuid.uuid4())
        current = replace(
            self.authority,
            actor_id=new_actor,
            current_technical_approver_id=new_actor,
            material_readers=(*self.authority.material_readers, new_actor),
        )
        receipt = self.reconciliation(ledger, authority=current)
        released, _, _ = self.transition(
            ledger, action="RELEASE", idempotency_key="release", reconciliation=receipt, authority=current
        )
        self.assertTrue(all(c.state == "RELEASED" for c in released.claims))
        other = subject(True)
        next_ledger, _, _ = self.transition(released, subject=other, authority=authority(other))
        self.assertTrue(all(c.generation == 2 for c in next_ledger.claims))
        self.assertEqual(len(next_ledger.history), 6)

    def test_duplicate_stable_task_or_unsafe_generation_rejected(self):
        ledger, _, _ = self.transition()
        with self.assertRaises(g.Gate2Denied):
            g.Ledger((ledger.claims[0], ledger.claims[0]))
        with self.assertRaises(g.Gate2Denied):
            g.Ledger((replace(ledger.claims[0], generation=True),))
