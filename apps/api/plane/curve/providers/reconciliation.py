# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import math
import time
from dataclasses import dataclass
from typing import Callable

from plane.curve.providers.types import (
    MAX_RECONCILIATION_ATTEMPTS,
    NormalizedProviderError,
    ProviderAdapter,
    ProviderAdapterError,
    ProviderCallContext,
    ProviderErrorCode,
    ProviderObservationRef,
    ProviderReconciliationObservation,
)


class ProviderReconciliationExecutionError(RuntimeError):
    def __init__(self, error: NormalizedProviderError, attempts: int) -> None:
        self.error = error
        self.attempts = attempts
        super().__init__(error.code.value)


class ProviderReconciliationCancelled(ProviderReconciliationExecutionError):
    pass


class ProviderReconciliationDeadlineExceeded(ProviderReconciliationExecutionError):
    pass


class ProviderReconciliationFailed(ProviderReconciliationExecutionError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderReconciliationResult:
    observation: ProviderReconciliationObservation
    attempts: int


def _is_cancelled(context: ProviderCallContext) -> bool:
    try:
        cancelled = context.cancellation_token.is_cancelled()
    except Exception:
        return True
    return cancelled if type(cancelled) is bool else True


def _guard_execution(
    context: ProviderCallContext,
    *,
    attempts: int,
    monotonic: Callable[[], float],
) -> None:
    if _is_cancelled(context):
        raise ProviderReconciliationCancelled(
            NormalizedProviderError(ProviderErrorCode.TERMINAL),
            attempts,
        )
    try:
        current_monotonic = monotonic()
    except Exception:
        current_monotonic = context.deadline_monotonic
    if (
        not isinstance(current_monotonic, (int, float))
        or isinstance(current_monotonic, bool)
        or not math.isfinite(current_monotonic)
        or current_monotonic >= context.deadline_monotonic
    ):
        raise ProviderReconciliationDeadlineExceeded(
            NormalizedProviderError(ProviderErrorCode.TRANSIENT),
            attempts,
        )


def _fail(error_code: ProviderErrorCode, attempts: int) -> None:
    raise ProviderReconciliationFailed(NormalizedProviderError(error_code), attempts)


def _validate_adapter_context(adapter: ProviderAdapter, context: ProviderCallContext) -> None:
    try:
        matches = (
            adapter.adapter_key == context.adapter_key
            and adapter.provider_type == context.provider_type
            and adapter.adapter_version == context.adapter_version
        )
    except Exception:
        matches = False
    if not matches:
        _fail(ProviderErrorCode.NOT_SUPPORTED, 0)


def _validate_observation(
    context: ProviderCallContext,
    previous: ProviderObservationRef | None,
    observation: ProviderReconciliationObservation,
    attempts: int,
) -> None:
    capability = observation.capability_observation
    if (
        capability.workspace_id != context.workspace_id
        or capability.connection_id != context.connection_id
        or capability.provider_type != context.provider_type
        or capability.adapter_key != context.adapter_key
        or capability.adapter_version != context.adapter_version
    ):
        _fail(ProviderErrorCode.TERMINAL, attempts)
    expected_changed = previous is None or previous.capability_digest != capability.capability_digest
    if observation.changed is not expected_changed:
        _fail(ProviderErrorCode.TERMINAL, attempts)


def reconcile_with_retry(
    adapter: ProviderAdapter,
    context: ProviderCallContext,
    previous: ProviderObservationRef | None,
    *,
    monotonic: Callable[[], float] = time.monotonic,
) -> ProviderReconciliationResult:
    _validate_adapter_context(adapter, context)

    for attempt in range(1, MAX_RECONCILIATION_ATTEMPTS + 1):
        _guard_execution(context, attempts=attempt - 1, monotonic=monotonic)
        try:
            observation = adapter.reconcile(context, previous)
        except ProviderAdapterError as error:
            normalized_error = error.error
        except Exception:
            normalized_error = NormalizedProviderError(ProviderErrorCode.TERMINAL)
        else:
            _guard_execution(context, attempts=attempt, monotonic=monotonic)
            try:
                _validate_observation(context, previous, observation, attempt)
            except ProviderReconciliationFailed:
                raise
            except Exception:
                _fail(ProviderErrorCode.TERMINAL, attempt)
            return ProviderReconciliationResult(observation=observation, attempts=attempt)

        _guard_execution(context, attempts=attempt, monotonic=monotonic)
        if not normalized_error.retryable or attempt == MAX_RECONCILIATION_ATTEMPTS:
            raise ProviderReconciliationFailed(normalized_error, attempt) from None

    raise AssertionError("unreachable reconciliation attempt state")
