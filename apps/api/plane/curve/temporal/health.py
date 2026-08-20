# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import os
import socket
import sys

from plane.curve.temporal.environment import validate_worker_environment


def _connect(address: str) -> bool:
    host, raw_port = address.rsplit(":", 1)
    try:
        with socket.create_connection((host, int(raw_port)), timeout=2):
            return True
    except (OSError, TimeoutError, ValueError):
        return False


def main() -> None:
    validate_worker_environment()
    database_host = "plane-db:5432"
    temporal_address = os.environ["TEMPORAL_ADDRESS"]
    if not _connect(database_host) or not _connect(temporal_address):
        sys.exit(1)


if __name__ == "__main__":
    main()
