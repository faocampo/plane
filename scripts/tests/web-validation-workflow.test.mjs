// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const workflow = readFileSync(
  new URL("../../.github/workflows/pull-request-build-lint-web-apps.yml", import.meta.url),
  "utf8"
);

test("integration checks target Curve while preview stays an upstream tracking branch", () => {
  for (const file of [
    "pull-request-build-lint-web-apps.yml",
    "pull-request-build-lint-api.yml",
    "copyright-check.yml",
    "codeql.yml",
    "i18n-sync-check.yml",
    "react-doctor.yml",
  ]) {
    const source = readFileSync(new URL(`../../.github/workflows/${file}`, import.meta.url), "utf8");
    assert.ok(source.includes("curve-integration"), file);
    assert.doesNotMatch(source, /branches:[\s\S]*?\bpreview\b/, file);
  }
});

test("manual runs are declared and all three entry jobs allow explicit dispatch", () => {
  assert.match(workflow, /  workflow_dispatch:/);
  const conditions = [...workflow.matchAll(/    if: \|\n([\s\S]*?)(?=    env:)/g)];
  assert.equal(conditions.length, 3);
  for (const [, condition] of conditions) {
    assert.equal(
      condition.replace(/\s+/g, " ").trim(),
      "github.event_name == 'workflow_dispatch' || ( github.event.pull_request.draft == false && github.event.pull_request.requested_reviewers != null )"
    );
  }
});

test("manual runs select the full package graph and PRs alone use affected selection", () => {
  assert.match(workflow, /VALIDATION_SCOPE: \$\{\{ github\.event_name == 'pull_request' && '--affected' \|\| '' \}\}/);
  for (const command of ["check:format", "build", "check:lint", "check:types"]) {
    assert.ok(workflow.includes(`run: pnpm turbo run ${command} $VALIDATION_SCOPE`));
  }
  assert.equal((workflow.match(/--affected/g) ?? []).length, 1);
});

test("type validation requires successful build and every job uses a compatible Node release", () => {
  assert.match(workflow, /  check-types:\n[\s\S]*?    needs: build/);
  assert.equal((workflow.match(/node-version: "22\.18\.0"/g) ?? []).length, 4);
  assert.equal((workflow.match(/run: pnpm install --frozen-lockfile/g) ?? []).length, 4);
});

test("draft PRs retain their gate and ready-for-review remains a trigger", () => {
  assert.match(workflow, /      - "ready_for_review"/);
  assert.equal((workflow.match(/github\.event\.pull_request\.draft == false/g) ?? []).length, 3);
});
