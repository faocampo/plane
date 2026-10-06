"""Current observations and local counters; native ORM locking remains a DB gate."""

# ruff: noqa: E402
from copy import deepcopy
from types import SimpleNamespace
import unittest
import uuid

import bootstrap

bootstrap.install()
from manual_plan_v2 import contracts, policy, synthetic
from test_draft_core import fixture


class CurrentAuthorityTests(unittest.TestCase):
    def setUp(self):
        identity = fixture("input-identity.valid")
        self.ids = sorted(
            {*identity["human_owner_ids"], *(item["approver_user_id"] for item in identity["gate_assignments"])}
        )
        memberships = tuple((uuid.uuid4(), uuid.UUID(user), 15, True) for user in self.ids)
        self.contexts = [
            SimpleNamespace(
                actor_id=uuid.UUID(user),
                workspace=SimpleNamespace(id=uuid.UUID(identity["workspace_id"])),
                initiative=SimpleNamespace(id=uuid.UUID(identity["initiative_id"]), version=9),
                fence=(uuid.uuid4(), 1, "ACTIVE", "STANDARD", (), memberships, ((user, "source-fence"),)),
            )
            for user in self.ids
        ]
        self.observations = policy.native_authority_observations(self.contexts)
        self.ledger = synthetic.advance_native_authority(None, self.observations)
        self.captured = SimpleNamespace(
            identity=identity,
            native_authority=self.ledger,
            catalog_generation=3,
            grants=tuple(
                dict(
                    principal_id=user, actions=sorted(synthetic.ACTIONS), acl_generation=1, classification_generation=1
                )
                for user in self.ids
            ),
        )

    def project(self, action="SAVE"):
        return policy.current_authority_projection(self.contexts[0], self.captured, self.contexts, action)

    def test_receipt_binds_current_all_principals_and_original_identity(self):
        receipt = self.project()
        self.assertEqual(len(receipt["principal_checks"]), 4)
        self.assertEqual(receipt["input_identity_digest"], self.captured.identity["digest"])
        self.assertEqual(receipt["source_access_generation"], 1)
        self.assertEqual(receipt["protected_catalog_generation"], 3)
        contracts.validate("manual-plan-current-authority-v2", receipt)
        self.assertNotIn("current_authority", self.captured.identity)

    def test_generation_counter_only_advances_for_changed_observation(self):
        self.assertEqual(synthetic.advance_native_authority(self.ledger, self.observations), self.ledger)
        changed = deepcopy(self.observations)
        changed["memberships"][self.ids[0]] = "sha256:" + "1" * 64
        changed["sources"][self.ids[0]] = "sha256:" + "2" * 64
        next_ledger = synthetic.advance_native_authority(self.ledger, changed)
        self.assertEqual(next_ledger["memberships"][self.ids[0]]["generation"], 2)
        self.assertEqual(next_ledger["memberships"][self.ids[1]]["generation"], 1)
        self.assertEqual(next_ledger["source"]["generation"], 2)

    def test_changed_source_and_membership_deny_until_producer_refresh(self):
        context = self.contexts[0]
        context.fence = (*context.fence[:-1], (("changed-source",),))
        with self.assertRaises(contracts.ManualPlanError):
            self.project()
        observations = policy.native_authority_observations(self.contexts)
        self.captured.native_authority = synthetic.advance_native_authority(self.ledger, observations)
        self.assertEqual(self.project()["source_access_generation"], 2)

    def test_individual_object_generation_is_in_final_fence_even_below_maximum(self):
        self.captured.grants += (dict(self.captured.grants[0], object_id=str(uuid.uuid4()), acl_generation=9),)
        before = self.project()
        self.captured.grants[0]["acl_generation"] = 2
        after = self.project()
        self.assertEqual(
            before["principal_checks"][0]["acl_generation"], after["principal_checks"][0]["acl_generation"]
        )
        self.assertNotEqual(before["fence_digest"], after["fence_digest"])

    def test_missing_principal_denied_action_and_counter_overflow_fail(self):
        del self.captured.native_authority["memberships"][self.ids[0]]
        with self.assertRaises(contracts.ManualPlanError):
            self.project()
        self.captured.native_authority = synthetic.advance_native_authority(None, self.observations)
        self.captured.grants[0]["actions"] = []
        with self.assertRaises(contracts.ManualPlanError):
            self.project()
        ledger = deepcopy(self.ledger)
        ledger["source"]["generation"] = 9007199254740991
        changed = deepcopy(self.observations)
        changed["sources"][self.ids[0]] = "sha256:" + "f" * 64
        with self.assertRaises(contracts.ManualPlanError):
            synthetic.advance_native_authority(ledger, changed)

    def test_subset_observations_preserve_absent_principal_generations(self):
        changed = deepcopy(self.observations)
        changed["memberships"][self.ids[0]] = "sha256:" + "a" * 64
        ledger = synthetic.advance_native_authority(self.ledger, changed)
        subset = {key: {self.ids[1]: value[self.ids[1]]} for key, value in self.observations.items()}
        self.assertEqual(synthetic.advance_native_authority(ledger, subset), ledger)
        self.assertEqual(ledger["memberships"][self.ids[0]]["generation"], 2)
        again = synthetic.advance_native_authority(ledger, self.observations)
        self.assertEqual(again["memberships"][self.ids[0]]["generation"], 3)

    def test_additional_catalog_principal_does_not_block_current_actor_subset(self):
        extra = str(uuid.uuid4())
        additional = {"memberships": {extra: "sha256:" + "b" * 64}, "sources": {extra: "sha256:" + "c" * 64}}
        self.captured.native_authority = synthetic.advance_native_authority(self.ledger, additional)
        receipt = self.project()
        self.assertEqual(len(receipt["principal_checks"]), len(self.contexts))
        self.assertEqual(receipt["source_access_generation"], 2)
