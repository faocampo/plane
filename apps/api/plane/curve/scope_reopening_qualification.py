# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Server-owned pre-plan compatibility proof, independent of feature switches."""

import hashlib
import json
import re
from importlib import import_module
from pathlib import Path

from django.apps import apps
from django.db import connection, transaction

from .prd_commands import PrdCommandError
from .scope_reopening_contracts import require_reopening_contract_integrity

# Finalized only after the successor migration and exact model catalog are tested.
QUALIFICATION_DIGEST = "sha256:72bdb3b987ec1925754e6a14dee36cecec3c85706605c052d443628d84e7fb52"
QUALIFICATION_PATH = Path(__file__).parent / "scope_reopening_qualification.json"
# Reviewed read-only successor. The original C2b proof remains byte-immutable.
READ_SUCCESSOR_DIGEST = "sha256:5381243df882c087ab61932cda77e286a76b3b3e4b19853be5eea9cc81574f1b"
READ_SUCCESSOR_PATH = Path(__file__).parent / "project_association_read_qualification.json"
_READ_ADDED_MODULES = frozenset({"project_association_read.py", "project_association_read_views.py"})
_READ_REPLACED_MODULES = frozenset({"urls.py"})


# Unapproved successor pins: these remain unset until real PostgreSQL review.
MANUAL_SUCCESSOR_DIGEST = "sha256:b4f16de1a78f0ffb7f62df770f6fe2e50636da3961e22bb193ba5e914b87215b"
MANUAL_SUCCESSOR_PATH = Path(__file__).parent / "manual_plan_draft_reconstruction_qualification_v2.json"
SCOPE_EDITOR_SUCCESSOR_DIGEST = "sha256:c2e37caa561e943bf4f2883c62d8ed889c74a55809fa1f5ffc93aed5d4ce093e"
SCOPE_EDITOR_SUCCESSOR_PATH = Path(__file__).parent / "scope_editor_read_reconstruction_qualification_v2.json"
GATE2_SUCCESSOR_DIGEST = "sha256:34661219609b64ae715466aa7a20f756eb85a17365f30a3ab0d25a926f28c8ec"
GATE2_SUCCESSOR_PATH = Path(__file__).parent / "manual_gate2_reconstruction_qualification_v2.json"
HEADER_SUCCESSOR_DIGEST = "sha256:a4086b8d08f918b187b623e56b9d810f2d0834ce723fe120297710db02d6352d"
HEADER_SUCCESSOR_PATH = Path(__file__).parent / "source_header_qualification_v1.json"
TWO_STAGE_SUCCESSOR_DIGEST = "sha256:f3dbfa241f6902232d44c1dddc5f96184aaf1307738533c15eeebbd2d80006bd"
TWO_STAGE_SUCCESSOR_PATH = Path(__file__).parent / "two_stage_review/runtime-qualification-v1.json"
REVIEW_READ_SUCCESSOR_DIGEST = "sha256:0d0abd1dfc62b987f8a85e68b620934f4d51167dc0f9dae812cb392cf91c88f6"
REVIEW_READ_SUCCESSOR_PATH = Path(__file__).parent / "two_stage_review/review-read-qualification-v1.json"
_REVIEW_READ_REPLACED_MODULES = frozenset({"local_prd_review_views.py", "local_plan_review_views.py"})
_TWO_STAGE_ADDED_MODULES = frozenset(
    [
        "local_document_store.py",
        "local_document_capture.py",
        "local_document_record.py",
        "local_document_models.py",
        "local_document_authority.py",
        "local_initiative_context.py",
        "local_prd_new_work.py",
        "local_new_work_policy.py",
        "local_document_policy.py",
        "local_document_services.py",
        "local_document_views.py",
        "local_prd_review.py",
        "local_prd_reopening.py",
        "local_prd_reopening_models.py",
        "local_prd_reopening_authority.py",
        "local_prd_reopening_services.py",
        "local_prd_reopening_views.py",
        "local_prd_review_models.py",
        "local_prd_review_authority.py",
        "local_prd_review_policy.py",
        "local_prd_review_services.py",
        "local_prd_review_views.py",
        "local_plan_review.py",
        "local_plan_authority.py",
        "local_plan_models.py",
        "local_plan_policy.py",
        "local_plan_services.py",
        "local_plan_views.py",
        "local_plan_review_policy.py",
        "local_plan_review_services.py",
        "local_plan_review_views.py",
        "manual_gate2_v3/__init__.py",
        "manual_gate2_v3/domain.py",
        "manual_gate2_v3/contracts.py",
        "manual_gate2_v3/policy.py",
        "manual_gate2_v3/repository.py",
        "manual_gate2_v3/services.py",
        "manual_gate2_v3/reads.py",
        "manual_gate2_v3/views.py",
        "manual_plan_v3/__init__.py",
        "manual_plan_v3/contracts.py",
        "manual_plan_v3/policy.py",
        "manual_plan_v3/reads.py",
        "manual_plan_v3/repository.py",
        "manual_plan_v3/services.py",
        "manual_plan_v3/synthetic.py",
        "manual_plan_v3/validation.py",
        "manual_plan_v3/validator_worker.py",
        "manual_plan_v3/views.py",
        "scoped_prd_editions.py",
        "scoped_prd_v2_contracts.py",
        "two_stage_review/__init__.py",
    ]
)
_TWO_STAGE_REPLACED_MODULES = frozenset(
    [
        "manual_gate2_v2/models.py",
        "manual_gate2_v2/repository.py",
        "initiative_policy.py",
        "initiative_serialization.py",
        "initiative_services.py",
        "manual_plan_v2/models.py",
        "manual_plan_v2/synthetic.py",
        "manual_plan_v2/validation.py",
        "models.py",
        "policy_evaluator.py",
        "policy_manifest.py",
        "policy_services.py",
        "prd_policy_context.py",
        "prd_review_validation.py",
        "request_privacy.py",
        "scoped_prd_acceptance.py",
        "scoped_prd_commands.py",
        "scoped_prd_completion.py",
        "scoped_prd_contracts.py",
        "scoped_prd_models.py",
        "scoped_prd_observations.py",
        "scoped_prd_policy.py",
        "scoped_prd_read.py",
        "scoped_prd_repository.py",
        "scoped_prd_views.py",
        "services.py",
        "temporal/scoped_prd_relay.py",
        "urls.py",
    ]
)
_TWO_STAGE_MIGRATIONS = frozenset(
    {
        "0026_two_stage_approval_policy.py",
        "0027_scoped_prd_two_stage.py",
        "0028_manual_plan_two_stage.py",
        "0029_technical_review_two_stage.py",
        "0030_local_prd_source.py",
        "0031_local_prd_command.py",
        "0032_local_prd_review.py",
        "0033_local_prd_lifecycle.py",
        "0034_local_review_commands.py",
        "0035_local_plan_revision.py",
        "0036_local_plan_upload.py",
        "0037_local_plan_review_records.py",
        "0038_local_plan_review_commands.py",
        "0039_local_prd_reopening.py",
        "0040_local_prd_reopening_lifecycle.py",
        "0041_local_prd_reopening_command.py",
        "0042_local_new_work_review.py",
    }
)
_TWO_STAGE_WRITERS = [
    "TWO_STAGE_INITIATIVE_1_2",
    "SCOPED_PRD_GATE1_V2",
    "MANUAL_PLAN_DRAFT_V3",
    "MANUAL_GATE2_V3",
    "LOCAL_PRD_SOURCE_V1",
    "LOCAL_PRD_UPLOAD_COMMAND_V1",
    "LOCAL_PRD_REVIEW_RECORDS_V1",
    "LOCAL_PRD_LIFECYCLE_V1",
    "LOCAL_PRD_REVIEW_COMMAND_V1",
    "LOCAL_PLAN_REVISION_V1",
    "LOCAL_PLAN_UPLOAD_V1",
    "LOCAL_PLAN_REVIEW_RECORDS_V1",
    "LOCAL_PLAN_REVIEW_COMMANDS_V1",
    "LOCAL_PRD_REOPENING_RECORDS_V1",
    "LOCAL_PRD_REOPENING_LIFECYCLE_V1",
    "LOCAL_PRD_REOPENING_COMMAND_V1",
    "LOCAL_NEW_INITIATIVE_DOCUMENT_REVIEW_V2",
]
_LOCAL_PRD_ADDED_MODELS = [
    {
        "model_name": "localprdreopening",
        "db_table": "curve_local_prd_reopening",
        "columns": [
            "decision_id",
            "digest",
            "id",
            "initiative_id",
            "initiative_version",
            "payload",
            "submission_id",
            "workspace_id",
        ],
    },
    {
        "model_name": "localplansubmission",
        "db_table": "curve_local_plan_submission",
        "columns": [
            "digest",
            "id",
            "initiative_id",
            "initiative_version",
            "payload",
            "plan_revision_id",
            "workspace_id",
        ],
    },
    {
        "model_name": "localplandecision",
        "db_table": "curve_local_plan_decision",
        "columns": [
            "digest",
            "id",
            "initiative_id",
            "initiative_version",
            "payload",
            "plan_submission_id",
            "state",
            "workspace_id",
        ],
    },
    {
        "model_name": "localplanrevision",
        "db_table": "curve_local_plan_revision",
        "columns": [
            "digest",
            "id",
            "initiative_id",
            "initiative_version",
            "payload",
            "prd_decision_id",
            "prd_submission_id",
            "predecessor_id",
            "version",
            "workspace_id",
        ],
    },
    {
        "model_name": "localprdsubmission",
        "db_table": "curve_local_prd_submission",
        "columns": ["digest", "id", "initiative_id", "initiative_version", "payload", "source_id", "workspace_id"],
    },
    {
        "model_name": "localprddecision",
        "db_table": "curve_local_prd_decision",
        "columns": [
            "digest",
            "id",
            "initiative_id",
            "initiative_version",
            "payload",
            "state",
            "submission_id",
            "workspace_id",
        ],
    },
] + [
    {
        "model_name": "localprdsource",
        "db_table": "curve_local_prd_source",
        "columns": [
            "digest",
            "id",
            "initiative_id",
            "payload",
            "predecessor_id",
            "uploaded_by",
            "version",
            "workspace_id",
        ],
    }
]
SOURCE_HEADER = (
    b"# Copyright (c) 2023-present Plane Software, Inc. and contributors\n"
    b"# SPDX-License-Identifier: AGPL-3.0-only\n"
    b"# See the LICENSE file for details.\n"
)
_GATE2_ADDED_MODULES = frozenset(
    [
        "manual_gate2_v2/__init__.py",
        "manual_gate2_v2/contracts.py",
        "manual_gate2_v2/domain.py",
        "manual_gate2_v2/models.py",
        "manual_gate2_v2/policy.py",
        "manual_gate2_v2/reads.py",
        "manual_gate2_v2/repository.py",
        "manual_gate2_v2/services.py",
        "manual_gate2_v2/views.py",
    ]
)
_GATE2_ADDED_MODELS = [
    {
        "model_name": "manualgate2controlv2",
        "db_table": "curve_manual_gate2_control_v2",
        "columns": [
            "approved_record_id",
            "current_record_id",
            "id",
            "initiative_id",
            "product_id",
            "state",
            "subject_id",
            "version",
            "workspace_id",
        ],
    },
    {
        "model_name": "manualgate2recordv2",
        "db_table": "curve_manual_gate2_record_v2",
        "columns": [
            "action",
            "command_receipt_id",
            "control_id",
            "created_by",
            "digest",
            "draft_revision_id",
            "id",
            "initiative_id",
            "initiative_version",
            "payload",
            "policy_decision_id",
            "predecessor_id",
            "product_id",
            "recorded_at",
            "request_digest",
            "request_payload",
            "subject_digest",
            "subject_id",
            "version",
            "workspace_id",
        ],
    },
    {
        "model_name": "manualtaskclaimhistoryv2",
        "db_table": "curve_manual_task_claim_history_v2",
        "columns": ["claim_id", "generation", "id", "initiative_id", "payload", "record_id", "state", "workspace_id"],
    },
    {
        "model_name": "manualtaskclaimv2",
        "db_table": "curve_manual_task_claim_v2",
        "columns": [
            "current_history_id",
            "current_record_id",
            "generation",
            "id",
            "initiative_id",
            "installation_id",
            "issue_id",
            "state",
            "subject_id",
            "workspace_id",
        ],
    },
]

_MANUAL_EDITION = "CURVE_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2"
_MANUAL_WRITER = "MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2"
_MANUAL_MIGRATION = "0024_manual_draft_reconstruction.py"
_MANUAL_ADDED_MODULES = frozenset(
    [
        "manual_plan_v2/__init__.py",
        "manual_plan_v2/contracts.py",
        "manual_plan_v2/models.py",
        "manual_plan_v2/repository.py",
        "manual_plan_v2/policy.py",
        "manual_plan_v2/services.py",
        "manual_plan_v2/reads.py",
        "manual_plan_v2/views.py",
        "manual_plan_v2/validation.py",
        "manual_plan_v2/validator_worker.py",
        "manual_plan_v2/synthetic.py",
    ]
)
_MANUAL_REPLACED_MODULES = frozenset({"models.py", "urls.py"})
_MANUAL_ADDED_MODELS = [
    {
        "model_name": "manualplandraftv2",
        "db_table": "curve_manual_plan_draft_v2",
        "columns": ["current_revision_id", "id", "initiative_id", "product_id", "version", "workspace_id"],
    },
    {
        "model_name": "manualplanrevisionv2",
        "db_table": "curve_manual_plan_revision_v2",
        "columns": [
            "command_receipt_id",
            "created_by",
            "digest",
            "draft_id",
            "id",
            "initiative_id",
            "initiative_version",
            "input_identity_digest",
            "original_input_identity",
            "payload",
            "policy_decision_id",
            "predecessor_id",
            "product_id",
            "recorded_at",
            "validation_receipt",
            "validation_receipt_digest",
            "version",
            "workspace_id",
        ],
    },
]
_SCOPE_EDITOR_ADDED_MODULES = frozenset({"scope_editor_read_v2.py", "scope_editor_read_views_v2.py"})


def _hashes(values):
    return type(values) is dict and all(
        type(key) is str and type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value)
        for key, value in values.items()
    )


def _validate_source_delta(old, new, added, replaced):
    if (
        not _hashes(new)
        or set(new) - set(old) != added
        or set(old) - set(new)
        or {key for key in old if old[key] != new[key]} != replaced
    ):
        raise ValueError("Unexpected successor source delta")


def validate_manual_successor(predecessor, successor):
    """Structural delta review only. This function alone never grants authority."""
    required = {"schema_version", "predecessor_digest", "writer_edition", "qualification"}
    if (
        type(successor) is not dict
        or set(successor) != required
        or successor["schema_version"] != "curve.manual-plan-draft-reconstruction-qualification/v2-candidate"
        or successor["predecessor_digest"] != READ_SUCCESSOR_DIGEST
        or successor["writer_edition"] != _MANUAL_WRITER
    ):
        raise ValueError("Wrong manual successor identity")
    qualified = successor["qualification"]
    if type(qualified) is not dict or set(qualified) != set(predecessor):
        raise ValueError("Wrong qualification shape")
    unchanged = {"schema_version", "excluded_writers"}
    if any(qualified[key] != predecessor[key] for key in unchanged):
        raise ValueError("Historical exclusions changed")
    if (
        qualified["model_edition"] != _MANUAL_EDITION
        or qualified["runtime_writer_inventory"] != predecessor["runtime_writer_inventory"] + [_MANUAL_WRITER]
        or qualified["models"]
        != sorted(predecessor["models"] + _MANUAL_ADDED_MODELS, key=lambda row: row["model_name"])
    ):
        raise ValueError("Unexpected writer or model delta")
    old, new = predecessor["migration_digests"], qualified["migration_digests"]
    if not _hashes(new) or set(new) - set(old) != {_MANUAL_MIGRATION} or any(new.get(k) != v for k, v in old.items()):
        raise ValueError("Historical migration changed")
    _validate_source_delta(
        predecessor["runtime_sources"], qualified["runtime_sources"], _MANUAL_ADDED_MODULES, _MANUAL_REPLACED_MODULES
    )
    if (
        type(qualified["physical_catalog_digest"]) is not str
        or re.fullmatch(r"sha256:[0-9a-f]{64}", qualified["physical_catalog_digest"]) is None
        or qualified["physical_catalog_digest"] == predecessor["physical_catalog_digest"]
    ):
        raise ValueError("A reviewed new physical catalog is required")
    return qualified


def validate_scope_editor_successor(predecessor, successor, manual_proof_digest):
    required = {"schema_version", "predecessor_digest", "read_edition", "qualification"}
    if (
        predecessor["model_edition"] != _MANUAL_EDITION
        or type(successor) is not dict
        or set(successor) != required
        or successor["schema_version"] != "curve.scope-editor-read-reconstruction-qualification/v2-candidate"
        or successor["predecessor_digest"] != manual_proof_digest
        or successor["read_edition"] != "LOCAL_SCOPE_EDITOR_PRECONDITION_RECONSTRUCTION_V2"
    ):
        raise ValueError("Wrong scope editor successor identity")
    qualified = successor["qualification"]
    if (
        type(qualified) is not dict
        or set(qualified) != set(predecessor)
        or any(qualified[key] != value for key, value in predecessor.items() if key != "runtime_sources")
    ):
        raise ValueError("A read successor cannot change writers or storage")
    _validate_source_delta(
        predecessor["runtime_sources"],
        qualified["runtime_sources"],
        _SCOPE_EDITOR_ADDED_MODULES,
        frozenset({"urls.py"}),
    )
    return qualified


def validate_gate2_successor(predecessor, successor):
    if (
        type(successor) is not dict
        or set(successor) != {"schema_version", "predecessor_digest", "writer_edition", "qualification"}
        or successor["schema_version"] != "curve.manual-gate2-reconstruction-qualification/v2-candidate"
        or successor["predecessor_digest"] != SCOPE_EDITOR_SUCCESSOR_DIGEST
        or successor["writer_edition"] != "MANUAL_GATE2_RECONSTRUCTION_V2"
    ):
        raise ValueError("Wrong manual Gate 2 successor")
    q = successor["qualification"]
    if (
        type(q) is not dict
        or set(q) != set(predecessor)
        or q["schema_version"] != predecessor["schema_version"]
        or q["model_edition"] != "CURVE_MANUAL_GATE2_RECONSTRUCTION_V2"
        or q["runtime_writer_inventory"] != predecessor["runtime_writer_inventory"] + ["MANUAL_GATE2_RECONSTRUCTION_V2"]
        or predecessor["excluded_writers"]
        != ["PLAN_APPROVAL", "CONTROLLING_WORK_BINDING", "EXECUTION", "COMPLETION_CREDIT"]
        or q["excluded_writers"] != ["EXECUTION", "COMPLETION_CREDIT"]
        or q["models"] != sorted(predecessor["models"] + _GATE2_ADDED_MODELS, key=lambda row: row["model_name"])
    ):
        raise ValueError("Wrong manual Gate 2 storage/writer delta")
    old, new = predecessor["migration_digests"], q["migration_digests"]
    if (
        not _hashes(new)
        or set(new) - set(old) != {"0025_manual_gate2_reconstruction.py"}
        or any(new.get(k) != v for k, v in old.items())
    ):
        raise ValueError("Historical migration changed")
    _validate_source_delta(
        predecessor["runtime_sources"], q["runtime_sources"], _GATE2_ADDED_MODULES, frozenset({"models.py", "urls.py"})
    )
    if (
        type(q["physical_catalog_digest"]) is not str
        or re.fullmatch(r"sha256:[0-9a-f]{64}", q["physical_catalog_digest"]) is None
        or q["physical_catalog_digest"] == predecessor["physical_catalog_digest"]
    ):
        raise ValueError("Reviewed Gate 2 catalog required")
    return q


def require_manual_gate2_v2_qualification():
    require_scope_editor_read_v2_qualification()
    if not GATE2_SUCCESSOR_PATH.exists() or GATE2_SUCCESSOR_DIGEST is None:
        raise PrdCommandError("MANUAL_GATE2_EDITION_UNAVAILABLE", 503)


def _read_pinned_successor(path, expected_digest):
    if (
        type(expected_digest) is not str
        or re.fullmatch(r"sha256:[0-9a-f]{64}", expected_digest) is None
        or path.is_symlink()
    ):
        raise ValueError("Unreviewed successor")
    raw = path.read_bytes()
    if len(raw) > 1048576 or "sha256:" + hashlib.sha256(raw).hexdigest() != expected_digest:
        raise ValueError("Successor proof mismatch")
    return json.loads(raw)


def _current_qualification(predecessor):
    # Preserve the historical proof, then apply each exact reviewed delta in order.
    qualified = dict(predecessor, runtime_sources=_qualified_runtime_sources(predecessor))
    if MANUAL_SUCCESSOR_PATH.exists():
        qualified = validate_manual_successor(
            qualified, _read_pinned_successor(MANUAL_SUCCESSOR_PATH, MANUAL_SUCCESSOR_DIGEST)
        )
        from .manual_plan_v2.validation import candidate_schemas

        candidate_schemas()
    if SCOPE_EDITOR_SUCCESSOR_PATH.exists():
        qualified = validate_scope_editor_successor(
            qualified,
            _read_pinned_successor(SCOPE_EDITOR_SUCCESSOR_PATH, SCOPE_EDITOR_SUCCESSOR_DIGEST),
            MANUAL_SUCCESSOR_DIGEST,
        )
    if GATE2_SUCCESSOR_PATH.exists():
        qualified = validate_gate2_successor(
            qualified, _read_pinned_successor(GATE2_SUCCESSOR_PATH, GATE2_SUCCESSOR_DIGEST)
        )
        from .manual_gate2_v2.contracts import validate_manifest

        validate_manifest()
        if TWO_STAGE_SUCCESSOR_PATH.exists():
            qualified = validate_two_stage_successor(
                qualified, _read_pinned_successor(TWO_STAGE_SUCCESSOR_PATH, TWO_STAGE_SUCCESSOR_DIGEST)
            )
            if REVIEW_READ_SUCCESSOR_PATH.exists():
                qualified = validate_review_read_successor(
                    qualified, _read_pinned_successor(REVIEW_READ_SUCCESSOR_PATH, REVIEW_READ_SUCCESSOR_DIGEST)
                )
        else:
            qualified = validate_source_header_successor(
                qualified, _read_pinned_successor(HEADER_SUCCESSOR_PATH, HEADER_SUCCESSOR_DIGEST)
            )
    return qualified


def validate_source_header_successor(predecessor, successor):
    """Permit exactly one fixed comment prefix on the twenty reconstructed modules.

    The historical qualification remains byte-immutable. Model, migration,
    physical-catalog and writer authority are inherited without modification.
    The complete old source bytes must still match after removing the prefix.
    """
    historical = _read_pinned_successor(GATE2_SUCCESSOR_PATH, GATE2_SUCCESSOR_DIGEST)["qualification"]
    modules = _MANUAL_ADDED_MODULES | _GATE2_ADDED_MODULES
    if (
        predecessor != historical
        or type(successor) is not dict
        or set(successor) != {"schema_version", "predecessor_digest", "header_digest", "replacements"}
        or successor["schema_version"] != "curve.source-header-qualification/v1"
        or successor["predecessor_digest"] != GATE2_SUCCESSOR_DIGEST
        or successor["header_digest"] != "sha256:" + hashlib.sha256(SOURCE_HEADER).hexdigest()
        or type(successor["replacements"]) is not dict
        or set(successor["replacements"]) != modules
    ):
        raise ValueError("Exact header-only successor required")
    sources = dict(predecessor["runtime_sources"])
    for name in sorted(modules):
        record = successor["replacements"][name]
        path = Path(__file__).parent / name
        if type(record) is not dict or set(record) != {"before", "after"} or path.is_symlink():
            raise ValueError("Exact regular source required")
        raw = path.read_bytes()
        if (
            record["before"] != sources[name]
            or not raw.startswith(SOURCE_HEADER)
            or "sha256:" + hashlib.sha256(raw[len(SOURCE_HEADER) :]).hexdigest() != record["before"]
            or "sha256:" + hashlib.sha256(raw).hexdigest() != record["after"]
        ):
            raise ValueError("Source delta exceeds the fixed copyright header")
        sources[name] = record["after"]
    return dict(predecessor, runtime_sources=sources)


def _retained_header_projection(predecessor):
    """Project the pinned historical header proof without treating current bytes as old bytes.

    The successor must subsequently verify the complete current source closure.
    This projection has no independent runtime authorization entry point.
    """
    historical = _read_pinned_successor(GATE2_SUCCESSOR_PATH, GATE2_SUCCESSOR_DIGEST)["qualification"]
    header = _read_pinned_successor(HEADER_SUCCESSOR_PATH, HEADER_SUCCESSOR_DIGEST)
    if predecessor != historical:
        raise ValueError("Historical qualification changed")
    if (
        set(header) != {"schema_version", "predecessor_digest", "header_digest", "replacements"}
        or header["schema_version"] != "curve.source-header-qualification/v1"
        or header["predecessor_digest"] != GATE2_SUCCESSOR_DIGEST
        or header["header_digest"] != "sha256:" + hashlib.sha256(SOURCE_HEADER).hexdigest()
        or set(header["replacements"]) != _MANUAL_ADDED_MODULES | _GATE2_ADDED_MODULES
    ):
        raise ValueError("Historical header proof changed")
    sources = dict(predecessor["runtime_sources"])
    for name, record in header["replacements"].items():
        if (
            set(record) != {"before", "after"}
            or record["before"] != sources[name]
            or re.fullmatch(r"sha256:[0-9a-f]{64}", record["after"]) is None
        ):
            raise ValueError("Historical source identity changed")
        sources[name] = record["after"]
    return dict(predecessor, runtime_sources=sources)


def _two_stage_model_catalog(predecessor):
    additions = ["current_local_prd_submission_id", "controlling_local_prd_decision_id"]
    models = [
        dict(row, columns=sorted(row["columns"] + additions)) if row["model_name"] == "initiative" else row
        for row in predecessor["models"]
    ]
    return sorted(models + _LOCAL_PRD_ADDED_MODELS, key=lambda row: row["model_name"])


def validate_two_stage_successor(predecessor, successor):
    """Accept only the declared two-stage source, storage and writer delta."""
    predecessor = _retained_header_projection(predecessor)
    if (
        type(successor) is not dict
        or set(successor) != {"schema_version", "predecessor_digest", "qualification"}
        or successor["schema_version"] != "curve.two-stage-review-runtime-qualification/v1-candidate"
        or successor["predecessor_digest"] != HEADER_SUCCESSOR_DIGEST
    ):
        raise ValueError("Exact two-stage qualification required")
    qualified = successor["qualification"]
    if (
        type(qualified) is not dict
        or set(qualified) != set(predecessor)
        or qualified["schema_version"] != predecessor["schema_version"]
        or qualified["model_edition"] != "CURVE_TWO_STAGE_REVIEW_V1"
        or qualified["models"] != _two_stage_model_catalog(predecessor)
        or qualified["excluded_writers"] != predecessor["excluded_writers"]
        or qualified["runtime_writer_inventory"] != predecessor["runtime_writer_inventory"] + _TWO_STAGE_WRITERS
        or qualified["physical_catalog_digest"]
        != import_module("plane.curve.migrations.0042_local_new_work_review").CURRENT_CATALOG_DIGEST
    ):
        raise ValueError("Two-stage authority exceeds the qualified delta")
    migrations = qualified["migration_digests"]
    old_migrations = predecessor["migration_digests"]
    if (
        type(migrations) is not dict
        or set(migrations) - set(old_migrations) != _TWO_STAGE_MIGRATIONS
        or any(migrations.get(name) != value for name, value in old_migrations.items())
    ):
        raise ValueError("Historical migrations changed")
    _validate_source_delta(
        predecessor["runtime_sources"],
        qualified["runtime_sources"],
        _TWO_STAGE_ADDED_MODULES,
        _TWO_STAGE_REPLACED_MODULES,
    )
    from .manual_gate2_v3.contracts import validate_manifest as validate_gate2_manifest
    from .manual_plan_v3.validation import candidate_schemas
    from .scoped_prd_v2_contracts import require_contract_integrity

    candidate_schemas()
    validate_gate2_manifest()
    require_contract_integrity()
    return qualified


def validate_review_read_successor(predecessor, successor):
    """Restrict the read-performance successor to two exact view replacements."""
    historical = _read_pinned_successor(TWO_STAGE_SUCCESSOR_PATH, TWO_STAGE_SUCCESSOR_DIGEST)["qualification"]
    if (
        predecessor != historical
        or type(successor) is not dict
        or set(successor) != {"schema_version", "predecessor_digest", "replacements"}
        or successor["schema_version"] != "curve.review-read-qualification/v1-candidate"
        or successor["predecessor_digest"] != TWO_STAGE_SUCCESSOR_DIGEST
        or type(successor["replacements"]) is not dict
        or set(successor["replacements"]) != _REVIEW_READ_REPLACED_MODULES
        or any(
            type(value) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
            or value == predecessor["runtime_sources"][name]
            for name, value in successor["replacements"].items()
        )
    ):
        raise ValueError("Exact review-read qualification required")
    return dict(predecessor, runtime_sources={**predecessor["runtime_sources"], **successor["replacements"]})


def require_manual_gate2_v3_qualification():
    require_reopening_qualification()
    if not TWO_STAGE_SUCCESSOR_PATH.exists() or TWO_STAGE_SUCCESSOR_DIGEST is None:
        raise PrdCommandError("MANUAL_GATE2_EDITION_UNAVAILABLE", 503)


def require_manual_plan_v3_qualification():
    require_reopening_qualification()
    if not TWO_STAGE_SUCCESSOR_PATH.exists() or TWO_STAGE_SUCCESSOR_DIGEST is None:
        raise PrdCommandError("MANUAL_PLAN_DRAFT_EDITION_UNAVAILABLE", 503)


def require_manual_plan_v2_qualification():
    require_reopening_qualification()
    # The baseline remains valid for old writers but cannot authorize the new one.
    if not MANUAL_SUCCESSOR_PATH.exists() or MANUAL_SUCCESSOR_DIGEST is None:
        raise PrdCommandError("MANUAL_PLAN_DRAFT_EDITION_UNAVAILABLE", 503)


def require_scope_editor_read_v2_qualification():
    require_manual_plan_v2_qualification()
    if not SCOPE_EDITOR_SUCCESSOR_PATH.exists() or SCOPE_EDITOR_SUCCESSOR_DIGEST is None:
        raise PrdCommandError("SCOPE_EDITOR_READ_EDITION_UNAVAILABLE", 503)


def current_model_catalog():
    return sorted(
        [
            dict(
                model_name=model._meta.model_name,
                db_table=model._meta.db_table,
                columns=sorted(field.column for field in model._meta.local_fields),
            )
            for model in apps.get_app_config("curve").get_models()
        ],
        key=lambda item: item["model_name"],
    )


def current_runtime_sources():
    """Exact supported Curve module closure; the validator is the trusted root.

    Tests are not runtime writers, migrations have their independent byte pin,
    and this validator cannot recursively contain its own qualification hash.
    External or dynamically injected writers are not supported by this edition.
    """
    root = Path(__file__).parent
    result = {}
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if relative.parts[0] in {"tests", "migrations"} or relative.as_posix() == "scope_reopening_qualification.py":
            continue
        if path.is_symlink():
            raise ValueError("Runtime module links are not qualified")
        result[relative.as_posix()] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _qualified_runtime_sources(predecessor):
    """Apply only the pinned, reviewed read/view/URL delta to the C2b proof.

    This loader is the explicitly trusted root, not recursively self-protected.
    No setting, deployed catalog or generic rehash can approve a new writer.
    """
    raw = READ_SUCCESSOR_PATH.read_bytes()
    if "sha256:" + hashlib.sha256(raw).hexdigest() != READ_SUCCESSOR_DIGEST:
        raise ValueError
    successor = json.loads(raw)
    if (
        type(successor) is not dict
        or set(successor) != {"schema_version", "predecessor_digest", "read_edition", "qualification"}
        or successor["schema_version"] != "curve.project-association-read-qualification/v1-candidate"
        or successor["predecessor_digest"] != QUALIFICATION_DIGEST
        or successor["read_edition"] != "LOCAL_NATIVE_PROJECT_ASSOCIATION_PRECONDITION_READ_V1"
    ):
        raise ValueError
    qualified = successor["qualification"]
    if type(qualified) is not dict or set(qualified) != set(predecessor):
        raise ValueError
    if any(qualified[key] != value for key, value in predecessor.items() if key != "runtime_sources"):
        raise ValueError
    old, new = predecessor["runtime_sources"], qualified["runtime_sources"]
    if type(new) is not dict or set(new) - set(old) != _READ_ADDED_MODULES or set(old) - set(new):
        raise ValueError
    if {name for name in old if old[name] != new[name]} != _READ_REPLACED_MODULES:
        raise ValueError
    if any(type(value) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None for value in new.values()):
        raise ValueError
    return new


def require_reopening_qualification():
    try:
        if not transaction.get_connection().in_atomic_block:
            raise ValueError
        require_reopening_contract_integrity()
        raw = QUALIFICATION_PATH.read_bytes()
        if "sha256:" + hashlib.sha256(raw).hexdigest() != QUALIFICATION_DIGEST:
            raise ValueError
        qualification = json.loads(raw)
        required = {
            "schema_version",
            "model_edition",
            "models",
            "migration_digests",
            "runtime_writer_inventory",
            "excluded_writers",
            "physical_catalog_digest",
            "runtime_sources",
        }
        if (
            type(qualification) is not dict
            or set(qualification) != required
            or qualification["schema_version"] != "curve.scope-reopening-qualification/v1-candidate"
            or qualification["model_edition"] != "CURVE_PRE_PLAN_C2B_V1"
            or qualification["runtime_writer_inventory"]
            != [
                "INITIATIVE_DRAFT_AND_REFINEMENT",
                "C1_DRAFT_SCOPE_SELECTION",
                "C2A_SCOPED_PRD_GATE_1",
                "LEGACY_PRD_NON_DELIVERY_GATE_1",
                "PRODUCT_LIFECYCLE",
                "PROJECT_ASSOCIATION_CREATE_END",
                "OPERATION_SETTLEMENT",
                "C2B_SCOPE_REOPEN_AND_REPLACE",
            ]
            or qualification["excluded_writers"]
            != [
                "PLAN_APPROVAL",
                "CONTROLLING_WORK_BINDING",
                "EXECUTION",
                "COMPLETION_CREDIT",
            ]
            or type(qualification["physical_catalog_digest"]) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", qualification["physical_catalog_digest"]) is None
        ):
            raise ValueError
        qualification = _current_qualification(qualification)
        if current_runtime_sources() != qualification["runtime_sources"]:
            raise ValueError
        directory = Path(__file__).parent / "migrations"
        actual = {
            path.name: "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.glob("[0-9]*.py"))
        }
        if actual != qualification["migration_digests"] or current_model_catalog() != qualification["models"]:
            raise ValueError
        with connection.cursor() as cursor:
            cursor.execute("SELECT name FROM django_migrations WHERE app = 'curve' ORDER BY name")
            if [row[0] + ".py" for row in cursor.fetchall()] != sorted(actual):
                raise ValueError
            # Independently compare the physical catalog to the reviewed source
            # pin, rather than trusting a possibly changed DB verifier or seal.
            catalog_sql = import_module(
                "plane.curve.migrations."
                + ("0025_manual_gate2_reconstruction" if GATE2_SUCCESSOR_PATH.exists() else "0023_scope_reopening")
            ).CATALOG_SQL
            cursor.execute("SELECT current_setting('search_path'), current_setting('jit')")
            previous_path, previous_jit = cursor.fetchone()
            # Catalog checks return one small snapshot. Compiling hundreds of
            # expressions costs more than executing them; keep every check fresh
            # and restore the caller's settings before returning.
            cursor.execute("SET LOCAL jit = off")
            try:
                cursor.execute("SET LOCAL search_path = pg_catalog, public")
                cursor.execute(
                    "SELECT 'sha256:' || encode(sha256(convert_to((" + catalog_sql + ")::text, 'UTF8')), 'hex')"
                )
                physical = cursor.fetchone()[0]
                cursor.execute("SELECT set_config('search_path', %s, true)", [previous_path])
                if physical != qualification["physical_catalog_digest"]:
                    raise ValueError
                cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
            finally:
                cursor.execute(
                    "SELECT set_config('search_path', %s, true), set_config('jit', %s, true)",
                    [previous_path, previous_jit],
                )
    except Exception:
        raise PrdCommandError("SCOPE_REOPENING_EDITION_UNAVAILABLE", 503) from None
