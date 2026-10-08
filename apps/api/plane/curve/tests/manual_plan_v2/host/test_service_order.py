# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Host orchestration checks only: test doubles do not establish DB atomicity."""

# ruff: noqa: E402 -- Configure Django before candidate imports.
from contextlib import contextmanager, ExitStack
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch
import uuid

import bootstrap

bootstrap.install()

from manual_plan_v2 import contracts, repository, services
from test_draft_core import command, fixture, initiative, revision


class IdempotencyConflict(Exception):
    pass


class CommandInProgress(Exception):
    pass


class ServiceOrderTests(unittest.TestCase):
    def setUp(self):
        self.trace = []
        self.atomic = False
        self.record = SimpleNamespace(key_digest="synthetic-key-digest")
        self.captured = SimpleNamespace(identity=fixture("input-identity.valid"), file_fence=("same",))
        self.context = SimpleNamespace(
            initiative=initiative(),
            actor_id=uuid.UUID(fixture("revision.valid")["created_by"]),
            workspace=SimpleNamespace(id=initiative().workspace_id),
        )
        self.resolver = Mock()
        self.resolver.__enter__ = Mock(return_value=self.resolver)
        self.resolver.__exit__ = Mock(return_value=False)
        self.receipt = SimpleNamespace(decision_id=uuid.uuid4(), correlation_id="synthetic")
        self.request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True))
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        modules = {
            "plane.curve.models": SimpleNamespace(AuditEvent=Mock()),
            "plane.curve.product_services": SimpleNamespace(
                _load_or_create_idempotency=Mock(return_value=(self.record, None, False))
            ),
            "plane.curve.services": SimpleNamespace(
                _append_audit_event=Mock(),
                IdempotencyConflict=IdempotencyConflict,
                CommandAlreadyInProgress=CommandInProgress,
            ),
        }
        modules["plane.curve.models"].AuditEvent.objects.filter.return_value.count.return_value = 1
        self.stack.enter_context(patch.dict(sys.modules, modules))
        self.modules = modules
        for name in ("require_enabled", "require_edition"):
            self.stack.enter_context(patch.object(services, name))
        self.stack.enter_context(
            patch.object(services.SyntheticManualPlanResolverV2, "from_settings", return_value=self.resolver)
        )
        self.stack.enter_context(patch.object(services, "_preflight", return_value=self.captured))
        self.stack.enter_context(patch.object(services, "capture_authorized", return_value=self.captured))
        self.stack.enter_context(patch.object(services, "authority_fence", return_value="current"))
        self.stack.enter_context(patch.object(services, "command_identity", return_value="identity"))
        self.stack.enter_context(patch.object(services, "record_save_authorization", self.authorize))
        self.stack.enter_context(patch.object(services.transaction, "atomic", self.transaction))
        self.stack.enter_context(patch.object(services, "validate_in_worker", self.worker))

    @contextmanager
    def transaction(self):
        self.trace.append("begin")
        self.atomic = True
        try:
            yield
        except BaseException:
            self.trace.append("rollback-requested")
            raise
        else:
            self.trace.append("commit-requested")
        finally:
            self.atomic = False

    @contextmanager
    def authorize(self, **kwargs):
        self.assertTrue(self.atomic)
        yield self.receipt

    def worker(self, captured):
        self.assertFalse(self.atomic)
        self.trace.append("worker")
        return fixture("validation.valid")

    def save(self):
        return services.save_manual_plan(request=self.request, workspace_slug="synthetic", command=command())

    def configure_new(self, *, changed_fence=False):
        row = revision()
        head = SimpleNamespace(id=row.draft_id, version=row.version, current_revision_id=row.id)
        fresh = SimpleNamespace(**vars(self.context))
        fresh.initiative = initiative(10)
        self.stack.enter_context(
            patch.object(services, "load_native", side_effect=[(self.context, None), (fresh, None)])
        )
        self.stack.enter_context(patch.object(services, "load_head", side_effect=[(None, None), (head, row)]))
        publisher = self.stack.enter_context(
            patch.object(services, "publish_new_revision", return_value=repository.DraftResult(row.as_record(), 10))
        )
        if changed_fence:
            self.stack.enter_context(patch.object(services, "authority_fence", side_effect=["before", "after"]))
        return publisher

    def test_worker_precedes_locks_and_success_requests_commit(self):
        publisher = self.configure_new()
        self.assertEqual(self.save().status_code, 201)
        publisher.assert_called_once()
        self.assertEqual(self.trace, ["worker", "begin", "commit-requested"])
        self.resolver.recheck.assert_called_once_with(self.captured.file_fence)

    def test_final_authority_change_escapes_transaction_as_denial(self):
        publisher = self.configure_new(changed_fence=True)
        with self.assertRaises(contracts.ManualPlanError):
            self.save()
        publisher.assert_called_once()
        self.assertEqual(self.trace, ["worker", "begin", "rollback-requested"])

    def test_worker_failure_never_starts_transaction_or_publisher(self):
        with (
            patch.object(
                services, "validate_in_worker", side_effect=contracts.ManualPlanError("VALIDATION_UNAVAILABLE")
            ),
            patch.object(services, "publish_new_revision") as publisher,
        ):
            with self.assertRaises(contracts.ManualPlanError):
                self.save()
            self.assertEqual(self.trace, [])
            publisher.assert_not_called()

    def test_disabled_surface_never_opens_protected_root(self):
        with (
            patch.object(services, "require_enabled", side_effect=contracts.ManualPlanError()),
            patch.object(services.SyntheticManualPlanResolverV2, "from_settings") as factory,
        ):
            with self.assertRaises(contracts.ManualPlanError):
                self.save()
            factory.assert_not_called()
            self.assertEqual(self.trace, [])

    def test_replay_returns_original_revision_with_current_version_without_publishing(self):
        row = revision()
        self.context.initiative.version = 25
        head = SimpleNamespace(id=row.draft_id, version=4, current_revision_id=uuid.uuid4())
        self.modules["plane.curve.product_services"]._load_or_create_idempotency.return_value = (
            self.record,
            None,
            True,
        )
        with (
            patch.object(services, "load_native", return_value=(self.context, None)),
            patch.object(services, "load_head", return_value=(head, None)),
            patch.object(services, "replay_revision", return_value=row),
            patch.object(services, "publish_new_revision") as publisher,
        ):
            result = self.save()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.initiative_version, 25)
        self.assertEqual(result.data["id"], str(row.id))
        publisher.assert_not_called()
        audit = self.modules["plane.curve.services"]._append_audit_event
        self.assertEqual(audit.call_args.kwargs["outcome"], "NO_EFFECT")
        self.assertEqual(self.trace, ["worker", "begin", "commit-requested"])


if __name__ == "__main__":
    unittest.main()
