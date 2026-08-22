# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import logging
import threading
import time


_heartbeat_lock = threading.Lock()
_last_worker_heartbeat = time.monotonic()
_snapshot_lock = threading.Lock()
_snapshot_cached_at = 0.0
_snapshot_cached_value = None
_last_failure_diagnostic_at = 0.0
_SNAPSHOT_CACHE_SECONDS = 0.5
_FAILURE_DIAGNOSTIC_SECONDS = 60.0
_logger = logging.getLogger("plane.curve.observability")


def mark_worker_heartbeat() -> None:
    global _last_worker_heartbeat
    with _heartbeat_lock:
        _last_worker_heartbeat = time.monotonic()


def _worker_heartbeat_observations(options):
    with _heartbeat_lock:
        age = max(0.0, time.monotonic() - _last_worker_heartbeat)
    return [(age, {"curve.component": "TEMPORAL_WORKER"})]


def _outbox_snapshot():
    from django.db import close_old_connections, connection, transaction
    from django.utils import timezone

    from plane.curve.models import OutboxState

    close_old_connections()
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = %s", [1000])
                cursor.execute(
                    """
                    SELECT
                        state,
                        COUNT(*) AS total,
                        MIN(
                            MIN(created_at) FILTER (
                                WHERE state IN ('PENDING', 'RETRY_SCHEDULED')
                            )
                        ) OVER () AS oldest_deliverable
                    FROM curve_outbox_event
                    GROUP BY state
                    """
                )
                rows = cursor.fetchall()
        counts = {state: 0 for state in OutboxState.values}
        counts.update({state: total for state, total, _ in rows})
        oldest = rows[0][2] if rows else None
        oldest_age = max(0.0, (timezone.now() - oldest).total_seconds()) if oldest else 0.0
        return counts, oldest_age
    finally:
        close_old_connections()


def _cached_outbox_snapshot():
    global _snapshot_cached_at, _snapshot_cached_value
    now = time.monotonic()
    with _snapshot_lock:
        if _snapshot_cached_value is not None and now - _snapshot_cached_at <= _SNAPSHOT_CACHE_SECONDS:
            return _snapshot_cached_value
        value = _outbox_snapshot()
        _snapshot_cached_at = now
        _snapshot_cached_value = value
        return value


def _diagnose_gauge_failure() -> None:
    global _last_failure_diagnostic_at
    now = time.monotonic()
    with _snapshot_lock:
        if now - _last_failure_diagnostic_at < _FAILURE_DIAGNOSTIC_SECONDS:
            return
        _last_failure_diagnostic_at = now
    _logger.warning("Curve outbox gauge collection omitted after a bounded query failure")


def _outbox_backlog_observations(options):
    try:
        counts, _ = _cached_outbox_snapshot()
    except Exception:
        _diagnose_gauge_failure()
        return []
    return [
        (
            count,
            {
                "curve.component": "OUTBOX_RELAY",
                "curve.outbox.state": state,
            },
        )
        for state, count in sorted(counts.items())
    ]


def _outbox_oldest_age_observations(options):
    try:
        _, age = _cached_outbox_snapshot()
    except Exception:
        _diagnose_gauge_failure()
        return []
    return [(age, {"curve.component": "OUTBOX_RELAY"})]


def register_worker_gauges(runtime) -> None:
    if not runtime.enabled:
        return
    runtime.registry.register_gauge("curve.outbox.backlog", _outbox_backlog_observations)
    runtime.registry.register_gauge("curve.outbox.oldest_age", _outbox_oldest_age_observations)
    runtime.registry.register_gauge("curve.worker.heartbeat.age", _worker_heartbeat_observations)
