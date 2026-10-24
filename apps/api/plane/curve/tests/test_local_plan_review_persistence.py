# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811, F401
import json
import uuid
import pytest
from django.db import connection, transaction, DatabaseError
from plane.curve.models import LocalPlanSubmission, LocalPlanDecision
from plane.curve.local_plan_review import create_plan_submission, create_plan_decision
from plane.curve.local_prd_review import _pin
from plane.curve.tests.test_local_plan_persistence import (
    make,
    context,
    configuration,
    bridge,
    two_stage,
    local,
    store,
    approved,
)  # noqa: F401

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def records(local, approved):
    plan = make(local, approved)
    plan.save()
    args = dict(
        plan=plan.as_record(),
        prd_submission=plan.prd_submission.as_record(),
        prd_approval=plan.prd_decision.as_record(),
    )
    subject = create_plan_submission(
        **args,
        initiative_version=plan.initiative_version,
        submitted_by=str(local.user.id),
        submitted_at="2099-01-01T00:01:00Z",
    )
    submission = LocalPlanSubmission.from_record(subject, plan)
    submission.save()
    decision = create_plan_decision(
        **args,
        submission=subject,
        initiative_version=plan.initiative_version,
        state="APPROVED",
        decided_by=subject["technical_approver_id"],
        decided_at="2099-01-01T00:02:00Z",
    )
    return submission, LocalPlanDecision.from_record(decision, submission)


def test_saved_technical_review_keeps_exact_plan(local, approved):
    submission, decision = records(local, approved)
    decision.save()
    submission.refresh_from_db()
    decision.refresh_from_db()
    submission.validate_metadata()
    decision.validate_metadata()
    assert decision.payload["plan_revision_digest"] == submission.plan_revision.digest


@pytest.mark.parametrize(
    "damage", ["reviewer", "plan_digest", "missing_feedback", "missing_changes_feedback", "extra_field"]
)
def test_direct_insert_cannot_forge_technical_decision(local, approved, damage):
    submission, decision = records(local, approved)
    value = decision.as_record()
    if damage == "reviewer":
        value["decided_by"] = str(uuid.uuid4())
    elif damage == "plan_digest":
        value["plan_revision_digest"] = "sha256:" + "0" * 64
    elif damage == "missing_feedback":
        value.pop("feedback")
    elif damage == "missing_changes_feedback":
        value["state"] = "CHANGES_REQUESTED"
    else:
        value["hidden"] = True
    value["digest"] = _pin(value)
    with transaction.atomic(), pytest.raises(DatabaseError), connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_local_plan_decision (id,workspace_id,initiative_id,plan_submission_id,"
            "initiative_version,state,digest,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
            [
                value[k]
                for k in (
                    "id",
                    "workspace_id",
                    "initiative_id",
                    "plan_submission_id",
                    "initiative_version",
                    "state",
                    "digest",
                )
            ]
            + [json.dumps(value)],
        )


@pytest.mark.parametrize("table", ["submission", "decision"])
@pytest.mark.parametrize("mutation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_saved_review_records_are_immutable(local, approved, table, mutation):
    _, decision = records(local, approved)
    decision.save()
    table_name = "curve_local_plan_" + table
    statement = {
        "UPDATE": f"UPDATE {table_name} SET initiative_version=100",
        "DELETE": f"DELETE FROM {table_name}",
        "TRUNCATE": f"TRUNCATE {table_name} CASCADE",
    }[mutation]
    with transaction.atomic(), pytest.raises(DatabaseError), connection.cursor() as cursor:
        cursor.execute(statement)
