"""Actual scoped PRD/native ORM plus owner-only synthetic protected bytes."""

from copy import deepcopy
from importlib import import_module, util
import json
import uuid

from django.db import transaction
from django.utils import timezone
from plane.curve.models import PrdArtifactVersion, PrdEvidenceItemVersion, DocumentCheckpoint
from plane.curve.scoped_prd_models import ScopedPrdSubject
from plane.curve.scoped_prd_policy import require_scoped_current
from plane.curve.tests.test_scoped_prd_bridge import submission, accept, complete, review_command
from plane.curve.tests.test_prd_metadata_models import snapshot_entry

from semantic_fixture import semantic_case

PACKAGE = "plane.curve.manual_plan_v2" if util.find_spec("plane.curve.manual_plan_v2") else "manual_plan_v2"
policy = import_module(PACKAGE + ".policy")
synthetic = import_module(PACKAGE + ".synthetic")
validation = import_module(PACKAGE + ".validation")
canonical_json, digest, metadata_digest = validation.canonical_json, validation.digest, validation.metadata_digest


def submit_with_retained_evidence(bridge):
    """Use the real submission/approval bridge with an immutable nonempty snapshot."""
    actor = dict(actor_type="HUMAN", actor_id=str(bridge.user.id))
    now = timezone.now().isoformat()
    policy_id, evidence_id = str(uuid.uuid4()), uuid.uuid4()
    bodies = [b"Full synthetic requirement evidence", b"synthetic requirement"]
    references = [
        dict(object_id=str(uuid.uuid4()), digest=digest(raw), size_bytes=len(raw), media_type="text/plain")
        for raw in bodies
    ]
    source_ref = dict(resource_type="SOURCE_DOCUMENT", resource_id=str(uuid.uuid4()), resource_version=1)
    envelope = dict(
        schema_version="1.0",
        id=str(uuid.uuid4()),
        workspace_id=str(bridge.workspace.id),
        source_refs=[source_ref],
        effective_principal=actor,
        source_authorization_digest=digest(b"synthetic-evidence-grant"),
        classification="INTERNAL",
        allowed_audiences=["WORKSPACE_MEMBERS"],
        allowed_destinations=["PROTECTED_STORAGE"],
        retention_policy_ref=dict(resource_type="RETENTION_POLICY_VERSION", resource_id=policy_id),
        redaction_state="RAW",
        legal_hold=False,
        created_at=now,
    )
    record = dict(
        schema_version="1.0-candidate",
        id=str(evidence_id),
        workspace_id=str(bridge.workspace.id),
        created_at=now,
        version=1,
        source=dict(
            provider_connection_id=str(bridge.binding.provider_connection_id),
            resource_id="synthetic-evidence",
            resource_type="DOCUMENT",
            source_ref=source_ref,
        ),
        source_version="synthetic-evidence-v1",
        retrieved_at=now,
        effective_principal=actor,
        content=references[0],
        content_digest=references[0]["digest"],
        classification="INTERNAL",
        access_envelope=envelope,
        trust_flags=[],
        redaction_state="RAW",
        retention_policy_version_id=policy_id,
    )
    item = PrdEvidenceItemVersion.objects.create(
        evidence_id=evidence_id,
        workspace_id=bridge.workspace.id,
        version=1,
        provider_connection_id=bridge.binding.provider_connection_id,
        record=record,
    )
    entry = snapshot_entry(item)
    entry["selected_excerpt_ref"] = references[1]
    value = submission(bridge)
    bridge.runtime.capture[0].items = [entry]
    bridge.runtime.capture[0].digest = bridge.runtime.capture[0].compute_digest()
    operation = accept(bridge, value).operation
    result = complete(bridge, operation)
    assert result["status"] == "SUCCEEDED" and result["effect_applied"], result
    bridge.initiative.refresh_from_db()
    checkpoint = DocumentCheckpoint.objects.get(id=bridge.initiative.current_prd_checkpoint_id)
    bridge.runtime.capture = None
    bridge.runtime.records = (
        bridge.binding,
        bridge.initiative,
        checkpoint,
        bridge.gates[0],
        bridge.user,
        bridge.workspace,
    )
    bridge.manual_evidence = item
    bridge.manual_evidence_materials = list(zip(references, bodies))
    return ScopedPrdSubject.objects.get(checkpoint_id=checkpoint.id)


def write(root, name, raw):
    path = root / name
    path.write_bytes(raw)
    path.chmod(0o600)


def current_contexts(bridge, subject):
    return [
        require_scoped_current(
            workspace_id=bridge.workspace.id,
            initiative_id=bridge.initiative.id,
            actor_id=user.id,
            subject=subject,
        )
        for user in bridge.reviewers
    ]


def prepare_native_fixture(bridge, settings, tmp_path):
    subject = submit_with_retained_evidence(bridge)
    approved = accept(bridge, review_command(bridge, subject)).operation
    assert complete(bridge, approved)["status"] == "SUCCEEDED"
    bridge.initiative.refresh_from_db()
    settings.CURVE_MANUAL_PLAN_DRAFT_V2_ENABLED = True
    root = tmp_path / "protected"
    root.mkdir(mode=0o700)
    settings.CURVE_MANUAL_PLAN_V2_SYNTHETIC_ROOT = str(root)
    replacement = {
        "30000000-0000-4000-8000-000000000001": str(bridge.workspace.id),
        "30000000-0000-4000-8000-000000000002": str(bridge.initiative.id),
        "30000000-0000-4000-8000-000000000008": str(bridge.initiative.workflow_version_id),
        "30000000-0000-4000-8000-000000000024": str(bridge.user.id),
    }
    raw, identity, facts, sources, materials = semantic_case(replacement)
    definition = json.loads(raw)
    version = PrdArtifactVersion.objects.get(id=subject.payload["artifact_version_id"])
    prd_ref = version.as_record()["body"]
    prior_prd = sources["prd"]
    materials.pop(prior_prd["object_id"])
    materials[prd_ref["object_id"]] = bridge.runtime.body
    assert digest(bridge.runtime.body) == version.body_digest
    for item in identity["protected_inputs"]:
        if item["object_ref"] == prior_prd:
            item.update(
                object_ref=prd_ref,
                material_version_id=str(version.id),
                access_envelope_id=str(version.access_envelope_id),
            )
    sources["prd"] = prd_ref
    for reference, body in bridge.manual_evidence_materials:
        materials[reference["object_id"]] = body
        identity["protected_inputs"].append(
            dict(
                object_ref=reference,
                material_version_id=str(bridge.manual_evidence.row_id),
                access_envelope_id=bridge.manual_evidence.record["access_envelope"]["id"],
                classification="INTERNAL",
                input_kind="CONTEXT_INPUT",
            )
        )
    identity.update(
        prd_artifact_version_id=str(version.id),
        prd_content_digest=version.body_digest,
        evidence_snapshot_id=str(version.evidence_snapshot_id),
    )
    with transaction.atomic():
        contexts = current_contexts(bridge, subject)
        context = contexts[0]
        identity["gate_assignments"] = list(context.reviewers)
        identity["human_owner_ids"] = [str(bridge.user.id)]
        for key, value in {
            "approved_subject_ref": dict(entity_id=str(subject.id), digest=subject.digest),
            "scope_revision_ref": dict(entity_id=str(context.revision.id), digest=context.revision.membership_digest),
        }.items():
            identity[key] = definition[key] = facts[key] = value
        ledger = policy.prepare_native_catalog_authority(contexts)
    delivery = dict(
        provider_installation_id=str(bridge.association.provider_installation_id),
        source_issue_id=str(bridge.issue.id),
    )
    facts.update(
        initiative_key=bridge.initiative.keyword,
        requirement_ids=["FR-1"],
        acceptance_ids=["AC-1"],
        owner_ids=[str(bridge.user.id)],
        code_approver_id=str(bridge.reviewers[2].id),
        proposed_delivery_refs=[delivery],
        protected_object_refs=[deepcopy(item["object_ref"]) for item in identity["protected_inputs"]],
    )
    definition["slices"] = definition["slices"][:1]
    definition["dependencies"] = []
    definition["slices"][0].update(
        requirement_ids=["FR-1"],
        acceptance_ids=["AC-1"],
        proposed_delivery_refs=[delivery],
        branch_name=f"curve/{bridge.initiative.keyword}/alpha",
        owner=dict(actor_type="HUMAN", actor_id=str(bridge.user.id)),
        code_approver=dict(actor_type="HUMAN", actor_id=str(bridge.reviewers[2].id)),
    )
    raw = canonical_json(definition)
    identity["definition_ref"].update(digest=digest(raw), size_bytes=len(raw))
    identity["digest"] = metadata_digest(identity)
    materials[identity["definition_ref"]["object_id"]] = raw
    grants = [
        dict(
            principal_id=str(user.id), actions=sorted(synthetic.ACTIONS), acl_generation=1, classification_generation=1
        )
        for user in bridge.reviewers
    ]
    catalog = dict(
        schema_version="curve.synthetic-manual-plan-catalog/v2-candidate",
        generation=1,
        initiatives={
            str(bridge.initiative.id): dict(
                workspace_id=str(bridge.workspace.id),
                technical_contributor_ids=[],
                grants=deepcopy(grants),
                native_authority=ledger,
            )
        },
        plans={identity["definition_ref"]["object_id"]: dict(identity=identity, facts=facts, semantic_sources=sources)},
        objects={},
    )
    for item in [
        dict(
            object_ref=identity["definition_ref"],
            material_version_id=identity["definition_ref"]["object_id"],
            access_envelope_id=identity["definition_ref"]["object_id"],
            classification="INTERNAL",
        ),
        *identity["protected_inputs"],
    ]:
        catalog["objects"][item["object_ref"]["object_id"]] = dict(
            workspace_id=str(bridge.workspace.id),
            **{
                key: deepcopy(item[key])
                for key in ("object_ref", "material_version_id", "access_envelope_id", "classification")
            },
            grants=deepcopy(grants),
        )
    for object_id, body in materials.items():
        write(root, object_id, body)
    write(root, "catalog.json", canonical_json(catalog))
    bridge.manual_root, bridge.manual_catalog, bridge.manual_subject = root, catalog, subject
    bridge.manual_identity, bridge.manual_definition = identity, raw
    return bridge


def capture_native(bridge, *, action="SAVE"):
    with synthetic.SyntheticManualPlanResolverV2(str(bridge.manual_root)) as resolver, transaction.atomic():
        context, subject = policy.load_native(
            request=bridge.request,
            workspace_slug=bridge.workspace.slug,
            initiative_id=bridge.initiative.id,
        )
        captured = policy.capture_authorized(
            context=context,
            subject=subject,
            resolver=resolver,
            definition_ref=bridge.manual_identity["definition_ref"],
            action=action,
        )
        resolver.recheck(captured.file_fence)
        return captured


def publish_catalog(bridge, replacement):
    with synthetic.SyntheticManualPlanResolverV2(str(bridge.manual_root)) as resolver:
        resolver.publish_catalog(expected_digest=digest(canonical_json(bridge.manual_catalog)), replacement=replacement)
    bridge.manual_catalog = replacement
