# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource


class ProviderEventContractError(ValueError):
    """Raised when a provider event is outside the pinned aggregate contract."""


_CONTRACT_DIRECTORY = Path(__file__).resolve().parents[1] / "contracts"
_SCHEMA_DIRECTORY = _CONTRACT_DIRECTORY / "schemas"
_MANIFEST_PATH = _CONTRACT_DIRECTORY / "providers" / "m0-s9a-provider-registry-v1.json"
PROVIDER_CONNECTION_EVENT_SCHEMA = (
    "https://curve.x3m.internal/contracts/schemas/provider-connection-event-v1.schema.json"
)
PROVIDER_RECONCILIATION_EVENT_SCHEMA = (
    "https://curve.x3m.internal/contracts/schemas/provider-reconciliation-event-v1.schema.json"
)


@lru_cache(maxsize=1)
def _event_contracts():
    schemas = [json.loads(path.read_text()) for path in _SCHEMA_DIRECTORY.glob("*.schema.json")]
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )
    schemas_by_id = {schema["$id"]: schema for schema in schemas}
    manifest = json.loads(_MANIFEST_PATH.read_text())
    required_events = frozenset(manifest["required_events"])
    contracts: dict[tuple[str, str], tuple[str, Draft202012Validator]] = {}
    for contract in manifest["event_payload_contracts"]:
        aggregate_type = contract["aggregate_type"]
        schema_uri = contract["payload_schema"]
        schema = schemas_by_id.get(schema_uri)
        if schema is None:
            raise ProviderEventContractError("provider event payload schema is unavailable")
        validator = Draft202012Validator(schema, registry=registry)
        for event_type in contract["event_types"]:
            key = (aggregate_type, event_type)
            if key in contracts:
                raise ProviderEventContractError("provider event payload contract is ambiguous")
            contracts[key] = (schema_uri, validator)
    return required_events, contracts


def validate_provider_event_payload(*, aggregate_type: str, event_type: str, payload: dict) -> str:
    """Validate one closed payload and return its exact schema URI."""

    try:
        required_events, contracts = _event_contracts()
        if event_type not in required_events:
            raise ProviderEventContractError("provider event type is not allowlisted")
        schema_uri, validator = contracts[(aggregate_type, event_type)]
        validator.validate(payload)
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        if isinstance(error, ProviderEventContractError):
            raise
        raise ProviderEventContractError("provider event payload does not satisfy its contract") from None
    return schema_uri
