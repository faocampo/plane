"""Reviewed Gate2 delta stays exact; no setting can grant a different writer."""

from copy import deepcopy
import hashlib
import json
import pytest
from django.db import connection, transaction, DatabaseError
from django.core.management import call_command
from io import StringIO
from plane.curve import scope_reopening_qualification as root

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def test_exact_successor_and_model_migration_consistency():
    raw = root.GATE2_SUCCESSOR_PATH.read_bytes()
    assert "sha256:" + hashlib.sha256(raw).hexdigest() == root.GATE2_SUCCESSOR_DIGEST
    old = json.loads(root.SCOPE_EDITOR_SUCCESSOR_PATH.read_bytes())["qualification"]
    new = json.loads(raw)
    qualified = root.validate_gate2_successor(old, new)
    assert len(qualified["runtime_sources"]) == len(old["runtime_sources"]) + 9
    assert len(qualified["migration_digests"]) == 25
    assert qualified["excluded_writers"] == ["EXECUTION", "COMPLETION_CREDIT"]
    with transaction.atomic():
        root.require_manual_gate2_v2_qualification()
    call_command("makemigrations", "curve", dry_run=True, check=True, interactive=False, stdout=StringIO())
    variants = []
    value = deepcopy(new)
    value["qualification"]["excluded_writers"] = []
    variants.append(value)
    value = deepcopy(new)
    value["qualification"]["runtime_sources"]["unexpected_writer.py"] = "sha256:" + "0" * 64
    variants.append(value)
    value = deepcopy(new)
    value["qualification"]["migration_digests"]["0024_manual_draft_reconstruction.py"] = "sha256:" + "0" * 64
    variants.append(value)
    value = deepcopy(new)
    value["qualification"]["runtime_sources"]["scope_reopening_services.py"] = "sha256:" + "0" * 64
    variants.append(value)
    value = deepcopy(new)
    value["qualification"]["models"].pop()
    variants.append(value)
    for value in variants:
        with pytest.raises(ValueError):
            root.validate_gate2_successor(old, value)


def test_gate2_seal_resists_rewrite_delete_truncate():
    for sql in (
        "UPDATE curve_manual_gate2_v2_coverage SET catalog_digest='sha256:tampered'",
        "DELETE FROM curve_manual_gate2_v2_coverage",
        "TRUNCATE curve_manual_gate2_v2_coverage",
    ):
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql)
    with transaction.atomic():
        root.require_manual_gate2_v2_qualification()
