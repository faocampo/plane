# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Real DB graph guards, immutable provenance, rollback and pre-plan qualification."""
# ruff: noqa: F811 - imported pytest fixtures intentionally name test parameters.

from pathlib import Path
import uuid

import pytest
from django.db import DatabaseError, connection, transaction

from plane.curve.models import DocumentCheckpoint, ImmutableRecordError, Initiative, OutboxEvent, PrdReviewDecision
from plane.curve.prd_acceptance import PrdRuntimeUnavailable
from plane.curve.prd_commands import PrdCommandError
from plane.curve.prd_completion import PrdCompletionUnavailable
from plane.curve.scope_proposal_models import ScopeProposalItem
from plane.curve.scope_reopening_models import ScopeReopening
from plane.curve.scope_reopening_qualification import require_reopening_qualification
from plane.curve.scoped_prd_models import ScopedPrdAcceptedCommand, ScopedPrdSubject
from plane.curve.tests.test_scope_reopening_services import (  # noqa: F401
    DENIED,
    accept,
    adopt,
    bridge,
    complete,
    configuration,
    context,
    history,
    no_reopening,
    reopen,
    reopening,
    replacement,
    review_command,
    stage,
    submission,
    submit,
)

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def sql_fails(sql, values=()):
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(sql, values)
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_ledger_is_immutable_in_python_and_raw_sql(reopening):
    result = reopen(reopening)
    record = ScopeReopening.objects.get(id=result.data["id"])
    with pytest.raises((ImmutableRecordError, PermissionError)):
        record.save()
    with pytest.raises(ImmutableRecordError):
        ScopeReopening.objects.filter(id=record.id).delete()
    sql_fails("UPDATE curve_scope_reopening SET digest=digest WHERE id=%s", [record.id])
    sql_fails("DELETE FROM curve_scope_reopening WHERE id=%s", [record.id])
    sql_fails("UPDATE curve_scope_reopening SET workspace_id=%s WHERE id=%s", [uuid.uuid4(), record.id])
    assert ScopeReopening.objects.get(id=record.id).as_record() == result.data
    copy = record.as_record()
    copy["revision"]["items"].clear()
    assert record.as_record() == result.data


@pytest.mark.parametrize("attack", ["clear_marker", "replace_marker", "rewind_head", "restore_approval"])
def test_raw_sql_cannot_restore_stale_authority_or_publish_partial_head(reopening, attack):
    stage(reopening, "PLANNING")
    old_decision = reopening.initiative.controlling_prd_decision_id
    old_revision = reopening.scope["id"]
    result = adopt(reopening, reopen(reopening))
    if attack == "clear_marker":
        sql_fails("UPDATE curve_initiative SET pending_scope_reopening_id=NULL WHERE id=%s", [reopening.initiative.id])
    elif attack == "replace_marker":
        sql_fails(
            "UPDATE curve_initiative SET pending_scope_reopening_id=%s WHERE id=%s",
            [uuid.uuid4(), reopening.initiative.id],
        )
    elif attack == "rewind_head":
        sql_fails(
            "UPDATE curve_scope_proposal SET current_revision_id=%s, version=1 WHERE initiative_id=%s",
            [old_revision, reopening.initiative.id],
        )
    else:
        sql_fails(
            "UPDATE curve_initiative SET state='PLANNING', controlling_prd_decision_id=%s, "
            "pending_scope_reopening_id=NULL, version=version+1 WHERE id=%s",
            [old_decision, reopening.initiative.id],
        )
    reopening.initiative.refresh_from_db()
    assert reopening.initiative.state == "ALIGNING"
    assert reopening.initiative.pending_scope_reopening_id == uuid.UUID(result.data["id"])
    assert reopening.initiative.controlling_prd_decision_id is None


@pytest.mark.parametrize("field", ["id", "workspace_id", "initiative_id", "scope_revision_id"])
def test_raw_insert_cannot_append_forged_ledger_to_committed_history(reopening, field):
    record = ScopeReopening.objects.get(id=reopen(reopening).data["id"])
    columns = [column.column for column in ScopeReopening._meta.local_fields]
    quoted = ", ".join(connection.ops.quote_name(column) for column in columns)
    select, values = [], []
    for column in columns:
        if column == "id" or column == field:
            select.append("%s")
            values.append(uuid.uuid4())
        else:
            select.append(connection.ops.quote_name(column))
    sql_fails(
        f"INSERT INTO curve_scope_reopening ({quoted}) SELECT {', '.join(select)} "
        "FROM curve_scope_reopening WHERE id=%s",
        [*values, record.id],
    )
    assert ScopeReopening.objects.count() == 1


@pytest.mark.parametrize("missing", ["ledger", "member", "outbox"])
def test_partial_same_transaction_reopening_graph_rolls_back(reopening, monkeypatch, missing):
    before = Initiative.objects.filter(id=reopening.initiative.id).values().get()
    if missing == "ledger":
        monkeypatch.setattr(ScopeReopening, "save", lambda *_args, **_kwargs: None)
    elif missing == "member":
        monkeypatch.setattr(ScopeProposalItem, "save", lambda *_args, **_kwargs: None)
    else:
        monkeypatch.setattr(OutboxEvent, "save", lambda *_args, **_kwargs: None)
    with pytest.raises((*DENIED, DatabaseError, PermissionError, PrdRuntimeUnavailable)):
        reopen(reopening)
    assert Initiative.objects.filter(id=reopening.initiative.id).values().get() == before
    no_reopening(reopening)
    assert ScopeProposalItem.objects.count() == 1


@pytest.mark.parametrize("stage_name", ["submit", "approve"])
def test_pending_accepted_command_is_retained_but_cannot_apply_after_reopening(reopening, stage_name):
    if stage_name == "submit":
        command = submission(reopening)
    else:
        subject, _, _ = submit(reopening)
        command = review_command(reopening, subject)
    operation = accept(reopening, command).operation
    accepted = ScopedPrdAcceptedCommand.objects.filter(operation_id=operation.id).values().get()
    counts = (DocumentCheckpoint.objects.count(), ScopedPrdSubject.objects.count(), PrdReviewDecision.objects.count())
    result = adopt(reopening, reopen(reopening))
    try:
        outcome = complete(reopening, operation)
    except (PrdCommandError, PrdCompletionUnavailable):
        outcome = None
    if outcome is not None:
        assert outcome["status"] in {"FAILED", "CANCELLED"} and not outcome["effect_applied"]
    assert ScopedPrdAcceptedCommand.objects.filter(operation_id=operation.id).values().get() == accepted
    assert (
        DocumentCheckpoint.objects.count(),
        ScopedPrdSubject.objects.count(),
        PrdReviewDecision.objects.count(),
    ) == counts
    reopening.initiative.refresh_from_db()
    assert reopening.initiative.pending_scope_reopening_id == uuid.UUID(result.data["id"])
    assert reopening.initiative.state == "ALIGNING"


@pytest.mark.parametrize("state,paused", [("DRAFT", None), ("PAUSED", "ALIGNING"), ("CANCELLED", None)])
def test_nonallowed_states_cannot_reopen(reopening, state, paused):
    from plane.curve.tests.test_prd_lifecycle_repository import raw_update

    changes = dict(state=state, paused_from_state=paused)
    if state == "DRAFT":
        changes["workflow_version_id"] = None
    raw_update(reopening.initiative.id, **changes)
    reopening.initiative.refresh_from_db()
    with pytest.raises(DENIED):
        reopen(reopening)
    no_reopening(reopening)


def test_qualification_accepts_only_exact_registered_model_catalog(reopening, monkeypatch):
    import plane.curve.scope_reopening_qualification as qualification

    original = qualification.current_model_catalog()
    with transaction.atomic():
        require_reopening_qualification()
    monkeypatch.setattr(
        qualification,
        "current_model_catalog",
        lambda: [
            *original,
            dict(model_name="unapprovedplan", db_table="curve_unapproved_plan", columns=["id", "approved"]),
        ],
    )
    with pytest.raises(PrdCommandError), transaction.atomic():
        require_reopening_qualification()
    no_reopening(reopening)


@pytest.mark.parametrize("damage", ["changed_migration_bytes", "new_migration", "changed_qualification"])
def test_source_qualification_rejects_byte_drift_without_operator_override(reopening, monkeypatch, damage):
    import plane.curve.scope_reopening_qualification as qualification

    real_read = Path.read_bytes
    real_glob = Path.glob
    directory = Path(qualification.__file__).parent / "migrations"

    def read(path):
        data = real_read(path)
        if damage == "changed_migration_bytes" and path == directory / "0022_scoped_prd.py":
            return data + b"\n# unauthorized source drift\n"
        if damage == "changed_qualification" and path == qualification.QUALIFICATION_PATH:
            return data + b" "
        return data

    monkeypatch.setattr(Path, "read_bytes", read)
    if damage == "new_migration":

        def glob(path, pattern):
            files = list(real_glob(path, pattern))
            return iter([*files, directory / "9999_unapproved_plan.py"] if path == directory else files)

        monkeypatch.setattr(Path, "glob", glob)
    with pytest.raises(PrdCommandError), transaction.atomic():
        require_reopening_qualification()
    no_reopening(reopening)


@pytest.mark.parametrize("damage", ["table", "column", "trigger", "function"])
def test_database_independently_rejects_unmigrated_physical_catalog_drift(reopening, damage):
    # DDL and its failed coverage assertion are one rolled-back test transaction.
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        if damage == "table":
            cursor.execute("CREATE TABLE curve_unapproved_plan (id uuid PRIMARY KEY, approved boolean)")
        elif damage == "column":
            cursor.execute("ALTER TABLE curve_initiative ADD COLUMN unapproved_plan_id uuid")
        elif damage == "trigger":
            cursor.execute(
                "SELECT tgname FROM pg_trigger WHERE tgrelid='curve_scope_reopening'::regclass "
                "AND NOT tgisinternal ORDER BY tgname LIMIT 1"
            )
            name = cursor.fetchone()[0]
            cursor.execute(f"ALTER TABLE curve_scope_reopening DISABLE TRIGGER {connection.ops.quote_name(name)}")
        else:
            cursor.execute(
                "SELECT pg_get_functiondef(tgfoid) FROM pg_trigger "
                "WHERE tgrelid='curve_scope_reopening'::regclass AND NOT tgisinternal ORDER BY tgname LIMIT 1"
            )
            definition = cursor.fetchone()[0]
            # Change executable function source while keeping its signature/trigger.
            marker = definition.index("$function$") + len("$function$")
            cursor.execute(definition[:marker] + "\n-- unauthorized guard source drift\n" + definition[marker:])
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    with transaction.atomic():
        require_reopening_qualification()
    no_reopening(reopening)


@pytest.mark.parametrize(
    "field", ["workspace_id", "initiative_id", "scope_revision_id", "created_by", "policy_decision_id"]
)
def test_ledger_public_projection_rejects_typed_column_substitution(reopening, field):
    record = ScopeReopening.objects.get(id=reopen(reopening).data["id"])
    setattr(record, field, uuid.uuid4())
    with pytest.raises((ImmutableRecordError, PrdCommandError)):
        record.as_record()


def test_direct_raw_sql_truncate_keeps_immutable_ledger_guard_enabled(reopening):
    result = reopen(reopening)
    with pytest.raises(DatabaseError, match="immutable"), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("TRUNCATE curve_scope_reopening CASCADE")
    assert ScopeReopening.objects.get(id=result.data["id"]).as_record() == result.data
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgenabled FROM pg_trigger WHERE tgrelid='curve_scope_reopening'::regclass "
            "AND tgname='curve_reopen_no_truncate'"
        )
        assert cursor.fetchone() == ("O",)
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


@pytest.mark.parametrize("attack", ["no_op_verifier", "forged_seal"])
def test_application_independently_rejects_compromised_database_coverage_proof(reopening, attack):
    # Disposable transaction-only corruption: even a self-consistent attacker
    # seal or no-op database verifier cannot replace the reviewed source pin.
    with pytest.raises(PrdCommandError), transaction.atomic(), connection.cursor() as cursor:
        if attack == "no_op_verifier":
            cursor.execute(
                "CREATE OR REPLACE FUNCTION curve_scope_reopening_verify_coverage() "
                "RETURNS void LANGUAGE plpgsql AS $$ BEGIN RETURN; END $$"
            )
        else:
            cursor.execute("CREATE TABLE curve_unapproved_plan (id uuid PRIMARY KEY)")
            cursor.execute(
                "SELECT 'sha256:' || encode(sha256(convert_to(curve_scope_reopening_catalog()::text, 'UTF8')), 'hex')"
            )
            forged_digest = cursor.fetchone()[0]
            # Forge the installed successor's active seal. Historical predecessor
            # seals are separately pinned by the current database verifier.
            cursor.execute("ALTER TABLE curve_manual_gate2_v2_coverage DISABLE TRIGGER curve_mg2_coverage_immutable")
            cursor.execute("UPDATE curve_manual_gate2_v2_coverage SET catalog_digest=%s", [forged_digest])
            cursor.execute("ALTER TABLE curve_manual_gate2_v2_coverage ENABLE TRIGGER curve_mg2_coverage_immutable")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
        require_reopening_qualification()
    with transaction.atomic():
        require_reopening_qualification()
    no_reopening(reopening)


@pytest.mark.parametrize("damage", ["edited_writer", "new_writer", "linked_writer"])
def test_runtime_writer_source_closure_rejects_unreviewed_python(reopening, monkeypatch, damage):
    import plane.curve.scope_reopening_qualification as qualification

    root = Path(qualification.__file__).parent
    edited = root / "scope_proposal_services.py"
    added = root / "unreviewed_plan_writer.py"
    original_read, original_glob, original_symlink = Path.read_bytes, Path.rglob, Path.is_symlink

    def read_bytes(path):
        if path == added:
            return b"def approve_plan(): return True\n"
        data = original_read(path)
        return data + b"\n# unreviewed writer change\n" if damage == "edited_writer" and path == edited else data

    def rglob(path, pattern):
        result = list(original_glob(path, pattern))
        return iter([*result, added] if damage == "new_writer" and path == root else result)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(Path, "rglob", rglob)
    if damage == "linked_writer":
        monkeypatch.setattr(Path, "is_symlink", lambda path: path == edited or original_symlink(path))
    with pytest.raises(PrdCommandError), transaction.atomic():
        require_reopening_qualification()
    no_reopening(reopening)


@pytest.mark.parametrize(
    "damage", ["unknown_key", "missing_key", "schema", "edition", "writer_inventory", "exclusions"]
)
def test_qualification_shape_and_writer_inventory_remain_closed_even_with_valid_document_hash(
    reopening, monkeypatch, damage
):
    import hashlib
    import json
    import plane.curve.scope_reopening_qualification as qualification

    data = json.loads(qualification.QUALIFICATION_PATH.read_bytes())
    if damage == "unknown_key":
        data["permit_plan_writers"] = True
    elif damage == "missing_key":
        del data["runtime_sources"]
    elif damage == "schema":
        data["schema_version"] = "future"
    elif damage == "edition":
        data["model_edition"] = "FUTURE_APPROVED_PLAN"
    elif damage == "writer_inventory":
        data["runtime_writer_inventory"].append("PLAN_APPROVAL")
    else:
        data["excluded_writers"].remove("PLAN_APPROVAL")
    raw = json.dumps(data).encode()
    original = Path.read_bytes
    monkeypatch.setattr(
        Path, "read_bytes", lambda path: raw if path == qualification.QUALIFICATION_PATH else original(path)
    )
    # Isolate closed-shape verification from the separate source-digest check.
    monkeypatch.setattr(qualification, "QUALIFICATION_DIGEST", "sha256:" + hashlib.sha256(raw).hexdigest())
    with pytest.raises(PrdCommandError), transaction.atomic():
        require_reopening_qualification()
    no_reopening(reopening)


def test_reverse_migration_refuses_retained_reopening_and_preserves_exact_history(reopening):
    from django.db.migrations.executor import MigrationExecutor
    from django.db.migrations.recorder import MigrationRecorder
    from plane.curve.scope_proposal_models import ScopeProposal, ScopeProposalRevision

    stage(reopening, "PLANNING")
    result = adopt(reopening, reopen(reopening))
    before_initiative = Initiative.objects.filter(id=reopening.initiative.id).values().get()
    before_ledger = ScopeReopening.objects.get(id=result.data["id"]).as_record()
    before_head = ScopeProposal.objects.filter(initiative_id=reopening.initiative.id).values().get()
    before_revisions = list(ScopeProposalRevision.objects.order_by("pk").values())
    before_history = history()
    latest = ("curve", "0023_scope_reopening")
    executor = MigrationExecutor(connection)
    installed_leaves = executor.loader.graph.leaf_nodes("curve")
    before_migrations = set(MigrationRecorder(connection).applied_migrations())
    try:
        # Exercise the historical reopening step without its empty successors.
        # Current-source qualification resumes only after all leaves are restored.
        executor.migrate([latest])
        with pytest.raises(DatabaseError, match="preservation migration"):
            MigrationExecutor(connection).migrate([("curve", "0022_scoped_prd")])
        assert latest in MigrationRecorder(connection).applied_migrations()
        assert Initiative.objects.filter(id=reopening.initiative.id).values().get() == before_initiative
        assert ScopeReopening.objects.get(id=result.data["id"]).as_record() == before_ledger
        assert ScopeProposal.objects.filter(initiative_id=reopening.initiative.id).values().get() == before_head
        assert list(ScopeProposalRevision.objects.order_by("pk").values()) == before_revisions
        assert history() == before_history
    finally:
        MigrationExecutor(connection).migrate(installed_leaves)
    assert set(MigrationRecorder(connection).applied_migrations()) == before_migrations
    assert history() == before_history
    with transaction.atomic():
        require_reopening_qualification()
