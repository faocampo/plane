"""Manual Gate 2 transition kernel, outside the installed/qualified draft writer.

The future repository must lock guaranteed-existing native task rows in task_key
order, reconstruct this state, and atomically persist the returned delta with
policy/audit/event/outbox/idempotency. This pure kernel does no IO, authorizes no
HTTP caller, and grants no execution, spending, completion credit or dispatch.
"""

from dataclasses import dataclass, replace
import re
import uuid

from manual_plan_v2.contracts import validate
from manual_plan_v2.validation import canonical_json, digest, metadata_digest, parse_strict_json, validate_definition


class Gate2Denied(Exception):
    def __init__(self):
        super().__init__("Manual Gate 2 is unavailable for this command.")


def require(value):
    if not value:
        raise Gate2Denied()


def _id(value):
    try:
        require(type(value) is str and str(uuid.UUID(value)) == value)
        return value
    except (ValueError, TypeError, AttributeError):
        raise Gate2Denied() from None


def _digest(value):
    require(type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value))
    return value


def _generation(value):
    require(type(value) is int and 1 <= value <= 9007199254740991)
    return value


@dataclass(frozen=True, order=True)
class TaskKey:
    workspace_id: str
    installation_id: str
    issue_id: str

    def __post_init__(self):
        for value in (self.workspace_id, self.installation_id, self.issue_id):
            _id(value)


@dataclass(frozen=True)
class Subject:
    # Canonical immutable bytes keep caller-owned dictionaries out of state.
    metadata: bytes

    @property
    def data(self):
        return parse_strict_json(self.metadata)

    @property
    def digest(self):
        return digest(self.metadata)

    @property
    def tasks(self):
        return tuple(TaskKey(**item) for item in self.data["tasks"])


def prepare_subject(*, revision, identity, receipt, definition, facts, controlling_prd_decision_id):
    """Pre-lock preparation from verified draft plus freshly derived facts.

    Production must supply facts from derive_semantic_facts in the bounded Linux
    worker, and independently recheck retained DB rows/current native authority.
    This computation alone is not a qualified review-subject persistence path.
    """
    validate("manual-plan-draft-revision-v2", revision)
    validate("manual-plan-input-identity-v2", identity)
    validate("manual-plan-validation-receipt-v2", receipt)
    require(revision["digest"] == metadata_digest(revision))
    require(identity["digest"] == metadata_digest(identity))
    require(receipt == validate_definition(definition, identity, facts))
    require(identity["workspace_id"] == revision["workspace_id"])
    require(identity["initiative_id"] == revision["initiative_id"])
    for key in ("definition_ref", "approved_subject_ref", "manual_profile_ref"):
        require(revision[key] == identity[key])
    assignments = identity["gate_assignments"]
    require(tuple(item["gate_type"] for item in assignments) == ("CODE_READINESS", "PLAN_APPROVAL", "PRD_APPROVAL"))
    require(len({item["gate_assignment_id"] for item in assignments}) == 3)
    require(facts["risk_tier"] in {"LOW", "STANDARD", "HIGH"})
    # Existing HIGH-risk separation is stricter than native membership alone.
    if facts["risk_tier"] == "HIGH":
        require(len({item["approver_user_id"] for item in assignments}) == 3)
    tasks = tuple(
        TaskKey(revision["workspace_id"], item["provider_installation_id"], item["source_issue_id"])
        for item in facts["proposed_delivery_refs"]
    )
    require(tasks and tasks == tuple(sorted(set(tasks))))
    metadata = dict(
        edition="MANUAL_GATE2_TRANSITION_CANDIDATE_V1",
        workspace_id=revision["workspace_id"],
        product_id=revision["product_id"],
        initiative_id=revision["initiative_id"],
        draft_revision_id=revision["id"],
        draft_revision=revision["revision"],
        draft_digest=revision["digest"],
        input_identity=identity,
        validation_receipt_digest=receipt["digest"],
        validator_edition=receipt["validator_edition"],
        controlling_prd_decision_id=_id(controlling_prd_decision_id),
        risk_tier=facts["risk_tier"],
        semantic_facts_digest=digest(canonical_json(facts)),
        tasks=[
            dict(workspace_id=t.workspace_id, installation_id=t.installation_id, issue_id=t.issue_id) for t in tasks
        ],
    )
    return Subject(canonical_json(metadata))


@dataclass(frozen=True)
class CurrentAuthority:
    """Internal fresh adapter result; not a wire schema, token or retained grant."""

    actor_id: str
    workspace_id: str
    initiative_id: str
    current_technical_approver_id: str
    current_subject_digest: str
    material_readers: tuple[str, ...]
    accessible_tasks: tuple[TaskKey, ...]
    native_fence_digest: str
    human: bool = True
    lifecycle: str = "PLAN_REVIEW"


def _authorize(subject, authority, *, exact):
    require(type(subject) is Subject and type(authority) is CurrentAuthority)
    data = subject.data
    require(authority.human is True)
    require(_id(authority.actor_id) == _id(authority.current_technical_approver_id))
    require(authority.workspace_id == data["workspace_id"] and authority.initiative_id == data["initiative_id"])
    _digest(authority.native_fence_digest)
    identity = data["input_identity"]
    principals = {
        *identity["human_owner_ids"],
        *(item["approver_user_id"] for item in identity["gate_assignments"]),
        authority.actor_id,
    }
    require(principals <= set(authority.material_readers))
    require(set(subject.tasks) <= set(authority.accessible_tasks))
    if exact:
        require(authority.current_subject_digest == subject.digest)
        require(
            authority.actor_id
            == next(
                item["approver_user_id"]
                for item in identity["gate_assignments"]
                if item["gate_type"] == "PLAN_APPROVAL"
            )
        )


@dataclass(frozen=True)
class Claim:
    task: TaskKey
    generation: int
    initiative_id: str
    subject_digest: str
    state: str = "ACTIVE"


@dataclass(frozen=True)
class History:
    claim: Claim
    action: str
    actor_id: str | None
    cause_digest: str


@dataclass(frozen=True)
class Decision:
    workspace_id: str
    initiative_id: str
    actor_id: str
    key_digest: str
    request_digest: str
    action: str
    subject_digest: str
    claims: tuple[Claim, ...]


@dataclass(frozen=True)
class Ledger:
    claims: tuple[Claim, ...] = ()
    history: tuple[History, ...] = ()
    decisions: tuple[Decision, ...] = ()

    def __post_init__(self):
        require(len({c.task for c in self.claims}) == len(self.claims))
        for claim in self.claims:
            _generation(claim.generation)
            _id(claim.initiative_id)
            _digest(claim.subject_digest)
            require(claim.state in {"ACTIVE", "HELD", "RELEASED"})


@dataclass(frozen=True)
class Reconciliation:
    subject_digest: str
    claims: tuple[tuple[TaskKey, int], ...]
    native_fence_digest: str
    unresolved_work: tuple[TaskKey, ...]
    rationale_digest: str


def reconcile(*, ledger, subject, authority, exact_claims, unresolved_work, rationale_digest):
    _authorize(subject, authority, exact=False)
    require(authority.lifecycle in {"PLAN_REVIEW", "MANUAL_APPROVED", "PAUSED", "CANCELLED"})
    selected = tuple(exact_claims)
    require(selected and selected == tuple(sorted(set(selected))))
    claims = {c.task: c for c in ledger.claims}
    for task, generation in selected:
        claim = claims.get(task)
        require(claim is not None and claim.generation == _generation(generation))
        require(claim.initiative_id == subject.data["initiative_id"] and claim.subject_digest == subject.digest)
        require(claim.state in {"ACTIVE", "HELD"})
    require(not unresolved_work)
    return Reconciliation(subject.digest, selected, authority.native_fence_digest, (), _digest(rationale_digest))


def transition(*, ledger, subject, authority, action, idempotency_key, rationale_digest, reconciliation=None):
    """All-or-none pure transition. Caller must persist *all* delta atomically.

    No state is mutated in place. Replay reauthorizes before returning its original
    decision and leaves even subsequently released/reacquired claims unchanged.
    """
    require(type(ledger) is Ledger and action in {"APPROVE", "REQUEST_CHANGES", "RELEASE"})
    _authorize(subject, authority, exact=action != "RELEASE")
    require(
        type(idempotency_key) is str
        and 1 <= len(idempotency_key) <= 500
        and all(32 <= ord(c) <= 126 for c in idempotency_key)
    )
    _digest(rationale_digest)
    require((action == "RELEASE") == (type(reconciliation) is Reconciliation))
    reconciliation_data = None
    if reconciliation is not None:
        require(reconciliation.subject_digest == subject.digest)
        require(
            reconciliation.native_fence_digest == authority.native_fence_digest and not reconciliation.unresolved_work
        )
        reconciliation_data = dict(
            claims=[[t.workspace_id, t.installation_id, t.issue_id, g] for t, g in reconciliation.claims],
            native_fence_digest=reconciliation.native_fence_digest,
            rationale_digest=reconciliation.rationale_digest,
        )
        require(reconciliation.rationale_digest == rationale_digest)
    key = digest(idempotency_key.encode("ascii"))
    request = digest(
        canonical_json(
            dict(action=action, subject=subject.digest, rationale=rationale_digest, reconciliation=reconciliation_data)
        )
    )
    data = subject.data
    for prior in ledger.decisions:
        if (prior.workspace_id, prior.initiative_id, prior.actor_id, prior.key_digest) == (
            data["workspace_id"],
            data["initiative_id"],
            authority.actor_id,
            key,
        ):
            require(prior.request_digest == request)
            return ledger, prior, True
    # A retained approval is never an execution/lifecycle authorization.
    if action != "RELEASE":
        require(authority.lifecycle == "PLAN_REVIEW")
        require(not any(d.subject_digest == subject.digest for d in ledger.decisions))
    claims = {claim.task: claim for claim in ledger.claims}
    selected = []
    if action == "APPROVE":
        for task in subject.tasks:
            previous = claims.get(task)
            require(previous is None or previous.state == "RELEASED")
            selected.append(
                Claim(
                    task,
                    _generation(1 if previous is None else previous.generation + 1),
                    data["initiative_id"],
                    subject.digest,
                )
            )
    elif action == "RELEASE":
        require(authority.lifecycle in {"PLAN_REVIEW", "MANUAL_APPROVED", "PAUSED", "CANCELLED"})
        require(reconciliation.claims and reconciliation.claims == tuple(sorted(set(reconciliation.claims))))
        for task, generation in reconciliation.claims:
            previous = claims.get(task)
            require(previous is not None and previous.generation == generation)
            require(
                previous.initiative_id == data["initiative_id"]
                and previous.subject_digest == subject.digest
                and previous.state in {"ACTIVE", "HELD"}
            )
            selected.append(replace(previous, state="RELEASED"))
    for claim in selected:
        claims[claim.task] = claim
    decision = Decision(
        data["workspace_id"],
        data["initiative_id"],
        authority.actor_id,
        key,
        request,
        action,
        subject.digest,
        tuple(selected),
    )
    history = tuple(History(c, action, authority.actor_id, request) for c in selected)
    return (
        Ledger(tuple(claims[t] for t in sorted(claims)), ledger.history + history, ledger.decisions + (decision,)),
        decision,
        False,
    )


def hold(*, ledger, initiative_id, cause, cause_digest):
    """Trusted native pause/cancel/access-loss observation; can only retain control."""
    _id(initiative_id)
    require(cause in {"PAUSED", "CANCELLED", "ACCESS_LOST"})
    _digest(cause_digest)
    held = tuple(
        replace(c, state="HELD") for c in ledger.claims if c.initiative_id == initiative_id and c.state == "ACTIVE"
    )
    replacements = {c.task: c for c in held}
    return Ledger(
        tuple(replacements.get(c.task, c) for c in ledger.claims),
        ledger.history + tuple(History(c, cause, None, cause_digest) for c in held),
        ledger.decisions,
    )
