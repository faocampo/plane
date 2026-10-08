// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const workflow = readFileSync(
  new URL("../../.github/workflows/pull-request-build-lint-api.yml", import.meta.url),
  "utf8"
);
const runner = readFileSync(new URL("../../apps/api/plane/curve/tests/run_ci_suite.py", import.meta.url), "utf8");

test("Curve CI starts its complete service set before a dependency-bounded run", () => {
  const start = workflow.indexOf("up -d --wait test-db test-redis test-mq");
  const run = workflow.indexOf("run --no-deps --rm --build");
  assert.ok(start >= 0 && run > start);
  assert.doesNotMatch(workflow, /up[^\n]*test-minio/);
});

test("Curve CI preserves the full backend suite, app initialization and migration check", () => {
  assert.match(runner, /import plane/);
  assert.match(runner, /pytest\.main/);
  assert.match(workflow, /python plane\/curve\/tests\/run_ci_suite\.py/);
  assert.match(workflow, /test-group: \[core, manual-planning, scope-regression\]/);
  assert.match(workflow, /fail-fast: false/);
  assert.match(workflow, /run_ci_suite\.py host-doubles/);
  assert.match(workflow, /python manage\.py makemigrations --check --dry-run/);
  assert.doesNotMatch(workflow, /--ignore|--deselect|continue-on-error/);
  assert.match(workflow, /PYTHONPATH=\/code:\/code\/plane\/curve:/);
});

test("Curve CI retains explicit dispatch, the draft gate and unconditional cleanup", () => {
  assert.match(workflow, /workflow_dispatch:/);
  assert.match(workflow, /github\.event\.pull_request\.draft == false/);
  assert.match(workflow, /if: always\(\)/);
  assert.match(workflow, /down -v --remove-orphans/);
});

test("API lint validates the checked-out source without rewriting model registrations", () => {
  assert.match(workflow, /run: uv run --no-sync ruff check \./);
  assert.doesNotMatch(workflow, /ruff check --fix/);
});
