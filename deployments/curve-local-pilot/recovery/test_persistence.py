# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import http_probe
import persistence
import recovery


class PersistentStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.object = self.root / str(uuid.uuid4())
        self.object.write_bytes(b"synthetic evidence")
        self.object.chmod(0o600)
        catalog = {
            "schema_version": "curve.synthetic-manual-plan-catalog/v2-candidate",
            "objects": {
                self.object.name: {
                    "object_ref": {
                        "object_id": self.object.name,
                        "size_bytes": self.object.stat().st_size,
                        "digest": recovery.sha(self.object.read_bytes()),
                    }
                }
            },
        }
        self.catalog = self.root / "catalog.json"
        self.catalog.write_text(json.dumps(catalog))
        self.catalog.chmod(0o600)
        self.digest = recovery.sha(self.catalog.read_bytes())

    def verify(self):
        return http_probe.verify_existing_objects(self.digest, self.root)

    def test_persisted_store_is_verified_without_rewriting(self):
        before = self.object.stat().st_mtime_ns
        self.assertEqual(self.verify(), 1)
        self.assertEqual(self.object.stat().st_mtime_ns, before)

    def test_corrupt_body_blocks_readiness(self):
        self.object.write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "body mismatch"):
            self.verify()

    def test_missing_body_is_not_reseeded(self):
        self.object.unlink()
        with self.assertRaisesRegex(RuntimeError, "inventory"):
            self.verify()
        self.assertFalse(self.object.exists())

    def test_world_readable_catalog_is_rejected(self):
        self.catalog.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "Unsafe protected object"):
            self.verify()

    def test_linked_object_is_rejected(self):
        raw = self.object.read_bytes()
        self.object.unlink()
        outside = self.root.parent / (self.root.name + "-outside")
        outside.write_bytes(raw)
        self.addCleanup(outside.unlink)
        self.object.symlink_to(outside)
        with self.assertRaises(OSError):
            self.verify()


class LifecycleBoundaryTests(unittest.TestCase):
    token = "curve-recovery-check-0123456789ab"

    def test_foreign_volume_is_never_deleted(self):
        with (
            patch.object(persistence, "inventory", return_value={self.token + "-db"}),
            patch.object(
                recovery, "run", return_value=json.dumps([{"Labels": {persistence.LABEL: "another-owner"}}]).encode()
            ) as run,
        ):
            with self.assertRaisesRegex(recovery.RecoveryError, "ownership"):
                persistence.owned("volume", self.token + "-db", self.token)
            self.assertEqual(len(run.call_args_list), 1)
            self.assertNotIn("rm", run.call_args.args[0])

    def test_missing_volume_blocks_start_without_creating_it(self):
        with patch.object(persistence, "inventory", return_value=set()), patch.object(recovery, "run") as run:
            with self.assertRaisesRegex(recovery.RecoveryError, "implicit reinitialization"):
                persistence.owned("volume", self.token + "-db", self.token)
            run.assert_not_called()

    def test_journal_cannot_expand_cleanup_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            recovery.private_file(
                path,
                json.dumps(
                    {"format": persistence.FORMAT, "owner": self.token, "volumes": ["live-db", "live-objects"]}
                ).encode(),
            )
            with self.assertRaisesRegex(recovery.RecoveryError, "unexpected volumes"):
                persistence.read_journal(path)

    def test_cleanup_attempts_remaining_owned_resources_after_failure(self):
        state = {
            "owner": self.token,
            "volumes": [self.token + "-db", self.token + "-objects"],
            "managed_volumes": [self.token + "-db", self.token + "-objects"],
            "managed_containers": [],
        }

        def check(kind, name, *args, **kwargs):
            if name == self.token + "-db":
                raise recovery.RecoveryError("foreign")
            return kind == "volume"

        with patch.object(persistence, "owned", side_effect=check), patch.object(recovery, "run") as run:
            with self.assertRaisesRegex(recovery.RecoveryError, "cleanup incomplete"):
                persistence.cleanup(state)
            run.assert_called_once_with(["docker", "volume", "rm", self.token + "-objects"])

    def test_atomic_journal_is_private_and_rejects_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            args = SimpleNamespace(journal=str(path))
            lifecycle = persistence.Lifecycle(args)
            lifecycle.state = {
                "format": persistence.FORMAT,
                "owner": self.token,
                "volumes": [self.token + "-db", self.token + "-objects"],
                "events": [],
                "managed_volumes": [],
                "managed_containers": [],
            }
            lifecycle.write("PREPARING")
            lifecycle.write("RESTORING_NEW_TARGET")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(persistence.read_journal(path)["stage"], "RESTORING_NEW_TARGET")
            with self.assertRaisesRegex(recovery.RecoveryError, "must be new"):
                persistence.Lifecycle(args)

    def test_no_synthetic_scope_prevents_any_docker_operation(self):
        with patch.object(recovery, "run") as run:
            with self.assertRaisesRegex(recovery.RecoveryError, "synthetic"):
                persistence.qualify(SimpleNamespace(synthetic_local=False))
            run.assert_not_called()

    def test_preexisting_same_label_volume_is_not_claimed_or_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            cycle = persistence.Lifecycle(SimpleNamespace(journal=str(Path(directory) / "journal.json")))

            def inventory(kind):
                return {self.token + "-db"} if kind == "volume" else set()

            with patch.object(persistence, "inventory", side_effect=inventory), patch.object(recovery, "run") as run:
                with self.assertRaisesRegex(recovery.RecoveryError, "existing volume"):
                    cycle.prepare(self.token, {})
                self.assertEqual(cycle.state["managed_volumes"], [])
                persistence.cleanup(cycle.state)
                run.assert_not_called()

    def test_failed_initialization_records_stage_and_runs_owned_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(synthetic_local=True, journal=str(Path(directory) / "journal.json"))

            def failure(arguments):
                cycle = arguments._lifecycle
                cycle.state = {
                    "format": persistence.FORMAT,
                    "owner": self.token,
                    "volumes": [self.token + "-db", self.token + "-objects"],
                    "managed_volumes": [],
                    "managed_containers": [],
                    "events": [],
                }
                cycle.write("RESTORING_NEW_TARGET")
                raise recovery.RecoveryError("Injected initialization failure")

            with (
                patch.object(recovery, "read_profile", return_value=[1, 2, 3]),
                patch.object(recovery, "exercise", side_effect=failure),
                patch.object(persistence, "cleanup") as cleanup,
            ):
                with self.assertRaisesRegex(recovery.RecoveryError, "Injected"):
                    persistence.qualify(args)
                cleanup.assert_called_once()
            state = persistence.read_journal(args.journal)
            self.assertEqual(state["outcome"], "FAILED")
            self.assertEqual(state["failure_stage"], "RESTORING_NEW_TARGET")
            self.assertEqual(state["stage"], "CLEANED")


if __name__ == "__main__":
    unittest.main()
