# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Fixed local Feature material authority over explicitly granted immutable objects.

This candidate is local-only. A qualified native command must hold this lease
outside its database transaction, resolve current membership under native locks,
and revalidate the capture before committing. Catalog publishers share the same
stable lock inode. Neither a reference nor a capture supplies Feature edit rights.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
import fcntl
import hashlib
import json
import os
import stat
from types import MappingProxyType
from uuid import UUID, uuid4

from django.conf import settings

from plane.curve.feature_input import FeatureInputError, normalize_feature_command
from plane.curve.manual_plan_v2.synthetic import _stamp
from plane.curve.manual_plan_v2.validation import InvalidPlan, parse_strict_json
from plane.curve.manual_plan_v2.contracts import ManualPlanError
from plane.curve.manual_plan_v3.synthetic import SyntheticManualPlanResolverV3


CATALOG_LIMIT = 1024 * 1024
MATERIAL_LIMIT = 16 * 1024 * 1024
EDITION = "curve.local-feature-material/v1-candidate"
DESTINATION = "CURVE_FEATURE_LOCAL_V1"


class FeatureMaterialUnavailable(ValueError):
    pass


def _available(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except FeatureMaterialUnavailable:
            raise
        except (OSError, ManualPlanError, InvalidPlan, FeatureInputError, KeyError, TypeError, AttributeError):
            raise FeatureMaterialUnavailable("FEATURE_MATERIAL_UNAVAILABLE") from None

    return guarded


def _require(value, code="FEATURE_MATERIAL_UNAVAILABLE"):
    if not value:
        raise FeatureMaterialUnavailable(code)


def _closed(value, keys):
    _require(type(value) is dict and set(value) == set(keys))


def _uuid(value):
    _require(type(value) is str)
    try:
        _require(str(UUID(value)) == value)
    except (ValueError, TypeError, AttributeError) as error:
        raise FeatureMaterialUnavailable("FEATURE_MATERIAL_UNAVAILABLE") from error
    return value


def _counter(value, minimum=1):
    _require(type(value) is int and minimum <= value <= 9223372036854775807)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _decode(raw):
    value = parse_strict_json(raw, max_bytes=CATALOG_LIMIT)
    _closed(value, ("schema_version", "generation", "objects"))
    _require(value["schema_version"] == EDITION)
    _counter(value["generation"])
    _require(type(value["objects"]) is dict and len(value["objects"]) <= 512)
    for object_id, item in value["objects"].items():
        _uuid(object_id)
        _closed(
            item,
            (
                "workspace_id",
                "product_id",
                "reference",
                "access_envelope_id",
                "classification",
                "destination",
                "grants",
            ),
        )
        for key in ("workspace_id", "product_id", "access_envelope_id"):
            _uuid(item[key])
        reference = normalize_feature_command(
            "CREATE_FEATURE", {"name": "Material", "description": item["reference"]}, None
        ).description
        _require(reference is not None and dict(reference) == item["reference"] and reference["object_id"] == object_id)
        _require(reference["size_bytes"] <= MATERIAL_LIMIT)
        _require(item["classification"] in {"INTERNAL", "CONFIDENTIAL", "RESTRICTED"})
        _require(item["destination"] == DESTINATION)
        _require(type(item["grants"]) is dict and len(item["grants"]) <= 512)
        for actor_id, grant in item["grants"].items():
            _uuid(actor_id)
            _closed(grant, ("membership_id", "membership_generation", "acl_generation", "can_read"))
            _uuid(grant["membership_id"])
            _counter(grant["membership_generation"], 0)
            _counter(grant["acl_generation"])
            _require(type(grant["can_read"]) is bool)
    return value


@dataclass(frozen=True, slots=True)
class FeatureMaterialCapture:
    workspace_id: str
    product_id: str
    actor_id: str
    membership_id: str
    membership_generation: int
    catalog_generation: int
    observations: tuple
    _fences: tuple
    _material_digests: tuple
    _catalog_digest: str
    _token: object


class LocalFeatureMaterialResolver:
    @_available
    def __init__(self, root):
        _require(type(self) is LocalFeatureMaterialResolver)
        self._files = SyntheticManualPlanResolverV3(root)
        self._lease_token = None

    @classmethod
    @_available
    def from_settings(cls):
        _require(cls is LocalFeatureMaterialResolver and getattr(settings, "CURVE_ENVIRONMENT", None) == "LOCAL")
        _require(getattr(settings, "CURVE_LOCAL_FEATURE_MATERIAL_ENABLED", False) is True)
        return cls(getattr(settings, "CURVE_LOCAL_FEATURE_MATERIAL_ROOT", None))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._files.__exit__(*args)

    @_available
    def _acquire_lock(self, mode):
        descriptor = os.open("catalog.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._files.root_fd)
        try:
            info = os.fstat(descriptor)
            _require(
                stat.S_ISREG(info.st_mode)
                and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) & 0o077 == 0
                and info.st_nlink == 1
            )
            try:
                fcntl.flock(descriptor, mode | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise FeatureMaterialUnavailable("FEATURE_MATERIAL_BUSY") from error
            self._files.recheck((("catalog.lock", _stamp(info)),))
            return descriptor, ("catalog.lock", _stamp(info))
        except BaseException:
            os.close(descriptor)
            raise

    @contextmanager
    def _lock(self, mode):
        descriptor, fence = self._acquire_lock(mode)
        try:
            yield fence
        finally:
            os.close(descriptor)

    @_available
    def _recheck(self, fences):
        self._files.recheck(fences)

    @contextmanager
    def lease(self):
        _require(self._lease_token is None, "FEATURE_MATERIAL_LEASE_ACTIVE")
        with self._lock(fcntl.LOCK_SH) as fence:
            token = object()
            self._lease_token = token
            try:
                yield self
                self._recheck((fence,))
            finally:
                self._lease_token = None

    @_available
    def capture(self, *, workspace_id, product_id, actor_id, membership_id, membership_generation, requirements):
        _require(self._lease_token is not None, "FEATURE_MATERIAL_LEASE_REQUIRED")
        workspace_id, product_id, actor_id, membership_id = (
            _uuid(str(value)) for value in (workspace_id, product_id, actor_id, membership_id)
        )
        _counter(membership_generation, 0)
        _require(type(requirements) is tuple and len(requirements) <= 2)
        raw, catalog_fence = self._files._read("catalog.json", CATALOG_LIMIT)
        catalog = _decode(raw)
        fences, observations, seen, total = [catalog_fence], [], set(), 0
        material_digests = []
        for requirement in requirements:
            reference = dict(requirement.reference)
            object_id = _uuid(reference["object_id"])
            _require(object_id not in seen)
            seen.add(object_id)
            item = catalog["objects"].get(object_id)
            _require(item is not None and item["workspace_id"] == workspace_id and item["product_id"] == product_id)
            _require(item["reference"] == reference)
            grant = item["grants"].get(actor_id)
            _require(
                grant is not None
                and grant["can_read"] is True
                and grant["membership_id"] == membership_id
                and grant["membership_generation"] == membership_generation
            )
            total += reference["size_bytes"]
            _require(total <= MATERIAL_LIMIT)
            body, fence = self._files._read(object_id, reference["size_bytes"])
            _require(len(body) == reference["size_bytes"] and _digest(body) == reference["digest"])
            fences.append(fence)
            material_digests.append((object_id, reference["digest"], reference["size_bytes"]))
            observations.append(
                MappingProxyType(
                    {
                        "object_id": object_id,
                        "reference_digest": _digest(_canonical(reference)),
                        "access_envelope_id": item["access_envelope_id"],
                        "classification": item["classification"],
                        "acl_generation": grant["acl_generation"],
                        "purposes": tuple(sorted(requirement.purposes)),
                    }
                )
            )
        self._files.recheck(tuple(fences))
        return FeatureMaterialCapture(
            workspace_id,
            product_id,
            actor_id,
            membership_id,
            membership_generation,
            catalog["generation"],
            tuple(observations),
            tuple(fences),
            tuple(material_digests),
            _digest(raw),
            self._lease_token,
        )

    @_available
    def revalidate(self, capture):
        _require(
            isinstance(capture, FeatureMaterialCapture)
            and self._lease_token is not None
            and capture._token is self._lease_token,
            "FEATURE_MATERIAL_CAPTURE_EXPIRED",
        )
        current_catalog, _ = self._files._read("catalog.json", CATALOG_LIMIT)
        _require(_digest(current_catalog) == capture._catalog_digest, "FEATURE_MATERIAL_CHANGED")
        for object_id, expected_digest, expected_size in capture._material_digests:
            current_body, _ = self._files._read(object_id, expected_size)
            _require(
                len(current_body) == expected_size and _digest(current_body) == expected_digest,
                "FEATURE_MATERIAL_CHANGED",
            )
        self._files.recheck(capture._fences)

    @_available
    def publish_catalog(self, *, expected_digest, replacement):
        """Private operator CAS; no API endpoint or client-selected access facts."""
        _require(self._lease_token is None, "FEATURE_MATERIAL_LEASE_ACTIVE")
        raw = _canonical(replacement)
        proposed = _decode(raw)
        temporary = None
        with self._lock(fcntl.LOCK_EX):
            old_raw, _ = self._files._read("catalog.json", CATALOG_LIMIT)
            old = _decode(old_raw)
            _require(_digest(old_raw) == expected_digest, "FEATURE_MATERIAL_VERSION_CHANGED")
            _require(proposed["generation"] == old["generation"] + 1)
            for object_id, original in old["objects"].items():
                current = proposed["objects"].get(object_id)
                _require(
                    current is not None
                    and {k: v for k, v in original.items() if k != "grants"}
                    == {k: v for k, v in current.items() if k != "grants"}
                )
                _require(set(original["grants"]) <= set(current["grants"]))
                for actor_id, before in original["grants"].items():
                    after = current["grants"][actor_id]
                    _require(after["acl_generation"] >= before["acl_generation"])
                    if after["membership_id"] == before["membership_id"]:
                        _require(after["membership_generation"] >= before["membership_generation"])
                    if after != before:
                        _require(after["acl_generation"] > before["acl_generation"])
            try:
                temporary = ".catalog-" + str(uuid4())
                descriptor = os.open(
                    temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self._files.root_fd
                )
                try:
                    pending = memoryview(raw)
                    while pending:
                        written = os.write(descriptor, pending)
                        _require(written > 0)
                        pending = pending[written:]
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                # Check the trusted root identity again without allowing a path redirect.
                current_root = self._files._open_root(self._files.root)
                try:
                    current, original = os.fstat(current_root), os.fstat(self._files.root_fd)
                    _require((current.st_dev, current.st_ino) == (original.st_dev, original.st_ino))
                finally:
                    os.close(current_root)
                os.replace(temporary, "catalog.json", src_dir_fd=self._files.root_fd, dst_dir_fd=self._files.root_fd)
                temporary = None
                os.fsync(self._files.root_fd)
                self._files.root_stamp = _stamp(os.fstat(self._files.root_fd))
            finally:
                if temporary is not None:
                    os.unlink(temporary, dir_fd=self._files.root_fd)
        return _digest(raw)
