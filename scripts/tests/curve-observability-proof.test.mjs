// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.

import assert from "node:assert/strict";
import test from "node:test";

import {
  composeArguments,
  environmentContents,
  expectedPanelMetrics,
  parseCommand,
  sanitizeFoundationEvidence,
  validateProjectName,
} from "../curve-observability-proof.mjs";

test("accepts only the nine contracted proof commands", () => {
  for (const command of [
    "prepare",
    "up",
    "verify-health",
    "run-foundation",
    "verify-telemetry",
    "verify-alerts",
    "verify-path-failure",
    "verify-disablement",
    "cleanup",
  ]) {
    assert.equal(parseCommand(["node", "proof", command]), command);
  }
  assert.throws(() => parseCommand(["node", "proof", "deploy"]), /Usage:/);
});

test("builds an OTLP environment with only the approved local endpoint", () => {
  const key = "A".repeat(43);
  const contents = environmentContents({ mode: "OTLP", key, sourceRoot: "/tmp/curve-proof" });
  assert.match(contents, /CURVE_TELEMETRY_MODE=OTLP/);
  assert.match(contents, /CURVE_OTEL_EXPORTER_OTLP_ENDPOINT=http:\/\/otel-collector:4317/);
  assert.match(contents, /CURVE_OTEL_EXPORTER_OTLP_PROTOCOL=grpc/);
  assert.match(contents, /CURVE_OTEL_EXPORTER_OTLP_INSECURE=true/);
  assert.match(contents, /CURVE_TELEMETRY_SCOPE_KEY_ID=local-dev-v1/);
  assert.match(contents, /CURVE_GRAFANA_HOST_PORT=3001/);
  assert.match(contents, new RegExp(`CURVE_TELEMETRY_SCOPE_HMAC_KEY=${key}`));
  assert.doesNotMatch(contents, /https:\/\//);
});

test("allows an explicit loopback Grafana port when Plane Admin owns the default", () => {
  const contents = environmentContents({
    mode: "OTLP",
    key: "A".repeat(43),
    sourceRoot: "/tmp/curve-proof",
    grafanaHostPort: "3002",
  });
  assert.match(contents, /CURVE_GRAFANA_HOST_PORT=3002/);
  assert.throws(
    () =>
      environmentContents({
        mode: "OTLP",
        key: "A".repeat(43),
        sourceRoot: "/tmp/curve-proof",
        grafanaHostPort: "70000",
      }),
    /invalid/
  );
});

test("builds a fail-closed disabled environment without endpoint or key material", () => {
  const contents = environmentContents({ mode: "DISABLED", key: "ignored", sourceRoot: "/tmp/curve-proof" });
  assert.match(contents, /CURVE_TELEMETRY_MODE=DISABLED/);
  assert.match(contents, /CURVE_OTEL_EXPORTER_OTLP_ENDPOINT=\n/);
  assert.match(contents, /CURVE_TELEMETRY_SCOPE_HMAC_KEY=\n/);
  assert.doesNotMatch(contents, /ignored/);
});

test("compose invocation reuses the existing Plane project and exact two-file overlay", () => {
  const args = composeArguments({ stackRoot: "/tmp/plane-stack", args: ["config", "--quiet"] });
  assert.deepEqual(args.slice(0, 4), ["compose", "--project-name", "plane", "--env-file"]);
  assert.match(args[4], /\.curve-local\/observability\.env$/);
  assert.deepEqual(args.slice(5, 8), ["-f", "/tmp/plane-stack/docker-compose-local.yml", "-f"]);
  assert.match(args[8], /docker-compose-curve\.yml$/);
  assert.deepEqual(args.slice(9), ["--profile", "curve", "--profile", "curve-observability", "config", "--quiet"]);
});

test("project names are bounded before any Docker mutation", () => {
  assert.equal(validateProjectName("plane"), "plane");
  assert.equal(validateProjectName("curve-m0-s5b"), "curve-m0-s5b");
  for (const invalid of ["Plane", "../plane", "plane project", "", "a".repeat(64)]) {
    assert.throws(() => validateProjectName(invalid), /invalid/);
  }
});

test("foundation evidence removes operation and workflow identifiers", () => {
  const entry = {
    operation_id: "11111111-1111-4111-8111-111111111111",
    workflow_id: "curve-workflow-secret",
    status: "SUCCEEDED",
    version: 4,
    history_sha256: "a".repeat(64),
    evidence: { operations: 1, audit: 4 },
  };
  const evidence = sanitizeFoundationEvidence({
    schema_version: "curve-temporal-proof/v1",
    success: entry,
    cancellation: { ...entry, status: "CANCELLED" },
    durable_cancellation: { ...entry, status: "CANCELLED" },
    duplicate_start_rejected: true,
    history_replay_passed: true,
    sentinel_absent_from_histories: true,
  });
  const serialized = JSON.stringify(evidence);
  assert.doesNotMatch(serialized, /operation_id|workflow_id|11111111|curve-workflow-secret/);
  assert.equal(evidence.success.status, "SUCCEEDED");
  assert.equal(evidence.cancellation.status, "CANCELLED");
});

test("the ten dashboard query inputs are explicit and unique", () => {
  assert.equal(expectedPanelMetrics.length, 10);
  assert.equal(new Set(expectedPanelMetrics).size, 10);
  assert.deepEqual(expectedPanelMetrics, [
    "curve_operation_started_total",
    "curve_operation_completed_total",
    "curve_operation_duration_seconds_bucket",
    "curve_outbox_backlog",
    "curve_outbox_oldest_age_seconds",
    "curve_activity_retry_total",
    "curve_worker_heartbeat_age_seconds",
    "curve_sse_connections",
    "curve_audit_append_total",
    "curve_sse_resume_total",
  ]);
});
