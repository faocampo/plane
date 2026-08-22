# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import base64
import hashlib
import hmac
import uuid


_DOMAIN = b"curve-workspace-scope:v1\x00"


def workspace_scope(*, workspace_id: uuid.UUID | str, key: bytes) -> str:
    parsed = uuid.UUID(str(workspace_id))
    material = _DOMAIN + str(parsed).lower().encode("ascii")
    digest = hmac.new(key, material, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
