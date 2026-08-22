# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import json
from functools import lru_cache
from pathlib import Path


MANIFEST_PATH = Path(__file__).resolve().parent.parent / "contracts" / "observability" / "m0-s5-telemetry-v1.json"
MANIFEST_SHA256 = "8ba95e5e605188e829df03374114eb2ec0d2cbea0218f1d286198cbbb2d34d9b"


class TelemetryManifestIntegrityError(RuntimeError):
    """Raised when the vendored telemetry contract does not match its reviewed bytes."""


@lru_cache(maxsize=1)
def telemetry_manifest() -> dict:
    contents = MANIFEST_PATH.read_bytes()
    if hashlib.sha256(contents).hexdigest() != MANIFEST_SHA256:
        raise TelemetryManifestIntegrityError("Curve telemetry manifest digest mismatch")
    manifest = json.loads(contents)
    if (
        manifest.get("manifest_key") != "CURVE_M0_TELEMETRY"
        or manifest.get("manifest_version") != 1
        or manifest.get("default_mode") != "DISABLED"
        or manifest.get("allowed_modes") != ["DISABLED", "IN_MEMORY_TEST", "OTLP"]
    ):
        raise TelemetryManifestIntegrityError("Curve telemetry manifest identity mismatch")
    return manifest


def clear_manifest_cache_for_tests() -> None:
    telemetry_manifest.cache_clear()
