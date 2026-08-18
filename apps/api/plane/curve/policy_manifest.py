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


class PolicyManifestIntegrityError(RuntimeError):
    pass


def _deep_freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


@lru_cache(maxsize=1)
def load_core_policy_manifest() -> Mapping[str, object]:
    try:
        manifest_bytes = CORE_POLICY_MANIFEST_PATH.read_bytes()
    except OSError as error:
        raise PolicyManifestIntegrityError("core policy manifest is unavailable") from error

    digest = f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}"
    if digest != CORE_POLICY_MANIFEST_DIGEST:
        raise PolicyManifestIntegrityError("core policy manifest digest mismatch")

    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PolicyManifestIntegrityError("core policy manifest is invalid JSON") from error

    if (
        manifest.get("schema_version") != "1.0"
        or manifest.get("policy_key") != "CURVE_CORE_POLICY"
        or manifest.get("policy_version") != 1
        or manifest.get("default_effect") != "DENY"
    ):
        raise PolicyManifestIntegrityError("core policy manifest identity mismatch")

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


def clear_core_policy_manifest_cache():
    load_core_policy_manifest.cache_clear()
