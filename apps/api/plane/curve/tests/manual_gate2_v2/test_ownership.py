"""Stable native task ownership across Initiatives, access changes and plan revisions."""

# ruff: noqa: F401,F811
from copy import copy, deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace
import re
import uuid

import pytest
from django.db import close_old_connections, connections
from django.utils import timezone
from plane.db.models import Project, ProjectMember, Issue, State
from plane.curve.models import Initiative, GateAssignment, ProviderConnection, ExternalDocumentBinding, PrdArtifact
from plane.curve.initiative_services import accept_initiative_refinement
from plane.curve.scope_proposal_services import replace_scope_proposal
from plane.curve.tests.test_scoped_prd_bridge import configuration, context, bridge
from plane.curve.tests.test_prd_completion import SyntheticCompletionRuntime
from plane.curve.tests.test_provider_models import connection_values
from plane.curve.tests.manual_plan_v2 import native_fixture
from plane.curve.manual_plan_v2.validation import canonical_json, digest, metadata_digest
from plane.curve.manual_gate2_v2 import reads, services, contracts
from plane.curve.manual_gate2_v2.models import ManualTaskClaimV2, ManualTaskClaimHistoryV2
from .test_gate2 import native, command, execute, approve, counts, save_with_rationales

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def second_initiative(n, settings, tmp_path, monkeypatch):
    other = copy(n)
    actor = dict(actor_type="HUMAN", actor_id=str(n.user.id))
    other.initiative = Initiative.objects.create(
        workspace_id=n.workspace.id,
        product_id=n.product.id,
        mode="STANDALONE",
        keyword="other",
        title="Other synthetic outcome",
        description={},
        risk_tier="STANDARD",
        business_intent="BUSINESS_IMPROVEMENT",
        creator_user_id=n.user.id,
        created_by=actor,
        updated_by=actor,
    )
    other.gates = [
        GateAssignment.objects.create(
            workspace_id=n.workspace.id,
            initiative=other.initiative,
            gate_type=kind,
            approver_user_id=user.id,
            valid_from=timezone.now() - timedelta(days=1),
        )
        for kind, user in zip(("PRD_APPROVAL", "PLAN_APPROVAL", "CODE_READINESS"), n.reviewers)
    ]
    other.scope = replace_scope_proposal(
        request=n.request,
        workspace_slug=n.workspace.slug,
        initiative_id=other.initiative.id,
        expected_version=1,
        raw_idempotency_key="other-scope",
        payload=dict(
            expected_scope_revision=0,
            items=[
                dict(
                    association_id=str(n.association.id),
                    association_version=1,
                    source_issue_id=str(n.issue.id),
                    purpose="PROPOSED_DELIVERY",
                )
            ],
        ),
    ).data
    accept_initiative_refinement(
        request=n.request,
        workspace_slug=n.workspace.slug,
        initiative_id=other.initiative.id,
        expected_version=2,
        raw_idempotency_key="other-refine",
    )
    other.initiative.refresh_from_db()
    provider = n.binding.provider_connection
    other.binding = ExternalDocumentBinding.objects.create(
        workspace_id=n.workspace.id,
        initiative=other.initiative,
        provider_connection=provider,
        provider_file_id="other-synthetic",
        provider_container_id="synthetic-container",
        canonical_url="https://docs.example.invalid/documents/other-synthetic",
        current_provider_version="source-v1",
        current_modified_at=timezone.now(),
        created_by=actor,
    )
    other.artifact = PrdArtifact.objects.create(workspace_id=n.workspace.id, initiative=other.initiative)
    other.runtime = SyntheticCompletionRuntime(
        (other.binding, other.initiative, None, other.gates[0], other.user, other.workspace)
    )
    settings.CURVE_PRD_ACCEPTANCE_RUNTIME = settings.CURVE_PRD_COMPLETION_RUNTIME = other.runtime
    case = native_fixture.semantic_case

    def unique_case(replacement):
        raw = "".join(
            (native_fixture.validation.ROOT / "fixtures" / (name + ".json")).read_text()
            for name in ("definition.valid", "input-identity.valid", "immutable-semantic-facts")
        )
        unique = {value: str(uuid.uuid4()) for value in re.findall(r"30000000-0000-4000-8000-[0-9]{12}", raw)}
        return case({**unique, **replacement})

    path = tmp_path / "second"
    path.mkdir()
    with monkeypatch.context() as patch:
        patch.setattr(native_fixture, "semantic_case", unique_case)
        other = native_fixture.prepare_native_fixture(other, settings, path)
    other = save_with_rationales(other)
    merged = deepcopy(n.manual_catalog)
    merged["generation"] += 1
    for section in ("initiatives", "plans", "objects"):
        assert not (merged[section].keys() & other.manual_catalog[section].keys())
        merged[section].update(other.manual_catalog[section])
    for source in other.manual_root.iterdir():
        if source.name != "catalog.json":
            native_fixture.write(n.manual_root, source.name, source.read_bytes())
    native_fixture.publish_catalog(n, merged)
    other.manual_root, other.manual_catalog = n.manual_root, merged
    settings.CURVE_MANUAL_PLAN_V2_SYNTHETIC_ROOT = str(n.manual_root)
    return other


def test_two_initiatives_overlap_then_reacquire_next_generation(native, settings, tmp_path, monkeypatch):
    nodes = [native, second_initiative(native, settings, tmp_path, monkeypatch)]
    subjects = [execute(n, command(n, "PREPARE")).data for n in nodes]
    commands = [command(n, "APPROVE", subject=s) for n, s in zip(nodes, subjects)]
    barrier, original = Barrier(2, timeout=45), services.validate_in_worker

    def validated(captured):
        result = original(captured)
        barrier.wait()
        return result

    def run(pair):
        n, value = pair
        close_old_connections()
        try:
            result = services.execute(
                request=SimpleNamespace(user=n.reviewers[1]), slug=n.workspace.slug, command=value
            )
            return result.status_code, result.data
        except contracts.Gate2Error as error:
            return error.status, error.code
        finally:
            connections.close_all()

    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=2) as pool:
        patch.setattr(services, "validate_in_worker", validated)
        results = list(pool.map(run, zip(nodes, commands)))
    assert sorted(r[0] for r in results) == [201, 409], results
    winner = next(i for i, r in enumerate(results) if r[0] == 201)
    loser = 1 - winner
    assert ManualTaskClaimV2.objects.count() == ManualTaskClaimHistoryV2.objects.count() == 1
    retained = results[winner][1]
    n, subject = nodes[winner], subjects[winner]
    reconciled = execute(n, command(n, "RECONCILE", subject=subject, claims=retained["claims"])).data
    execute(n, command(n, "RELEASE", subject=subject, claims=retained["claims"], reconciliation=reconciled))
    acquired = execute(nodes[loser], commands[loser]).data
    claim = ManualTaskClaimV2.objects.get()
    assert claim.initiative_id == nodes[loser].initiative.id and claim.generation == 2 and claim.state == "ACTIVE"
    assert acquired["claims"][0]["claim_id"] == retained["claims"][0]["claim_id"]
    assert execute(n, commands[winner]).data == retained
    claim.refresh_from_db()
    assert claim.initiative_id == nodes[loser].initiative.id and claim.generation == 2


def test_access_revocation_project_move_and_fresh_association_preserve_identity(native):
    n = native
    subject, value, approved = approve(n)
    membership = ProjectMember.objects.get(project=n.project, member=n.reviewers[1])
    ProjectMember.objects.filter(id=membership.id).update(is_active=False)
    before = counts()
    with pytest.raises(contracts.Gate2Error):
        execute(n, value)
    with pytest.raises(contracts.Gate2Error):
        reads.status(
            request=SimpleNamespace(user=n.reviewers[1], query_params={}),
            slug=n.workspace.slug,
            initiative_id=n.initiative.id,
        )
    assert counts() == before and ManualTaskClaimV2.objects.get().state == "ACTIVE"
    ProjectMember.objects.filter(id=membership.id).update(is_active=True)
    project = Project.objects.create(workspace=n.workspace, name="Moved synthetic project", identifier="MOVED")
    state = State.objects.create(
        workspace=n.workspace, project=project, name="Ready", color="#000000", group="unstarted"
    )
    Issue.objects.filter(id=n.issue.id).update(project=project, state=state)
    with pytest.raises(contracts.Gate2Error):
        execute(n, command(n, "RECONCILE", subject=subject, claims=approved["claims"]))
    claim = ManualTaskClaimV2.objects.get()
    assert counts() == before and claim.issue_id == n.issue.id and claim.state == "ACTIVE"
    from plane.curve.tests.test_project_association_api import create

    for user in n.reviewers:
        ProjectMember.objects.create(workspace=n.workspace, project=project, member=user, role=15, is_active=True)
    moved = copy(n)
    moved.project = project
    n.product.refresh_from_db()
    response = create(moved, key="associate-moved-project", version=n.product.version)
    assert response.status_code == 201, response.content
    reconciled = execute(n, command(n, "RECONCILE", subject=subject, claims=approved["claims"])).data
    execute(n, command(n, "RELEASE", subject=subject, claims=approved["claims"], reconciliation=reconciled))
    claim.refresh_from_db()
    assert claim.issue_id == n.issue.id and claim.id == uuid.UUID(approved["claims"][0]["claim_id"])
    assert claim.state == "RELEASED" and claim.generation == 1


def test_replacement_definition_read_and_resubmit_use_current_draft(native):
    n = native
    subject = execute(n, command(n, "PREPARE")).data
    execute(n, command(n, "REQUEST_CHANGES", subject=subject))
    catalog = deepcopy(n.manual_catalog)
    old_id = n.manual_identity["definition_ref"]["object_id"]
    new_id = str(uuid.uuid4())
    plan = deepcopy(catalog["plans"][old_id])
    import json

    body = json.loads(n.manual_definition)
    body["slices"][0]["user_outcome"] = "A revised synthetic user outcome."
    raw = canonical_json(body)
    ref = dict(object_id=new_id, digest=digest(raw), size_bytes=len(raw), media_type="application/json")
    plan["identity"]["definition_ref"] = ref
    plan["identity"]["digest"] = metadata_digest(plan["identity"])
    catalog["plans"][new_id] = plan
    catalog["objects"][new_id] = dict(
        deepcopy(catalog["objects"][old_id]), object_ref=ref, material_version_id=new_id, access_envelope_id=new_id
    )
    catalog["generation"] += 1
    native_fixture.write(n.manual_root, new_id, raw)
    native_fixture.publish_catalog(n, catalog)
    request = SimpleNamespace(user=n.user, query_params={})
    result = reads.material(request=request, slug=n.workspace.slug, initiative_id=n.initiative.id, object_id=new_id)
    assert result.data["reference"] == ref and result.data["content"] == raw.decode()
    n.manual_identity = plan["identity"]
    from plane.curve.tests.manual_plan_v2.test_manual_persistence import save, command as draft_command

    n.initiative.refresh_from_db()
    n.draft = save(n, draft_command(n, revision=1, key="replacement-save")).data
    current = reads.status(request=request, slug=n.workspace.slug, initiative_id=n.initiative.id).data
    assert current["definition_ref"] == ref and current["allowed_actions"] == ["PREPARE"]
    assert current["rationales"] == []
    fresh = execute(n, command(n, "PREPARE")).data
    assert fresh["draft_revision_id"] == n.draft["id"] and fresh["id"] != subject["id"]
