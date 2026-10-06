"""Fixed local-only input resolver. Configuration and object names are not API input.

The runtime accepts this exact class only. The catalog is a bounded, owner-only
file below a trusted root; objects are opaque UUID filenames in that same root.
No provider, URL, callback, environment importer or executable plan instruction.
"""

import os
import re
import stat
import uuid
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from .contracts import require, validate
from .validation import digest, metadata_digest, parse_strict_json

EDITION = "FIXED_SYNTHETIC_LOCAL_MANUAL_PLAN_V2"
CATALOG_LIMIT = 1024 * 1024
TOTAL_INPUT_LIMIT = 16 * 1024 * 1024
ACTIONS = frozenset({"SAVE", "READ_CURRENT", "READ_REVISION", "READ_STATUS"})


def _stamp(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _positive(value):
    return type(value) is int and 1 <= value <= 9007199254740991


def _id(value):
    require(type(value) is str and str(uuid.UUID(value)) == value)
    return value


def _closed(value, names):
    require(type(value) is dict and set(value) == set(names))


def _validate_grants(grants):
    require(type(grants) is list and len(grants) <= 512)
    seen = set()
    for grant in grants:
        _closed(grant, ("principal_id", "actions", "acl_generation", "classification_generation"))
        principal = _id(grant["principal_id"])
        require(principal not in seen)
        seen.add(principal)
        require(
            type(grant["actions"]) is list
            and len(grant["actions"]) <= len(ACTIONS)
            and grant["actions"] == sorted(set(grant["actions"]))
            and set(grant["actions"]) <= ACTIONS
        )
        require(_positive(grant["acl_generation"]) and _positive(grant["classification_generation"]))


def _authorize_grants(grants, principals, action):
    by_principal = {grant["principal_id"]: grant for grant in grants}
    requested = sorted({str(item) for item in principals})
    require(requested and all(item in by_principal and action in by_principal[item]["actions"] for item in requested))
    return tuple(deepcopy(by_principal[item]) for item in requested)


@dataclass(frozen=True)
class CapturedPlan:
    identity: dict
    facts: dict
    definition: bytes
    technical_contributor_ids: tuple
    catalog_generation: int
    grants: tuple
    file_fence: tuple


class SyntheticManualPlanResolverV2:
    def __init__(self, root):
        require(type(self) is SyntheticManualPlanResolverV2, "EDITION_UNAVAILABLE")
        self.root = root
        self.root_fd = self._open_root(root)
        self.root_stamp = _stamp(os.fstat(self.root_fd))

    @staticmethod
    def _open_root(root):
        require(type(root) is str and Path(root).is_absolute(), "EDITION_UNAVAILABLE")
        parts = Path(root).parts
        require(".." not in parts, "EDITION_UNAVAILABLE")
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in parts[1:]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            info = os.fstat(fd)
            require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0)
            return fd
        except BaseException:
            os.close(fd)
            raise

    @classmethod
    def from_settings(cls):
        from django.conf import settings

        require(cls is SyntheticManualPlanResolverV2, "EDITION_UNAVAILABLE")
        require(getattr(settings, "CURVE_ENVIRONMENT", None) == "LOCAL", "EDITION_UNAVAILABLE")
        # No resolver object or import path can be selected by a setting.
        return cls(getattr(settings, "CURVE_MANUAL_PLAN_V2_SYNTHETIC_ROOT", None))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        os.close(self.root_fd)
        self.root_fd = -1

    def _read(self, name, bound):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.root_fd)
        try:
            info = os.fstat(fd)
            require(
                stat.S_ISREG(info.st_mode)
                and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) & 0o077 == 0
                and info.st_nlink == 1
                and 0 <= info.st_size <= bound
            )
            chunks, length = [], 0
            while True:
                block = os.read(fd, min(65536, bound + 1 - length))
                if not block:
                    break
                chunks.append(block)
                length += len(block)
                require(length <= bound)
            require(length == info.st_size and _stamp(os.fstat(fd)) == _stamp(info))
            return b"".join(chunks), (name, _stamp(info))
        finally:
            os.close(fd)

    def _catalog(self):
        raw, fence = self._read("catalog.json", CATALOG_LIMIT)
        catalog = parse_strict_json(raw, max_bytes=CATALOG_LIMIT)
        _closed(catalog, ("schema_version", "generation", "initiatives", "plans", "objects"))
        require(catalog["schema_version"] == "curve.synthetic-manual-plan-catalog/v2-candidate")
        require(_positive(catalog["generation"]))
        require(type(catalog["initiatives"]) is dict and len(catalog["initiatives"]) <= 128)
        require(type(catalog["plans"]) is dict and len(catalog["plans"]) <= 128)
        require(type(catalog["objects"]) is dict and len(catalog["objects"]) <= 512)
        for key, entry in catalog["initiatives"].items():
            _id(key)
            _closed(entry, ("workspace_id", "technical_contributor_ids", "grants"))
            _id(entry["workspace_id"])
            contributors = entry["technical_contributor_ids"]
            require(type(contributors) is list and len(contributors) <= 256)
            require(contributors == sorted({_id(item) for item in contributors}))
            _validate_grants(entry["grants"])
        for key, entry in catalog["objects"].items():
            _id(key)
            _closed(
                entry,
                ("workspace_id", "object_ref", "material_version_id", "access_envelope_id", "classification", "grants"),
            )
            _id(entry["workspace_id"])
            _id(entry["material_version_id"])
            _id(entry["access_envelope_id"])
            _closed(entry["object_ref"], ("object_id", "digest", "size_bytes", "media_type"))
            require(
                entry["object_ref"]["object_id"] == key
                and type(entry["object_ref"]["digest"]) is str
                and re.fullmatch(r"sha256:[0-9a-f]{64}", entry["object_ref"]["digest"]) is not None
                and type(entry["object_ref"]["media_type"]) is str
                and 1 <= len(entry["object_ref"]["media_type"]) <= 255
                and type(entry["object_ref"]["size_bytes"]) is int
                and 0 < entry["object_ref"]["size_bytes"] <= TOTAL_INPUT_LIMIT
                and entry["classification"] in {"INTERNAL", "CONFIDENTIAL", "RESTRICTED"}
            )
            _validate_grants(entry["grants"])
        for key, plan in catalog["plans"].items():
            _id(key)
            _closed(plan, ("identity", "facts"))
            validate("manual-plan-input-identity-v2", plan["identity"])
            require(
                plan["identity"]["digest"] == metadata_digest(plan["identity"])
                and plan["identity"]["definition_ref"]["object_id"] == key
            )
            _closed(
                plan["facts"],
                (
                    "workspace_id",
                    "initiative_id",
                    "initiative_key",
                    "manual_profile_ref",
                    "approved_subject_ref",
                    "scope_revision_ref",
                    "workflow_ref",
                    "quality_policy_ref",
                    "repositories",
                    "owner_ids",
                    "code_approver_id",
                    "risk_tier",
                    "budget_policy_ref",
                    "requirement_ids",
                    "acceptance_ids",
                    "required_check_ids",
                    "proposed_delivery_refs",
                    "dependency_artifact_refs",
                    "protected_object_refs",
                    "workflow_conditions",
                ),
            )
        return catalog, fence

    def authorize(self, *, workspace_id, initiative_id, principals, action):
        require(action in ACTIONS)
        catalog, fence = self._catalog()
        entry = catalog["initiatives"].get(str(initiative_id))
        require(entry is not None and entry["workspace_id"] == str(workspace_id))
        grants = _authorize_grants(entry["grants"], principals, action)
        return catalog, entry, grants, fence

    def read_material(self, *, catalog, workspace_id, reference, principals, action, original=None):
        entry = catalog["objects"].get(_id(reference["object_id"]))
        require(entry is not None and entry["workspace_id"] == str(workspace_id) and entry["object_ref"] == reference)
        if original is not None:
            for key in ("material_version_id", "access_envelope_id", "classification"):
                require(entry[key] == original[key])
        grants = _authorize_grants(entry["grants"], principals, action)
        raw, fence = self._read(reference["object_id"], reference["size_bytes"])
        require(len(raw) == reference["size_bytes"] and digest(raw) == reference["digest"])
        return raw, fence, tuple(dict(grant, object_id=reference["object_id"]) for grant in grants)

    def capture(self, *, workspace_id, initiative_id, definition_ref, principals, action):
        catalog, entry, grants, catalog_fence = self.authorize(
            workspace_id=workspace_id,
            initiative_id=initiative_id,
            principals=principals,
            action=action,
        )
        object_id = _id(definition_ref["object_id"])
        plan = catalog["plans"].get(object_id)
        require(plan is not None)
        identity = plan["identity"]
        require(
            identity["workspace_id"] == str(workspace_id)
            and identity["initiative_id"] == str(initiative_id)
            and identity["definition_ref"] == definition_ref
        )
        refs = [definition_ref] + [entry["object_ref"] for entry in identity["protected_inputs"]]
        require(len({ref["object_id"] for ref in refs}) == len(refs))
        require(sum(ref["size_bytes"] for ref in refs) <= TOTAL_INPUT_LIMIT)
        fences, definition, all_grants = [catalog_fence], None, list(grants)
        originals = {item["object_ref"]["object_id"]: item for item in identity["protected_inputs"]}
        for index, ref in enumerate(refs):
            raw, fence, object_grants = self.read_material(
                catalog=catalog,
                workspace_id=workspace_id,
                reference=ref,
                principals=principals,
                action=action,
                original=originals.get(ref["object_id"]),
            )
            all_grants.extend(object_grants)
            fences.append(fence)
            if index == 0:
                definition = raw
        self.recheck(tuple(fences))
        return CapturedPlan(
            deepcopy(identity),
            deepcopy(plan["facts"]),
            definition,
            tuple(entry["technical_contributor_ids"]),
            catalog["generation"],
            tuple(all_grants),
            tuple(fences),
        )

    def recheck(self, fence):
        require(_stamp(os.fstat(self.root_fd)) == self.root_stamp)
        current_root = self._open_root(self.root)
        try:
            require(_stamp(os.fstat(current_root)) == self.root_stamp)
        finally:
            os.close(current_root)
        for name, expected in fence:
            # Relative no-follow stat prevents a replaced symlink from looking
            # like the original object. It is not a privileged-tampering proof.
            current = os.stat(name, dir_fd=self.root_fd, follow_symlinks=False)
            require(stat.S_ISREG(current.st_mode) and _stamp(current) == expected)
