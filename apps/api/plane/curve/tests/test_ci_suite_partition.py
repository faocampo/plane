# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from itertools import combinations

import pytest

from plane.curve.tests.run_ci_suite import GROUPS, MANUAL_DIRECTORIES, ROOT, SCOPE_FILES, partition


def test_ci_partitions_cover_every_test_file_exactly_once():
    groups = partition()
    assert tuple(groups) == GROUPS
    sets = [set(paths) for paths in groups.values()]
    assert set.union(*sets) == set(ROOT.rglob("test_*.py"))
    for first, second in combinations(sets, 2):
        assert first.isdisjoint(second)


def test_native_group_boundaries_and_coverage_guard_are_preserved():
    groups = partition()
    assert {path.relative_to(ROOT).parts[0] for path in groups["manual-planning"]} == MANUAL_DIRECTORIES
    assert {path.name for path in groups["scope-regression"]} == SCOPE_FILES
    assert ROOT / "test_ci_suite_partition.py" in groups["core"]


def test_new_test_files_default_to_core(tmp_path):
    (tmp_path / "manual_plan_v2").mkdir()
    (tmp_path / "manual_plan_v2" / "test_manual.py").touch()
    (tmp_path / "test_scope_proposal_api.py").touch()
    new_test = tmp_path / "test_future_feature.py"
    new_test.touch()
    assert partition(tmp_path)["core"] == [new_test]


def test_empty_partition_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="must contain test files"):
        partition(tmp_path)
