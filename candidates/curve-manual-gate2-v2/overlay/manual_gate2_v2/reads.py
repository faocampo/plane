"""Freshly authorized preparation and manual-control projections; no cached grants."""

from types import SimpleNamespace
from django.db import transaction
from plane.curve.manual_plan_v2 import policy as draft_policy
from plane.curve.manual_plan_v2.contracts import POLICY_EDITION, ManualPlanError
from plane.curve.manual_plan_v2.repository import load_head, load_revision
from plane.curve.manual_plan_v2.synthetic import SyntheticManualPlanResolverV2
from plane.curve.manual_plan_v2.validation import parse_strict_json
from . import policy, repository as repo
from .contracts import Gate2Error, project_record, require, validate


def preparation(*, request, slug, initiative_id):
    try:
        policy.require_enabled(request, slug)
        require(not request.query_params)
        with (
            SyntheticManualPlanResolverV2.from_settings() as resolver,
            transaction.atomic(),
        ):
            policy.require_edition()
            context, subject = draft_policy.load_native(
                request=request, workspace_slug=slug, initiative_id=initiative_id
            )
            control = repo.load_control(context.initiative)
            require(control is None or control.approved_record_id is None)
            head, _ = load_head(context.initiative)
            catalog, _, _, fence = resolver.authorize(
                workspace_id=context.workspace.id,
                initiative_id=initiative_id,
                principals=draft_policy._principals(context),
                action="SAVE",
            )
            plans, fences = [], [fence]
            for item in catalog["plans"].values():
                identity = item["identity"]
                if identity["workspace_id"] != str(context.workspace.id) or identity["initiative_id"] != str(
                    initiative_id
                ):
                    continue
                try:
                    captured = draft_policy.capture_authorized(
                        context=context,
                        subject=subject,
                        resolver=resolver,
                        definition_ref=identity["definition_ref"],
                        action="SAVE",
                    )
                    require(
                        context.initiative.creator_user_id == context.actor_id
                        or str(context.actor_id) in captured.technical_contributor_ids
                    )
                except (ManualPlanError, Gate2Error):
                    continue
                plans.append(
                    dict(
                        payload=dict(
                            schema_version="curve.manual-plan-draft.save/v2-candidate",
                            policy_edition=POLICY_EDITION,
                            expected_draft_revision=0 if head is None else head.version,
                            **{
                                k: identity[k]
                                for k in (
                                    "approved_subject_ref",
                                    "definition_ref",
                                    "manual_profile_ref",
                                )
                            },
                        )
                    )
                )
                fences.extend(captured.file_fence)
                require(len(plans) <= 25)
            data = dict(
                schema_version="curve.manual-plan.preparation/v2-candidate",
                workspace_id=str(context.workspace.id),
                product_id=str(context.product.id),
                initiative_id=str(initiative_id),
                initiative_version=context.initiative.version,
                plans=plans,
            )
            validate("preparation", data)
            resolver.recheck(tuple(fences))
            return repo.Result(data, context.initiative.version)
    except Gate2Error:
        raise
    except Exception:
        raise Gate2Error() from None


def _rationales(authority, resolver, revision):
    catalog, _, _, fence = resolver.authorize(
        workspace_id=authority.context.workspace.id,
        initiative_id=authority.context.initiative.id,
        principals=authority.principals,
        action="READ_REVISION",
    )
    values, fences = [], [fence]
    for item in catalog["objects"].values():
        ref = item["object_ref"]
        if (
            item["workspace_id"] != str(authority.context.workspace.id)
            or ref["media_type"] != "application/json"
            or ref["size_bytes"] > 16384
        ):
            continue
        try:
            raw, object_fence, _ = resolver.read_material(
                catalog=catalog,
                workspace_id=authority.context.workspace.id,
                reference=ref,
                principals=authority.principals,
                action="READ_REVISION",
            )
            body = parse_strict_json(raw, max_bytes=16384)
            if body.get("schema_version") != "curve.manual-gate2.rationale/v2-candidate":
                continue
            validate("rationale", body)
            if body["draft_revision_id"] != str(revision.id):
                continue
            command = SimpleNamespace(
                action=body["intent"],
                payload=dict(rationale_ref=ref, draft_revision_id=str(revision.id)),
            )
            checked, _ = policy.read_rationale(authority, resolver, command)
        except Exception:
            continue
        values.append(dict(reference=ref, intent=body["intent"]))
        fences.extend((object_fence, *checked))
        require(len(values) <= 100)
    return values, fences


def status(*, request, slug, initiative_id):
    from plane.db.models import Workspace
    from plane.curve.models import Initiative
    from .domain import Subject
    from plane.curve.manual_plan_v2.validation import canonical_json

    try:
        policy.require_enabled(request, slug)
        require(not request.query_params)
        with (
            SyntheticManualPlanResolverV2.from_settings() as resolver,
            transaction.atomic(),
        ):
            policy.require_edition()
            workspace = Workspace.objects.select_for_update().filter(slug=slug).first()
            require(workspace is not None)
            initiative = Initiative.objects.find_by_id(
                workspace_id=workspace.id, record_id=initiative_id, for_update=True
            )
            require(initiative is not None)
            control = repo.load_control(initiative)
            head, current_draft = load_head(initiative)
            require(head is not None)
            original = repo.load_record(initiative, control.subject_id) if control is not None else None
            approved = control is not None and control.approved_record_id is not None
            revision = load_revision(initiative, head, original.draft_revision_id) if approved else current_draft
            authority = policy.load_authority(
                request=request,
                slug=slug,
                revision=revision,
                resolver=resolver,
                action="READ_RELEASE" if control is not None and control.approved_record_id is not None else "READ",
            )
            record = repo.load_record(initiative, control.current_record_id) if control is not None else None
            claims = []
            if approved:
                subject = Subject(canonical_json(original.payload["subject_metadata"]))
                require(
                    subject.digest == original.subject_digest
                    and subject.data["controlling_prd_decision_id"] == str(initiative.controlling_prd_decision_id)
                )
                rows = repo.lock_claims(initiative, subject)
                for row in rows.values():
                    if row.initiative_id == initiative.id and row.subject_id == original.id:
                        claims.append(repo.ManualTaskClaimHistoryV2.objects.get(id=row.current_history_id).payload)
            actions = []
            is_technical = str(request.user.id) == next(
                x["approver_user_id"] for x in authority.context.reviewers if x["gate_type"] == "PLAN_APPROVAL"
            )
            if control is None or (
                control.state in {"PLAN_REVIEW", "CHANGES_REQUESTED"} and current_draft.id != original.draft_revision_id
            ):
                if (
                    initiative.creator_user_id == request.user.id
                    or str(request.user.id) in authority.captured.technical_contributor_ids
                ):
                    actions = ["PREPARE"]
            elif control.state == "PLAN_REVIEW" and current_draft.id == original.draft_revision_id and is_technical:
                actions = ["APPROVE", "REQUEST_CHANGES"]
            elif control.state == "MANUAL_APPROVED" and is_technical:
                actions = ["RECONCILE", "RELEASE"]
            rationales, fences = _rationales(authority, resolver, revision)
            data = dict(
                schema_version="curve.manual-gate2.status/v2-candidate",
                workspace_id=str(workspace.id),
                product_id=str(initiative.product_id),
                initiative_id=str(initiative.id),
                initiative_version=initiative.version,
                state="ABSENT" if control is None else control.state,
                effective_hold=initiative.state if initiative.state in {"PAUSED", "CANCELLED"} else None,
                current_record=None if record is None else project_record(record),
                subject_ref=None
                if original is None
                else dict(entity_id=str(original.id), digest=original.subject_digest),
                draft_revision_id=str(current_draft.id if "PREPARE" in actions else revision.id),
                claims=sorted(claims, key=lambda x: x["claim_id"]),
                allowed_actions=actions,
                rationales=rationales,
                execution_authorized=False,
                completion_credit=False,
            )
            data["definition_ref"] = revision.payload["definition_ref"]
            validate("status", data)
            resolver.recheck((*authority.file_fence, *fences))
            return repo.Result(data, initiative.version)
    except Gate2Error:
        raise
    except Exception:
        raise Gate2Error() from None


def material(*, request, slug, initiative_id, object_id):
    """Read one original definition or bound rationale through its original grants."""
    from plane.db.models import Workspace
    from plane.curve.models import Initiative

    try:
        policy.require_enabled(request, slug)
        require(not request.query_params)
        with SyntheticManualPlanResolverV2.from_settings() as resolver, transaction.atomic():
            policy.require_edition()
            workspace = Workspace.objects.select_for_update().filter(slug=slug).first()
            require(workspace is not None)
            initiative = Initiative.objects.find_by_id(
                workspace_id=workspace.id, record_id=initiative_id, for_update=True
            )
            require(initiative is not None)
            control = repo.load_control(initiative)
            head, revision = load_head(initiative)
            approved = control is not None and control.approved_record_id is not None
            if approved:
                original = repo.load_record(initiative, control.subject_id)
                revision = load_revision(initiative, head, original.draft_revision_id)
            # A creator may inspect a newly prepared replacement before saving it.
            # It must pass fresh SAVE authority, never borrow the current draft's grants.
            prepared = None
            if not approved and (revision is None or str(object_id) != revision.payload["definition_ref"]["object_id"]):
                try:
                    prepared = _prepared_definition(request, slug, initiative_id, object_id, resolver)
                except (ManualPlanError, Gate2Error):
                    pass
            if prepared is not None:
                reference, raw, fences, kind = prepared
            elif revision is None:
                raise Gate2Error()
            else:
                authority = policy.load_authority(
                    request=request,
                    slug=slug,
                    revision=revision,
                    resolver=resolver,
                    action="READ_RELEASE" if approved else "READ",
                )
                if str(object_id) == revision.payload["definition_ref"]["object_id"]:
                    reference, raw, fences, kind = (
                        revision.payload["definition_ref"],
                        authority.captured.definition,
                        authority.file_fence,
                        "DEFINITION",
                    )
                else:
                    rationales, fences = _rationales(authority, resolver, revision)
                    selected = [x for x in rationales if x["reference"]["object_id"] == str(object_id)]
                    require(len(selected) == 1)
                    reference = selected[0]["reference"]
                    catalog, _, _, catalog_fence = resolver.authorize(
                        workspace_id=workspace.id,
                        initiative_id=initiative_id,
                        principals=authority.principals,
                        action="READ_REVISION",
                    )
                    raw, object_fence, _ = resolver.read_material(
                        catalog=catalog,
                        workspace_id=workspace.id,
                        reference=reference,
                        principals=authority.principals,
                        action="READ_REVISION",
                    )
                    fences = (*authority.file_fence, *fences, catalog_fence, object_fence)
                    kind = "RATIONALE"
            data = dict(
                schema_version="curve.manual-gate2.material/v2-candidate",
                workspace_id=str(workspace.id),
                product_id=str(initiative.product_id),
                initiative_id=str(initiative.id),
                initiative_version=initiative.version,
                kind=kind,
                reference=reference,
                content=raw.decode("utf-8", "strict"),
            )
            validate("material", data)
            resolver.recheck(tuple(fences))
            return repo.Result(data, initiative.version)
    except Gate2Error:
        raise
    except Exception:
        raise Gate2Error() from None


def _prepared_definition(request, slug, initiative_id, object_id, resolver):
    context, subject = draft_policy.load_native(request=request, workspace_slug=slug, initiative_id=initiative_id)
    catalog, _, _, _ = resolver.authorize(
        workspace_id=context.workspace.id,
        initiative_id=initiative_id,
        principals=draft_policy._principals(context),
        action="SAVE",
    )
    plan = catalog["plans"].get(str(object_id))
    require(plan is not None and plan["identity"]["initiative_id"] == str(initiative_id))
    captured = draft_policy.capture_authorized(
        context=context,
        subject=subject,
        resolver=resolver,
        definition_ref=plan["identity"]["definition_ref"],
        action="SAVE",
    )
    require(
        context.initiative.creator_user_id == context.actor_id
        or str(context.actor_id) in captured.technical_contributor_ids
    )
    return (
        captured.identity["definition_ref"],
        captured.definition,
        captured.file_fence,
        "DEFINITION",
    )
