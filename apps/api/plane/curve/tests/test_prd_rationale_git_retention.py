# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from plane.curve.models import PrdReviewDecision
from plane.curve.prd_review_rationale import review_decision_wire_record
from plane.curve.tests.test_prd_review_models import decision_fixture

pytestmark = [pytest.mark.unit, pytest.mark.django_db]
COMMIT = "ab" * 20
BODY = b"Synthetic review rationale."


def prepared(state="APPROVED"):
    *_, legacy = decision_fixture(state=state)
    metadata = legacy.as_metadata()
    wire = review_decision_wire_record(metadata=metadata, rationale_bytes=BODY)
    wire["schema_version"] = "2.0"
    return PrdReviewDecision.from_wire(
        decision=wire,
        rationale_ref=metadata["rationale_ref"],
        rationale_access_envelope_id=metadata["rationale_access_envelope_id"],
        rationale_retention_policy_version_id=COMMIT,
    ), wire


@pytest.mark.parametrize("state", ["APPROVED", "CHANGES_REQUESTED", "REJECTED"])
def test_v2_rationale_identity_and_original_bytes_round_trip(state):
    decision, wire = prepared(state)
    original = decision.as_metadata()
    decision.save()
    decision.refresh_from_db()
    assert decision.as_metadata() == original
    assert decision.rationale_retention_policy_version_id == COMMIT
    assert BODY.decode() not in repr(decision.__dict__)
    assert review_decision_wire_record(metadata=original, rationale_bytes=BODY) == wire
    with pytest.raises(ValidationError):
        review_decision_wire_record(metadata=original, rationale_bytes=BODY + b" changed")


@pytest.mark.parametrize("value", ["main", "HEAD", "a" * 12, "A" * 40, "a" * 40 + "~1", "a" * 39 + "\n"])
def test_v2_rejects_invalid_policy_refs_in_orm_and_database(value):
    decision, _ = prepared()
    decision.rationale_retention_policy_version_id = value
    with pytest.raises(ValidationError):
        decision.save()
    with patch.object(PrdReviewDecision, "validate_metadata"), pytest.raises(DatabaseError), transaction.atomic():
        decision.save()


@pytest.mark.parametrize(
    "edition,value",
    [("1.0-candidate", COMMIT), ("2.0-candidate", "00000000-0000-4000-8000-000000000001"), ("3.0-candidate", COMMIT)],
)
def test_record_edition_cannot_be_inferred_or_mixed(edition, value):
    decision, _ = prepared()
    decision.metadata_schema_version = edition
    decision.rationale_retention_policy_version_id = value
    with pytest.raises(ValidationError):
        decision.save()
    with patch.object(PrdReviewDecision, "validate_metadata"), pytest.raises(DatabaseError), transaction.atomic():
        decision.save()


@pytest.mark.django_db(transaction=True)
def test_legacy_rationale_survives_reverse_and_forward_migration():
    *_, decision = decision_fixture()
    decision.save()
    original = decision.as_metadata()
    latest = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0017_prd_git_retention")])
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rationale_retention_policy_version_id::text FROM curve_prd_review_decision WHERE id=%s",
                [decision.id],
            )
            assert cursor.fetchone()[0] == original["rationale_retention_policy_version_id"]
    finally:
        MigrationExecutor(connection).migrate(latest)
    decision.refresh_from_db()
    assert decision.as_metadata() == original


@pytest.mark.django_db(transaction=True)
def test_reverse_preserves_retained_v2_rationale():
    decision, _ = prepared()
    decision.save()
    original = decision.as_metadata()
    latest = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        with pytest.raises(DatabaseError, match="preservation migration"):
            MigrationExecutor(connection).migrate([("curve", "0017_prd_git_retention")])
    finally:
        MigrationExecutor(connection).migrate(latest)
    decision.refresh_from_db()
    assert decision.as_metadata() == original
