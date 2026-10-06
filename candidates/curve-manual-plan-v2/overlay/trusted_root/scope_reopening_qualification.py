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
MANUAL_SUCCESSOR_DIGEST = None
MANUAL_SUCCESSOR_PATH = Path(__file__).parent / "manual_plan_draft_reconstruction_qualification_v2.json"
SCOPE_EDITOR_SUCCESSOR_DIGEST = None
SCOPE_EDITOR_SUCCESSOR_PATH = Path(__file__).parent / "scope_editor_read_reconstruction_qualification_v2.json"
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
    return qualified


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
            catalog_sql = import_module("plane.curve.migrations.0023_scope_reopening").CATALOG_SQL
            cursor.execute("SHOW search_path")
            previous_path = cursor.fetchone()[0]
            cursor.execute("SET LOCAL search_path = pg_catalog, public")
            cursor.execute("SELECT 'sha256:' || encode(sha256(convert_to((" + catalog_sql + ")::text, 'UTF8')), 'hex')")
            physical = cursor.fetchone()[0]
            cursor.execute("SELECT set_config('search_path', %s, true)", [previous_path])
            if physical != qualification["physical_catalog_digest"]:
                raise ValueError
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    except Exception:
        raise PrdCommandError("SCOPE_REOPENING_EDITION_UNAVAILABLE", 503) from None
