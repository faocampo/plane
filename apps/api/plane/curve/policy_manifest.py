# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


CORE_POLICY_MANIFEST_DIGEST = "sha256:e0c4a03e27fd2b53b0109856c1599804865469ebebfc480244f4e76f7653cc52"
CORE_POLICY_MANIFEST_PATH = Path(__file__).resolve().parent / "contracts" / "policy" / "core-policy-v1.json"
CORE_POLICY_V2_MANIFEST_DIGEST = "sha256:2895b63392236afa07e6f0572d6ddb1c91aa7f40d37282f250019d2829ed5787"
CORE_POLICY_V2_MANIFEST_PATH = Path(__file__).resolve().parent / "contracts" / "policy" / "core-policy-v2.json"
PRD_POLICY_MANIFEST_DIGEST = "sha256:ad38408f0e4450c615025debdf3361965f3a7361ad392aaf9aeb4219b910cb4c"
PRD_POLICY_MANIFEST_PATH = Path(__file__).resolve().parent / "prd_candidate_policy" / "prd-policy-v1.json"
SUPPORTED_CORE_POLICY_MANIFEST_DIGESTS = frozenset(
    {
        CORE_POLICY_MANIFEST_DIGEST,
        CORE_POLICY_V2_MANIFEST_DIGEST,
        PRD_POLICY_MANIFEST_DIGEST,
    }
)


class PolicyManifestIntegrityError(RuntimeError):
    pass


def _deep_freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _load_manifest(
    *,
    manifest_path: Path,
    manifest_digest: str,
    schema_version: str,
    policy_version: int,
    policy_key: str = "CURVE_CORE_POLICY",
) -> Mapping[str, object]:
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as error:
        raise PolicyManifestIntegrityError("core policy manifest is unavailable") from error

    digest = f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}"
    if digest != manifest_digest:
        raise PolicyManifestIntegrityError("core policy manifest digest mismatch")

    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PolicyManifestIntegrityError("core policy manifest is invalid JSON") from error

    if (
        manifest.get("schema_version") != schema_version
        or manifest.get("policy_key") != policy_key
        or manifest.get("policy_version") != policy_version
        or manifest.get("default_effect") != "DENY"
    ):
        raise PolicyManifestIntegrityError("core policy manifest identity mismatch")

    if policy_version == 2:
        expected_role_source = {
            "role": "PLATFORM_ADMINISTRATOR",
            "actor_type": "HUMAN",
            "source": "PLANE_WORKSPACE_MEMBERSHIP",
            "plane_role": 20,
            "membership_active": True,
            "workspace_match": "REQUIRED",
            "caller_supplied_role": "REJECT",
            "allowed_actions": [
                "CURVE.PROVIDER_CONNECTION.REGISTER",
                "CURVE.PROVIDER_CONNECTION.ADMINISTER",
            ],
        }
        if manifest.get("supersedes") != {
            "policy_version": 1,
            "manifest_digest": CORE_POLICY_MANIFEST_DIGEST,
        } or manifest.get("trusted_role_sources") != [expected_role_source]:
            raise PolicyManifestIntegrityError("core policy manifest authority mismatch")

    actions = manifest.get("actions")
    precedence = manifest.get("deny_precedence")
    if (
        not isinstance(actions, list)
        or not actions
        or len({item.get("action") for item in actions if isinstance(item, dict)}) != len(actions)
        or not isinstance(precedence, list)
        or not precedence
        or len(precedence) != len(set(precedence))
    ):
        raise PolicyManifestIntegrityError("core policy manifest structure mismatch")

    return _deep_freeze(manifest)


@lru_cache(maxsize=1)
def load_core_policy_manifest() -> Mapping[str, object]:
    """Load the immutable policy-v1 manifest used by existing Curve actions."""

    return _load_manifest(
        manifest_path=CORE_POLICY_MANIFEST_PATH,
        manifest_digest=CORE_POLICY_MANIFEST_DIGEST,
        schema_version="1.0",
        policy_version=1,
    )


@lru_cache(maxsize=1)
def load_core_policy_v2_manifest() -> Mapping[str, object]:
    """Load the immutable policy-v2 manifest used by provider actions."""

    return _load_manifest(
        manifest_path=CORE_POLICY_V2_MANIFEST_PATH,
        manifest_digest=CORE_POLICY_V2_MANIFEST_DIGEST,
        schema_version="2.0",
        policy_version=2,
    )


@lru_cache(maxsize=1)
def load_prd_policy_manifest() -> Mapping[str, object]:
    return _load_manifest(
        manifest_path=PRD_POLICY_MANIFEST_PATH,
        manifest_digest=PRD_POLICY_MANIFEST_DIGEST,
        schema_version="1.0-candidate",
        policy_version=1,
        policy_key="CURVE_PRD_POLICY",
    )


def load_core_policy_manifest_for_digest(policy_manifest_digest: object) -> Mapping[str, object] | None:
    """Resolve only a supported exact digest without silently changing policy."""

    if policy_manifest_digest == CORE_POLICY_MANIFEST_DIGEST:
        return load_core_policy_manifest()
    if policy_manifest_digest == CORE_POLICY_V2_MANIFEST_DIGEST:
        return load_core_policy_v2_manifest()
    if policy_manifest_digest == PRD_POLICY_MANIFEST_DIGEST:
        return load_prd_policy_manifest()
    return None


def clear_core_policy_manifest_cache():
    load_core_policy_manifest.cache_clear()
    load_core_policy_v2_manifest.cache_clear()
    load_prd_policy_manifest.cache_clear()
