# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: E402 -- Configure Django before candidate imports.
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

import bootstrap

bootstrap.install()

from manual_plan_v2 import contracts, synthetic, validator_worker
from manual_plan_v2.validation import ROOT, canonical_json, digest, metadata_digest, validate_definition


def fixture(name):
    return json.loads((ROOT / "fixtures" / (name + ".json")).read_text())


def synthetic_inputs():
    definition, identity, facts = (
        fixture(name) for name in ("definition.valid", "input-identity.valid", "immutable-semantic-facts")
    )
    context = b"Synthetic local context."
    object_ref = identity["protected_inputs"][0]["object_ref"]
    object_ref.update(digest=digest(context), size_bytes=len(context))
    definition["repositories"][0]["context_input_ref"] = deepcopy(object_ref)
    identity["repository_inputs"] = deepcopy(definition["repositories"])
    facts["repositories"] = deepcopy(definition["repositories"])
    facts["protected_object_refs"] = [deepcopy(object_ref)]
    raw = canonical_json(definition)
    identity["definition_ref"].update(digest=digest(raw), size_bytes=len(raw))
    identity["digest"] = metadata_digest(identity)
    return raw, identity, facts, context


class SyntheticFixtures:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name).resolve()
        self.root = self.parent / "store"
        self.root.mkdir(mode=0o700)
        self.raw, self.identity, self.facts, context = synthetic_inputs()
        self.principals = sorted(
            {*self.identity["human_owner_ids"], *(a["approver_user_id"] for a in self.identity["gate_assignments"])}
        )
        self.entry = dict(
            workspace_id=self.identity["workspace_id"],
            technical_contributor_ids=self.identity["human_owner_ids"],
            native_authority=synthetic.advance_native_authority(
                None,
                dict(
                    memberships={principal: "sha256:" + "0" * 64 for principal in self.principals},
                    sources={principal: "sha256:" + "0" * 64 for principal in self.principals},
                ),
            ),
            grants=[
                dict(
                    principal_id=item, actions=sorted(synthetic.ACTIONS), acl_generation=1, classification_generation=1
                )
                for item in self.principals
            ],
        )
        self.catalog = dict(
            schema_version="curve.synthetic-manual-plan-catalog/v2-candidate",
            generation=1,
            initiatives={self.identity["initiative_id"]: self.entry},
            plans={
                self.identity["definition_ref"]["object_id"]: dict(
                    identity=self.identity,
                    facts=self.facts,
                    semantic_sources=dict(prd={}, workflow={}, quality={}, repositories=[]),
                )
            },
            objects={},
        )
        for original in [
            dict(
                object_ref=self.identity["definition_ref"],
                material_version_id=self.identity["definition_ref"]["object_id"],
                access_envelope_id=self.identity["definition_ref"]["object_id"],
                classification="INTERNAL",
            ),
            *self.identity["protected_inputs"],
        ]:
            self.catalog["objects"][original["object_ref"]["object_id"]] = dict(
                workspace_id=self.identity["workspace_id"],
                object_ref=deepcopy(original["object_ref"]),
                material_version_id=original["material_version_id"],
                access_envelope_id=original["access_envelope_id"],
                classification=original["classification"],
                grants=deepcopy(self.entry["grants"]),
            )
        self.write("catalog.json", canonical_json(self.catalog))
        self.write(self.identity["definition_ref"]["object_id"], self.raw)
        self.write(self.identity["protected_inputs"][0]["object_ref"]["object_id"], context)

    def write(self, name, raw):
        target = self.root / name
        target.write_bytes(raw)
        target.chmod(0o600)

    def capture(self, resolver, action="SAVE"):
        return resolver.capture(
            workspace_id=self.identity["workspace_id"],
            initiative_id=self.identity["initiative_id"],
            definition_ref=self.identity["definition_ref"],
            principals=self.principals,
            action=action,
        )


class SyntheticResolverTests(SyntheticFixtures, unittest.TestCase):
    def test_exact_local_catalog_and_bytes_validate(self):
        with synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
            captured = self.capture(resolver)
            receipt = validate_definition(captured.definition, captured.identity, captured.facts)
            self.assertEqual(receipt["input_identity_digest"], self.identity["digest"])
            self.assertEqual(captured.catalog_generation, 1)
            self.assertEqual(len(captured.grants), 12)

    def test_object_acl_deny_overrides_initiative_allow(self):
        object_id = self.identity["protected_inputs"][0]["object_ref"]["object_id"]
        self.catalog["objects"][object_id]["grants"][-1]["actions"] = ["READ_STATUS"]
        self.write("catalog.json", canonical_json(self.catalog))
        with synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
            with self.assertRaises(contracts.ManualPlanError):
                self.capture(resolver)

    def test_protected_material_identity_cannot_be_substituted(self):
        object_id = self.identity["protected_inputs"][0]["object_ref"]["object_id"]
        entry = self.catalog["objects"][object_id]
        changes = dict(
            material_version_id="00000000-0000-0000-0000-000000000099",
            access_envelope_id="00000000-0000-0000-0000-000000000099",
            classification="RESTRICTED",
            workspace_id="00000000-0000-0000-0000-000000000099",
        )
        for key, value in changes.items():
            previous = entry[key]
            with self.subTest(key=key):
                entry[key] = value
                self.write("catalog.json", canonical_json(self.catalog))
                with synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
                    with self.assertRaises(contracts.ManualPlanError):
                        self.capture(resolver)
                entry[key] = previous

    def test_malformed_catalog_object_is_denied_without_reading_body(self):
        object_id = self.identity["definition_ref"]["object_id"]
        for key, value in (("digest", "sha256:bad"), ("media_type", []), ("size_bytes", True)):
            entry = self.catalog["objects"][object_id]["object_ref"]
            original = entry[key]
            with self.subTest(key=key):
                entry[key] = value
                self.write("catalog.json", canonical_json(self.catalog))
                with synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
                    with self.assertRaises(contracts.ManualPlanError):
                        resolver._catalog()
                entry[key] = original

    def test_denied_action_cannot_be_overridden_by_owner_or_contributor(self):
        self.entry["grants"][-1]["actions"] = ["READ_STATUS"]
        self.write("catalog.json", canonical_json(self.catalog))
        with synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
            with self.assertRaises(contracts.ManualPlanError):
                self.capture(resolver)

    def test_changed_catalog_or_definition_fails_final_fence(self):
        for name in ("catalog.json", self.identity["definition_ref"]["object_id"]):
            with self.subTest(name=name):
                before = (self.root / name).read_bytes()
                with synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
                    captured = self.capture(resolver)
                    self.write(name, before + b" ")
                    with self.assertRaises(contracts.ManualPlanError):
                        resolver.recheck(captured.file_fence)
                self.write(name, before)

    def test_replaced_root_does_not_retain_authority(self):
        with synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
            captured = self.capture(resolver)
            self.root.rename(self.parent / "old-store")
            self.root.mkdir(mode=0o700)
            with self.assertRaises(contracts.ManualPlanError):
                resolver.recheck(captured.file_fence)

    def test_missing_changed_or_symlinked_original_content_is_denied(self):
        target = self.root / self.identity["protected_inputs"][0]["object_ref"]["object_id"]
        original = target.read_bytes()
        target.write_bytes(b"wrong")
        with synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
            with self.assertRaises(contracts.ManualPlanError):
                self.capture(resolver)
        target.unlink()
        elsewhere = self.parent / "elsewhere"
        elsewhere.write_bytes(original)
        target.symlink_to(elsewhere)
        with synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
            with self.assertRaises(OSError):
                self.capture(resolver)

    def test_nonprivate_root_file_and_hardlink_are_denied(self):
        self.root.chmod(0o755)
        with self.assertRaises(contracts.ManualPlanError):
            synthetic.SyntheticManualPlanResolverV2(str(self.root))
        self.root.chmod(0o700)
        target = self.root / self.identity["definition_ref"]["object_id"]
        target.chmod(0o644)
        with synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
            with self.assertRaises(contracts.ManualPlanError):
                self.capture(resolver)
        target.chmod(0o600)
        os.link(target, self.parent / "hardlink")
        with synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
            with self.assertRaises(contracts.ManualPlanError):
                self.capture(resolver)

    def test_closed_catalog_rejects_unknown_keys_and_duplicated_principals(self):
        for change in (
            lambda: self.catalog.update(callback="untrusted"),
            lambda: self.entry["grants"].append(deepcopy(self.entry["grants"][0])),
        ):
            with self.subTest(change=change):
                before = deepcopy(self.catalog)
                change()
                self.write("catalog.json", canonical_json(self.catalog))
                with synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
                    with self.assertRaises(contracts.ManualPlanError):
                        self.capture(resolver)
                self.catalog = before
                self.entry = self.catalog["initiatives"][self.identity["initiative_id"]]

    def test_subclasses_and_nonopaque_object_paths_are_rejected(self):
        class Override(synthetic.SyntheticManualPlanResolverV2):
            pass

        with self.assertRaises(contracts.ManualPlanError):
            Override(str(self.root))
        with synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
            ref = dict(self.identity["definition_ref"], object_id="../catalog.json")
            with self.assertRaises((contracts.ManualPlanError, ValueError)):
                resolver.capture(
                    workspace_id=self.identity["workspace_id"],
                    initiative_id=self.identity["initiative_id"],
                    definition_ref=ref,
                    principals=self.principals,
                    action="SAVE",
                )

    def test_status_acl_does_not_read_original_object_bodies(self):
        (self.root / self.identity["definition_ref"]["object_id"]).unlink()
        with synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
            catalog, _, grants, fence = resolver.authorize(
                workspace_id=self.identity["workspace_id"],
                initiative_id=self.identity["initiative_id"],
                principals=self.principals,
                action="READ_STATUS",
            )
            self.assertEqual(catalog["generation"], 1)
            self.assertEqual(len(grants), 4)
            self.assertEqual(fence[0], "catalog.json")

    def test_host_worker_fails_closed_instead_of_weakening_limits(self):
        with (
            patch.object(validator_worker.sys, "platform", "darwin"),
            patch.object(validator_worker.subprocess, "Popen") as spawn,
        ):
            with self.assertRaises(contracts.ManualPlanError) as error:
                validator_worker.validate_in_worker(None)
            self.assertEqual(error.exception.code, "MANUAL_PLAN_DRAFT_VALIDATION_UNAVAILABLE")
            spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class CatalogProducerTests(SyntheticFixtures, unittest.TestCase):
    def test_catalog_cas_preserves_original_data_and_requires_generation_advance(self):
        before = digest(canonical_json(self.catalog))
        replacement = deepcopy(self.catalog)
        replacement["generation"] += 1
        with synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
            written = resolver.publish_catalog(expected_digest=before, replacement=replacement)
            self.assertEqual(written, digest(canonical_json(replacement)))
            self.assertEqual(self.capture(resolver).catalog_generation, 2)
            with self.assertRaises(contracts.ManualPlanError) as error:
                resolver.publish_catalog(expected_digest=before, replacement=replacement)
            self.assertEqual(error.exception.code, "MANUAL_PLAN_DRAFT_COMMAND_CONFLICT")

    def test_catalog_cannot_rewrite_retained_plan_or_material(self):
        for section in ("plans", "objects"):
            replacement = deepcopy(self.catalog)
            replacement["generation"] += 1
            del replacement[section][self.identity["definition_ref"]["object_id"]]
            with self.subTest(section=section), synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
                with self.assertRaises(contracts.ManualPlanError):
                    resolver.publish_catalog(
                        expected_digest=digest(canonical_json(self.catalog)), replacement=replacement
                    )

    def test_revoke_requires_new_acl_generation_and_immediately_denies_capture(self):
        replacement = deepcopy(self.catalog)
        replacement["generation"] += 1
        entry = replacement["objects"][self.identity["protected_inputs"][0]["object_ref"]["object_id"]]
        entry["grants"][0]["actions"] = []
        with synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
            with self.assertRaises(contracts.ManualPlanError):
                resolver.publish_catalog(expected_digest=digest(canonical_json(self.catalog)), replacement=replacement)
            entry["grants"][0]["acl_generation"] += 1
            resolver.publish_catalog(expected_digest=digest(canonical_json(self.catalog)), replacement=replacement)
            with self.assertRaises(contracts.ManualPlanError):
                self.capture(resolver)

    def test_catalog_cannot_move_retained_initiative_to_another_workspace(self):
        replacement = deepcopy(self.catalog)
        replacement["generation"] += 1
        replacement["initiatives"][self.identity["initiative_id"]]["workspace_id"] = str(uuid.uuid4())
        with synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
            with self.assertRaises(contracts.ManualPlanError):
                resolver.publish_catalog(expected_digest=digest(canonical_json(self.catalog)), replacement=replacement)

    def test_removed_grant_cannot_reset_its_counter_and_busy_publisher_fails_promptly(self):
        import fcntl

        replacement = deepcopy(self.catalog)
        replacement["generation"] += 1
        replacement["initiatives"][self.identity["initiative_id"]]["grants"].pop()
        with synthetic.SyntheticManualPlanResolverV2(str(self.root)) as resolver:
            with self.assertRaises(contracts.ManualPlanError):
                resolver.publish_catalog(expected_digest=digest(canonical_json(self.catalog)), replacement=replacement)
            fd = os.open(self.root / "catalog.lock", os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(contracts.ManualPlanError) as error:
                    resolver.publish_catalog(
                        expected_digest=digest(canonical_json(self.catalog)), replacement=replacement
                    )
                self.assertEqual(error.exception.code, "MANUAL_PLAN_DRAFT_COMMAND_CONFLICT")
            finally:
                os.close(fd)
