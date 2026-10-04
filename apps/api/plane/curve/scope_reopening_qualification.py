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
            or current_runtime_sources() != _qualified_runtime_sources(qualification)
        ):
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
