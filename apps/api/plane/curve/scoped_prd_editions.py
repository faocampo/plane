# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Explicit scoped review editions, selected by current server-owned Initiative."""

from dataclasses import dataclass

from .prd_commands import PrdCommandError


@dataclass(frozen=True)
class ScopedEdition:
    number: int
    gates: tuple[str, ...]

    @property
    def schema_version(self):
        return f"curve.scoped-prd/v{self.number}-candidate"

    @property
    def policy_edition(self):
        return f"EXACT_EXISTING_WORK_SCOPED_PRD_V{self.number}"

    @property
    def command_prefix(self):
        return f"SCOPED_PRD_V{self.number}_"


LEGACY = ScopedEdition(1, ("CODE_READINESS", "PLAN_APPROVAL", "PRD_APPROVAL"))
TWO_STAGE = ScopedEdition(2, ("PLAN_APPROVAL", "PRD_APPROVAL"))


def edition_for_schema(version):
    for edition in (LEGACY, TWO_STAGE):
        if version == edition.schema_version:
            return edition
    raise PrdCommandError("SCOPED_PRD_INVALID", 422)


def edition_for_initiative(initiative):
    if initiative.schema_version == "1.2":
        return TWO_STAGE
    if initiative.schema_version in ("1.0", "1.1"):
        return LEGACY
    raise PrdCommandError("SCOPED_PRD_UNAVAILABLE", 404)
