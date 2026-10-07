"""Archive integrity and refusal tests; the real restore is a separate exercise."""

import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import recovery

OBJECT = "10000000-0000-4000-8000-000000000001"


class RecoveryValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.body = b"synthetic protected body"
        self.catalog = {
            "schema_version": "curve.synthetic-manual-plan-catalog/v2-candidate",
            "generation": 1,
            "initiatives": {},
            "plans": {},
            "objects": {
                OBJECT: {
                    "object_ref": {
                        "object_id": OBJECT,
                        "size_bytes": len(self.body),
                        "digest": recovery.sha(self.body),
                    }
                }
            },
        }
        self.archive()
        (self.root / "database.dump").write_bytes(b"synthetic dump bytes")
        self.manifest()

    def tearDown(self):
        self.temporary.cleanup()

    def archive(self, extra=None, omit=False):
        with tarfile.open(self.root / "protected.tar", "w") as archive:
            entries = [("catalog.json", json.dumps(self.catalog).encode())]
            if not omit:
                entries.append((OBJECT, self.body))
            for name, raw in entries:
                item = tarfile.TarInfo(name)
                item.size = len(raw)
                archive.addfile(item, io.BytesIO(raw))
            if extra:
                archive.addfile(extra, io.BytesIO(b""))

    def manifest(self):
        value = {
            "format": recovery.FORMAT,
            "synthetic_only": True,
            "source_commit": "a" * 40,
            "postgres_version_num": "150007",
            "tables": {"synthetic_table": {"rows": 0, "sha256": recovery.sha(b"")}},
            "schema_sha256": recovery.sha(b"synthetic schema"),
            "api_image_id": "sha256:" + "a" * 64,
            "postgres_image_id": "sha256:" + "b" * 64,
            "catalog_sha256": recovery.sha(json.dumps(self.catalog).encode()),
            "files": {
                name: {
                    "bytes": (self.root / name).stat().st_size,
                    "sha256": recovery.file_sha(self.root / name),
                }
                for name in ("database.dump", "protected.tar")
            },
        }
        (self.root / "manifest.json").write_text(json.dumps(value))

    def test_valid_backup_preserves_catalog_and_body(self):
        _, members = recovery.verify(self.root)
        self.assertEqual(members[OBJECT], self.body)

    def test_database_corruption_prevents_any_restore_process(self):
        (self.root / "database.dump").write_bytes(b"corrupted bytes")
        with patch.object(recovery, "run") as run:
            with self.assertRaisesRegex(recovery.RecoveryError, "checksum"):
                recovery.exercise(SimpleNamespace(backup=self.root))
            run.assert_not_called()

    def test_object_digest_is_checked_even_with_updated_archive_hash(self):
        self.body = b"different object body"
        self.archive()
        self.manifest()
        with self.assertRaisesRegex(recovery.RecoveryError, "integrity"):
            recovery.verify(self.root)

    def test_missing_catalog_object_fails(self):
        self.archive(omit=True)
        self.manifest()
        with self.assertRaisesRegex(recovery.RecoveryError, "inventory"):
            recovery.verify(self.root)

    def test_archive_paths_links_and_duplicates_fail(self):
        for name, kind in (
            ("../outside", tarfile.REGTYPE),
            ("/absolute", tarfile.REGTYPE),
            (OBJECT, tarfile.SYMTYPE),
            (OBJECT, tarfile.LNKTYPE),
            (OBJECT, tarfile.REGTYPE),
            ("subdirectory", tarfile.DIRTYPE),
        ):
            with self.subTest(name=name, kind=kind):
                extra = tarfile.TarInfo(name)
                extra.type = kind
                extra.linkname = "/outside"
                self.archive(extra=extra)
                self.manifest()
                with self.assertRaises(recovery.RecoveryError):
                    recovery.verify(self.root)

    def test_manifest_cannot_name_arbitrary_files(self):
        path = self.root / "manifest.json"
        value = json.loads(path.read_text())
        value["files"]["../outside"] = {}
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(recovery.RecoveryError, "inventory"):
            recovery.verify(self.root)

    def test_backup_symlink_is_rejected(self):
        path = self.root / "database.dump"
        path.rename(self.root / "elsewhere")
        path.symlink_to(self.root / "elsewhere")
        with self.assertRaisesRegex(recovery.RecoveryError, "unsafe"):
            recovery.verify(self.root)

    def test_cleanup_refuses_a_container_with_another_run_label(self):
        with (
            patch.object(
                recovery.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout=b"different-run"),
            ),
            patch.object(recovery, "run") as remove,
        ):
            recovery.cleanup_owned("synthetic-target", "this-run")
            remove.assert_not_called()

    def test_http_probe_rejects_partial_operator_profile(self):
        with self.assertRaisesRegex(recovery.RecoveryError, "all three"):
            recovery.read_profile(SimpleNamespace(operator_settings="profile.py"))

    def test_pilot_controls_require_the_private_http_profile(self):
        with patch.object(recovery, "run") as run:
            with self.assertRaisesRegex(
                recovery.RecoveryError, "complete private HTTP profile"
            ):
                recovery.exercise(
                    SimpleNamespace(backup=self.root, pilot_controls=True)
                )
            run.assert_not_called()

    def test_http_probe_rejects_group_readable_credentials(self):
        settings = self.root / "operator.py"
        access = self.root / "access.json"
        target = self.root / "target.json"
        for path in (settings, access, target):
            path.write_text("synthetic input")
        access.chmod(0o640)
        with self.assertRaisesRegex(recovery.RecoveryError, "owner-only"):
            recovery.read_profile(
                SimpleNamespace(
                    operator_settings=settings, access_file=access, target_file=target
                )
            )

    def test_isolated_restore_failure_removes_only_created_target(self):
        names = []

        def run(argv, **kwargs):
            if argv[:2] == ["docker", "run"]:
                names.append(argv[argv.index("--name") + 1])
                return b"created"
            if argv[:3] == ["docker", "rm", "-f"]:
                self.assertEqual(argv[3], names[0])
                return b"removed"
            raise AssertionError("unexpected process")

        def subprocess_run(argv, **kwargs):
            if argv[:2] == ["docker", "inspect"]:
                if argv[-1] == names[0]:
                    return SimpleNamespace(returncode=0, stdout=names[0].encode())
                return SimpleNamespace(returncode=1, stdout=b"")
            return SimpleNamespace(returncode=1)

        with (
            patch.object(recovery, "run", side_effect=run) as calls,
            patch.object(recovery, "verify_source", return_value=self.root),
            patch.object(recovery.subprocess, "run", side_effect=subprocess_run),
            patch.object(recovery.time, "sleep"),
        ):
            with self.assertRaisesRegex(recovery.RecoveryError, "did not become ready"):
                recovery.exercise(SimpleNamespace(backup=self.root, source=self.root))
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].startswith("curve-recovery-check-"))
        self.assertEqual(calls.call_args.args[0][:3], ["docker", "rm", "-f"])


if __name__ == "__main__":
    unittest.main()
