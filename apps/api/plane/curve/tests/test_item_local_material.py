# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from plane.curve.item_creation_input import normalize_item_creation
from plane.curve.tests.test_item_creation_input import fixture
from plane.curve.item_local_material import (
    DESTINATION,
    EDITION,
    ItemMaterialUnavailable,
    LocalItemMaterialResolver,
)
from plane.curve.item_creation_material import scope_requirements


WORKSPACE, PRODUCT, ACTOR, MEMBER, OBJECT, ENVELOPE, OTHER, ROADMAP = [
    f"00000000-0000-0000-0000-{value:012d}" for value in range(1, 9)
]


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class ItemLocalMaterialTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.body = b'{"type":"doc","content":[]}'
        self.reference = {
            "object_id": OBJECT,
            "digest": digest(self.body),
            "size_bytes": len(self.body),
            "media_type": "application/json",
            "editor_schema_version": "synthetic-v1",
        }
        self.catalog = {
            "schema_version": EDITION,
            "generation": 1,
            "objects": {
                OBJECT: {
                    "workspace_id": WORKSPACE,
                    "product_id": PRODUCT,
                    "roadmap_id": ROADMAP,
                    "reference": self.reference,
                    "access_envelope_id": ENVELOPE,
                    "classification": "INTERNAL",
                    "destination": DESTINATION,
                    "grants": {
                        ACTOR: {
                            "membership_id": MEMBER,
                            "membership_generation": 1,
                            "acl_generation": 1,
                            "can_read": True,
                        }
                    },
                }
            },
        }
        self.write("catalog.lock", b"")
        self.write(OBJECT, self.body)
        self.write("catalog.json", canonical(self.catalog))

    def write(self, name, body):
        (self.root / name).write_bytes(body)
        os.chmod(self.root / name, 0o600)

    def requirements(self, reference=None):
        ref = self.reference if reference is None else reference
        payload = fixture()
        payload["scope_body"] = ref
        return scope_requirements(normalize_item_creation(payload, 1))

    def capture(self, resolver, **changes):
        args = dict(
            workspace_id=WORKSPACE,
            product_id=PRODUCT,
            roadmap_id=ROADMAP,
            actor_id=ACTOR,
            membership_id=MEMBER,
            membership_generation=1,
            requirements=self.requirements(),
        )
        return resolver.capture(**{**args, **changes})

    def replacement(self, **grant_changes):
        value = deepcopy(self.catalog)
        value["generation"] = 2
        value["objects"][OBJECT]["grants"][ACTOR].update(acl_generation=2, **grant_changes)
        return value

    def test_scoped_capture_has_immutable_evidence_without_document_bytes(self):
        with LocalItemMaterialResolver(str(self.root)) as resolver, resolver.lease():
            captured = self.capture(resolver)
            resolver.revalidate(captured)
            self.assertEqual(captured.workspace_id, WORKSPACE)
            self.assertEqual(captured.observations[0]["access_envelope_id"], ENVELOPE)
            self.assertEqual(captured.observations[0]["purposes"], ("ITEM_SCOPE",))
            self.assertNotIn(self.body.decode(), repr(captured))
            with self.assertRaises(TypeError):
                captured.observations[0]["acl_generation"] = 99

    def test_capture_and_revalidation_require_the_same_active_lease(self):
        with LocalItemMaterialResolver(str(self.root)) as resolver:
            with self.assertRaisesRegex(ItemMaterialUnavailable, "LEASE_REQUIRED"):
                self.capture(resolver)
            with resolver.lease():
                captured = self.capture(resolver)
            with self.assertRaisesRegex(ItemMaterialUnavailable, "EXPIRED"):
                resolver.revalidate(captured)
            with resolver.lease(), self.assertRaisesRegex(ItemMaterialUnavailable, "EXPIRED"):
                resolver.revalidate(captured)

    def test_actor_product_workspace_and_membership_are_independent(self):
        for field in ("actor_id", "product_id", "roadmap_id", "workspace_id", "membership_id"):
            with self.subTest(field=field), LocalItemMaterialResolver(str(self.root)) as resolver, resolver.lease():
                with self.assertRaises(ItemMaterialUnavailable):
                    self.capture(resolver, **{field: OTHER})

    def test_restored_membership_needs_a_fresh_explicit_material_grant(self):
        with LocalItemMaterialResolver(str(self.root)) as resolver, resolver.lease():
            with self.assertRaises(ItemMaterialUnavailable):
                self.capture(resolver, membership_generation=2)
        with LocalItemMaterialResolver(str(self.root)) as writer:
            writer.publish_catalog(
                expected_digest=digest(canonical(self.catalog)), replacement=self.replacement(membership_generation=2)
            )
        with LocalItemMaterialResolver(str(self.root)) as resolver, resolver.lease():
            self.capture(resolver, membership_generation=2)
            with self.assertRaises(ItemMaterialUnavailable):
                self.capture(resolver)

    def test_creation_requires_current_material_access(self):
        self.catalog["objects"][OBJECT]["grants"][ACTOR]["can_read"] = False
        self.write("catalog.json", canonical(self.catalog))
        with LocalItemMaterialResolver(str(self.root)) as resolver, resolver.lease():
            with self.assertRaises(ItemMaterialUnavailable):
                self.capture(resolver, requirements=self.requirements())

    def test_shared_lease_serializes_catalog_revocation(self):
        with LocalItemMaterialResolver(str(self.root)) as reader, reader.lease():
            captured = self.capture(reader)
            with LocalItemMaterialResolver(str(self.root)) as writer:
                with self.assertRaisesRegex(ItemMaterialUnavailable, "BUSY"):
                    writer.publish_catalog(
                        expected_digest=digest(canonical(self.catalog)), replacement=self.replacement(can_read=False)
                    )
            reader.revalidate(captured)
        with LocalItemMaterialResolver(str(self.root)) as writer:
            writer.publish_catalog(
                expected_digest=digest(canonical(self.catalog)), replacement=self.replacement(can_read=False)
            )
        with LocalItemMaterialResolver(str(self.root)) as reader, reader.lease():
            with self.assertRaises(ItemMaterialUnavailable):
                self.capture(reader)

    def test_reader_blocks_a_separate_catalog_publisher_process(self):
        script = """
import json, sys
from plane.curve.item_local_material import LocalItemMaterialResolver, ItemMaterialUnavailable
args = json.load(sys.stdin)
try:
    with LocalItemMaterialResolver(args['root']) as writer:
        writer.publish_catalog(expected_digest=args['digest'], replacement=args['replacement'])
except ItemMaterialUnavailable as error:
    print(str(error))
else:
    print('PUBLISHED')
"""
        payload = json.dumps(
            {
                "root": str(self.root),
                "digest": digest(canonical(self.catalog)),
                "replacement": self.replacement(can_read=False),
            }
        )
        with LocalItemMaterialResolver(str(self.root)) as reader, reader.lease():
            captured = self.capture(reader)
            blocked = subprocess.run(
                [sys.executable, "-c", script], input=payload, text=True, capture_output=True, timeout=15, check=True
            )
            self.assertEqual(blocked.stdout.strip(), "ITEM_MATERIAL_BUSY")
            reader.revalidate(captured)
        published = subprocess.run(
            [sys.executable, "-c", script], input=payload, text=True, capture_output=True, timeout=15, check=True
        )
        self.assertEqual(published.stdout.strip(), "PUBLISHED")
        with LocalItemMaterialResolver(str(self.root)) as reader, reader.lease():
            with self.assertRaises(ItemMaterialUnavailable):
                self.capture(reader)

    def test_reference_metadata_must_match_authoritative_object(self):
        for key, value in (
            ("digest", "sha256:" + "b" * 64),
            ("size_bytes", 1),
            ("media_type", "text/plain"),
            ("editor_schema_version", "synthetic-v2"),
        ):
            with self.subTest(key=key), LocalItemMaterialResolver(str(self.root)) as resolver, resolver.lease():
                with self.assertRaises(ItemMaterialUnavailable):
                    self.capture(resolver, requirements=self.requirements({**self.reference, key: value}))

    def test_digest_is_checked_against_actual_bytes(self):
        self.write(OBJECT, b"x" * len(self.body))
        with LocalItemMaterialResolver(str(self.root)) as resolver, resolver.lease():
            with self.assertRaises(ItemMaterialUnavailable):
                self.capture(resolver)

    def test_revalidation_detects_noncooperating_content_change(self):
        with LocalItemMaterialResolver(str(self.root)) as resolver, resolver.lease():
            captured = self.capture(resolver)
            self.write(OBJECT, b"x" * len(self.body))
            with self.assertRaises(ItemMaterialUnavailable):
                resolver.revalidate(captured)

    def test_revalidation_detects_same_size_catalog_rewrite(self):
        with LocalItemMaterialResolver(str(self.root)) as reader, reader.lease():
            captured = self.capture(reader)
            changed = canonical(self.catalog).replace(ACTOR.encode(), OTHER.encode())
            self.assertEqual(len(changed), len(canonical(self.catalog)))
            self.write("catalog.json", changed)
            with self.assertRaises(ItemMaterialUnavailable):
                reader.revalidate(captured)

    def test_membership_generation_cannot_be_rolled_back_by_catalog_update(self):
        self.catalog["objects"][OBJECT]["grants"][ACTOR]["membership_generation"] = 2
        self.write("catalog.json", canonical(self.catalog))
        with LocalItemMaterialResolver(str(self.root)) as writer:
            with self.assertRaises(ItemMaterialUnavailable):
                writer.publish_catalog(
                    expected_digest=digest(canonical(self.catalog)),
                    replacement=self.replacement(membership_generation=1),
                )
        self.assertEqual((self.root / "catalog.json").read_bytes(), canonical(self.catalog))

    def test_publicly_readable_and_hardlinked_objects_are_rejected(self):
        os.chmod(self.root / OBJECT, 0o644)
        with LocalItemMaterialResolver(str(self.root)) as reader, reader.lease():
            with self.assertRaises(ItemMaterialUnavailable):
                self.capture(reader)
        os.chmod(self.root / OBJECT, 0o600)
        os.link(self.root / OBJECT, self.root / "alias")
        with LocalItemMaterialResolver(str(self.root)) as reader, reader.lease():
            with self.assertRaises(ItemMaterialUnavailable):
                self.capture(reader)

    def test_nested_lease_cannot_replace_an_active_capture_token(self):
        with LocalItemMaterialResolver(str(self.root)) as reader, reader.lease():
            captured = self.capture(reader)
            with self.assertRaisesRegex(ItemMaterialUnavailable, "LEASE_ACTIVE"), reader.lease():
                pass
            reader.revalidate(captured)

    def test_catalog_publisher_preserves_immutable_object_identity_and_tombstones(self):
        proposals = []
        changed = self.replacement()
        changed["objects"][OBJECT]["classification"] = "RESTRICTED"
        proposals.append(changed)
        changed = self.replacement()
        changed["objects"][OBJECT]["grants"] = {}
        proposals.append(changed)
        changed = self.replacement(can_read=False)
        changed["objects"][OBJECT]["grants"][ACTOR]["acl_generation"] = 1
        proposals.append(changed)
        changed = self.replacement()
        changed["objects"] = {}
        proposals.append(changed)
        for proposed in proposals:
            with self.subTest(proposed=proposed), LocalItemMaterialResolver(str(self.root)) as writer:
                with self.assertRaises(ItemMaterialUnavailable):
                    writer.publish_catalog(expected_digest=digest(canonical(self.catalog)), replacement=proposed)
        self.assertEqual((self.root / "catalog.json").read_bytes(), canonical(self.catalog))

    def test_stale_catalog_publish_has_no_effect(self):
        with LocalItemMaterialResolver(str(self.root)) as writer:
            with self.assertRaisesRegex(ItemMaterialUnavailable, "VERSION_CHANGED"):
                writer.publish_catalog(
                    expected_digest="sha256:" + "0" * 64, replacement=self.replacement(can_read=False)
                )
        self.assertEqual((self.root / "catalog.json").read_bytes(), canonical(self.catalog))

    def test_symlink_object_is_rejected(self):
        (self.root / OBJECT).unlink()
        (self.root / OBJECT).symlink_to(self.root / "catalog.json")
        with LocalItemMaterialResolver(str(self.root)) as reader, reader.lease():
            with self.assertRaises(ItemMaterialUnavailable):
                self.capture(reader)

    def test_missing_or_symlink_lock_uses_stable_unavailable_error(self):
        (self.root / "catalog.lock").unlink()
        with LocalItemMaterialResolver(str(self.root)) as reader:
            with self.assertRaises(ItemMaterialUnavailable), reader.lease():
                pass
        (self.root / "catalog.lock").symlink_to(self.root / "catalog.json")
        with LocalItemMaterialResolver(str(self.root)) as reader:
            with self.assertRaises(ItemMaterialUnavailable), reader.lease():
                pass

    def test_duplicate_catalog_keys_are_rejected(self):
        raw = canonical(self.catalog).replace(b'"generation":1', b'"generation":1,"generation":1')
        self.write("catalog.json", raw)
        with LocalItemMaterialResolver(str(self.root)) as reader, reader.lease():
            with self.assertRaises(ItemMaterialUnavailable):
                self.capture(reader)

    def test_initial_zero_membership_requires_its_exact_explicit_grant(self):
        self.catalog["objects"][OBJECT]["grants"][ACTOR]["membership_generation"] = 0
        self.write("catalog.json", canonical(self.catalog))
        with LocalItemMaterialResolver(str(self.root)) as reader, reader.lease():
            self.capture(reader, membership_generation=0)
            with self.assertRaises(ItemMaterialUnavailable):
                self.capture(reader, membership_generation=1)

    def test_feature_description_catalog_cannot_authorize_item_scope(self):
        from plane.curve.feature_local_material import EDITION as FEATURE_EDITION

        self.catalog["schema_version"] = FEATURE_EDITION
        self.write("catalog.json", canonical(self.catalog))
        with LocalItemMaterialResolver(str(self.root)) as reader, reader.lease():
            with self.assertRaises(ItemMaterialUnavailable):
                self.capture(reader)

    def test_feature_grant_destination_cannot_authorize_item_scope(self):
        self.catalog["objects"][OBJECT]["destination"] = "CURVE_FEATURE_LOCAL_V1"
        self.write("catalog.json", canonical(self.catalog))
        with LocalItemMaterialResolver(str(self.root)) as reader, reader.lease():
            with self.assertRaises(ItemMaterialUnavailable):
                self.capture(reader)

    def test_scope_requirement_and_current_membership_generation_are_mandatory(self):
        from dataclasses import replace
        from plane.curve.feature_material import FeatureMaterialRequirement

        requirements = self.requirements()
        invalid = (
            (),
            requirements * 2,
            (replace(requirements[0], purposes=frozenset({"REQUESTED"})),),
            (FeatureMaterialRequirement(requirements[0].reference, frozenset({"ITEM_SCOPE"})),),
        )
        with LocalItemMaterialResolver(str(self.root)) as reader, reader.lease():
            for value in invalid:
                with self.subTest(value=value), self.assertRaises(ItemMaterialUnavailable):
                    self.capture(reader, requirements=value)
            for generation in (-1, True, None):
                with self.subTest(generation=generation), self.assertRaises(ItemMaterialUnavailable):
                    self.capture(reader, membership_generation=generation)

    def test_local_profile_requires_explicit_enablement(self):
        for environment, enabled in (("PRODUCTION", True), ("LOCAL", False), ("LOCAL", 1)):
            fake = SimpleNamespace(
                CURVE_ENVIRONMENT=environment,
                CURVE_LOCAL_ITEM_MATERIAL_ENABLED=enabled,
                CURVE_LOCAL_ITEM_MATERIAL_ROOT=str(self.root),
            )
            with (
                patch("plane.curve.item_local_material.settings", fake),
                self.assertRaises(ItemMaterialUnavailable),
            ):
                LocalItemMaterialResolver.from_settings()
        fake = SimpleNamespace(
            CURVE_ENVIRONMENT="LOCAL",
            CURVE_LOCAL_ITEM_MATERIAL_ENABLED=True,
            CURVE_LOCAL_ITEM_MATERIAL_ROOT=str(self.root),
        )
        with (
            patch("plane.curve.item_local_material.settings", fake),
            LocalItemMaterialResolver.from_settings() as reader,
            reader.lease(),
        ):
            self.capture(reader)


if __name__ == "__main__":
    unittest.main()
