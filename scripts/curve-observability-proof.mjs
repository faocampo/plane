#!/usr/bin/env node

// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.

import { execFileSync, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { chmod, mkdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = fileURLToPath(new URL("../", import.meta.url));
const stateDirectory = join(repositoryRoot, ".curve-local");
const environmentPath = join(stateDirectory, "observability.env");
const receiptPath = join(stateDirectory, "observability-receipt.json");
const bindingPath = join(repositoryRoot, "apps/api/plane/curve/contracts/observability/obs-bind-001-local-v1.json");
const projectName = process.env.CURVE_PROOF_COMPOSE_PROJECT || "plane";
const commandNames = new Set([
  "prepare",
  "up",
  "verify-health",
  "run-foundation",
  "verify-telemetry",
  "verify-alerts",
  "verify-path-failure",
  "verify-disablement",
  "cleanup",
]);

export const expectedPanelMetrics = Object.freeze([
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

export function validateProjectName(value) {
  if (!/^[a-z0-9][a-z0-9_-]{0,62}$/.test(value)) {
    throw new Error("Curve proof Compose project name is invalid");
  }
  return value;
}

export function parseCommand(argv) {
  const command = argv[2];
  if (!commandNames.has(command)) {
    throw new Error(`Usage: node scripts/curve-observability-proof.mjs ${[...commandNames].join("|")}`);
  }
  return command;
}

function existingStackRoot() {
  if (process.env.CURVE_LOCAL_STACK_ROOT) return process.env.CURVE_LOCAL_STACK_ROOT;
  const commonGitDirectory = execFileSync("git", ["rev-parse", "--git-common-dir"], {
    cwd: repositoryRoot,
    encoding: "utf8",
  }).trim();
  return dirname(commonGitDirectory);
}

export function composeArguments({ includeObservability = true, args = [], stackRoot = existingStackRoot() } = {}) {
  validateProjectName(projectName);
  const result = [
    "compose",
    "--project-name",
    projectName,
    "--env-file",
    environmentPath,
    "-f",
    join(stackRoot, "docker-compose-local.yml"),
    "-f",
    join(repositoryRoot, "docker-compose-curve.yml"),
    "--profile",
    "curve",
  ];
  if (includeObservability) result.push("--profile", "curve-observability");
  return [...result, ...args];
}

export function environmentContents({
  mode,
  key = "",
  sourceRoot = repositoryRoot,
  grafanaHostPort = process.env.CURVE_GRAFANA_HOST_PORT || "3001",
}) {
  if (!new Set(["OTLP", "DISABLED"]).has(mode)) throw new Error("Unsupported Curve proof telemetry mode");
  if (!/^\d{4,5}$/.test(String(grafanaHostPort)) || Number(grafanaHostPort) > 65535) {
    throw new Error("Curve proof Grafana host port is invalid");
  }
  const values = {
    CURVE_SOURCE_ROOT: sourceRoot,
    CURVE_GRAFANA_HOST_PORT: grafanaHostPort,
    CURVE_TELEMETRY_MODE: mode,
    CURVE_TELEMETRY_SCOPE_HMAC_KEY: mode === "OTLP" ? key : "",
    CURVE_TELEMETRY_SCOPE_KEY_ID: mode === "OTLP" ? "local-dev-v1" : "",
    CURVE_OTEL_EXPORTER_OTLP_ENDPOINT: mode === "OTLP" ? "http://otel-collector:4317" : "",
    CURVE_OTEL_EXPORTER_OTLP_PROTOCOL: mode === "OTLP" ? "grpc" : "",
    CURVE_OTEL_EXPORTER_OTLP_INSECURE: mode === "OTLP" ? "true" : "",
  };
  return `${Object.entries(values)
    .map(([name, value]) => `${name}=${String(value).replaceAll("\\", "\\\\").replaceAll("\n", "")}`)
    .join("\n")}\n`;
}

const summarizeFoundationEntry = (entry) => ({
  status: entry.status,
  version: entry.version,
  history_sha256: entry.history_sha256,
  evidence: entry.evidence,
});

export function sanitizeFoundationEvidence(value) {
  return {
    schema_version: value.schema_version,
    success: summarizeFoundationEntry(value.success),
    cancellation: summarizeFoundationEntry(value.cancellation),
    durable_cancellation: summarizeFoundationEntry(value.durable_cancellation),
    duplicate_start_rejected: value.duplicate_start_rejected,
    history_replay_passed: value.history_replay_passed,
    sentinel_absent_from_histories: value.sentinel_absent_from_histories,
  };
}

function run(program, args, { capture = false, allowFailure = false } = {}) {
  const result = spawnSync(program, args, {
    cwd: repositoryRoot,
    encoding: "utf8",
    stdio: capture ? "pipe" : "inherit",
  });
  if (result.error) throw result.error;
  if (result.status !== 0 && !allowFailure) {
    const diagnostic = [result.stdout, result.stderr].filter(Boolean).join("\n").trim();
    throw new Error(`${program} exited ${result.status}${diagnostic ? `: ${diagnostic}` : ""}`);
  }
  return result;
}

function compose(args, options) {
  return run("docker", composeArguments({ args }), options);
}

function composeCore(args, options) {
  return run("docker", composeArguments({ includeObservability: false, args }), options);
}

function parseLastJsonLine(output) {
  const lines = output
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  for (const line of lines.toReversed()) {
    try {
      return JSON.parse(line);
    } catch {
      continue;
    }
  }
  throw new Error("Curve proof command did not emit JSON evidence");
}

async function writeEnvironment(mode, key = "") {
  await mkdir(stateDirectory, { recursive: true, mode: 0o700 });
  await chmod(stateDirectory, 0o700);
  await writeFile(environmentPath, environmentContents({ mode, key }), { mode: 0o600 });
  await chmod(environmentPath, 0o600);
}

async function grafanaHostUrl() {
  const contents = await readFile(environmentPath, "utf8");
  const port = contents.match(/^CURVE_GRAFANA_HOST_PORT=(\d+)$/m)?.[1];
  if (!port) throw new Error("Curve proof Grafana host port is unavailable");
  return `http://127.0.0.1:${port}`;
}

async function requirePrepared() {
  const metadata = await stat(environmentPath);
  if ((metadata.mode & 0o777) !== 0o600) throw new Error("Curve proof environment file must use mode 0600");
}

async function request(url, { json = true } = {}) {
  const response = await fetch(url, { signal: AbortSignal.timeout(5_000) });
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
  return json ? response.json() : response.text();
}

async function waitFor(label, probe, { timeoutMillis = 120_000, intervalMillis = 2_000 } = {}) {
  const deadline = Date.now() + timeoutMillis;
  let lastError;

  const poll = async () => {
    if (Date.now() >= deadline) {
      throw new Error(`${label} did not become ready${lastError ? `: ${lastError.message}` : ""}`);
    }
    try {
      const value = await probe();
      if (value) return value;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMillis));
    return poll();
  };

  return poll();
}

async function prometheusQuery(expression) {
  const response = await request(`http://127.0.0.1:9091/api/v1/query?query=${encodeURIComponent(expression)}`);
  if (response.status !== "success") throw new Error(`Prometheus query failed for ${expression}`);
  return response.data.result;
}

async function prepare() {
  const binding = JSON.parse(await readFile(bindingPath, "utf8"));
  if (binding.binding_id !== "OBS-BIND-001" || binding.decision.status !== "DECIDED_LOCAL_ONLY") {
    throw new Error("Approved local observability binding is unavailable");
  }
  const key = randomBytes(32).toString("base64url");
  await writeEnvironment("OTLP", key);
  const receipt = {
    schema_version: "curve-local-observability-receipt/v1",
    phase: "PREPARED",
    project: validateProjectName(projectName),
    curve_revision: "43480ca8463d0b40d436145aeb19fbbc8c2be472",
    context_digest: "sha256:36933053249f2159d2b768e3ff62c3e114a587a5fa650df9b262b4f7d9b28d3b",
    plane_base_revision: "39920769daf78fce29a10c7f4e4bb8779671b004",
    grafana_host_port: process.env.CURVE_GRAFANA_HOST_PORT || "3001",
    grafana_binding_default_port: "3001",
    prepared_at: new Date().toISOString(),
  };
  await writeFile(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, { mode: 0o600 });
  console.log(JSON.stringify(receipt));
}

async function up() {
  await requirePrepared();
  compose(["config", "--quiet"]);
  compose([
    "up",
    "-d",
    "--no-deps",
    "--build",
    "--force-recreate",
    "otel-collector",
    "prometheus",
    "grafana",
    "api",
    "curve-worker",
  ]);
  console.log(JSON.stringify({ phase: "UP", project: projectName, telemetry_mode: "OTLP" }));
}

async function verifyHealth() {
  await requirePrepared();
  const collector = await waitFor("Collector health", () => request("http://127.0.0.1:13133/"));
  const prometheus = await waitFor("Prometheus readiness", () =>
    request("http://127.0.0.1:9091/-/ready", { json: false })
  );
  const grafanaBase = await grafanaHostUrl();
  const grafana = await waitFor("Grafana health", () => request(`${grafanaBase}/api/health`));
  const targets = await waitFor("Prometheus scrape paths", async () => {
    const response = await request("http://127.0.0.1:9091/api/v1/targets");
    const selected = response.data.activeTargets.filter(({ labels }) =>
      new Set(["curve-otel-metrics", "otel-collector-self"]).has(labels.job)
    );
    return selected.length === 2 && selected.every(({ health }) => health === "up") ? selected : null;
  });
  console.log(
    JSON.stringify({
      phase: "HEALTHY",
      collector_status: collector.status || "ready",
      prometheus_status: prometheus.trim(),
      grafana_database: grafana.database,
      scrape_jobs: targets.map(({ labels }) => labels.job).toSorted(),
    })
  );
}

async function runFoundation() {
  await requirePrepared();
  const foundation = compose(["exec", "-T", "curve-worker", "python", "-m", "plane.curve.temporal.proof", "run"], {
    capture: true,
  });
  const telemetry = compose(["exec", "-T", "api", "python", "-m", "plane.curve.observability.local_proof"], {
    capture: true,
  });
  const evidence = {
    phase: "FOUNDATION_COMPLETE",
    foundation: sanitizeFoundationEvidence(parseLastJsonLine(foundation.stdout)),
    telemetry: parseLastJsonLine(telemetry.stdout),
  };
  console.log(JSON.stringify(evidence));
}

async function verifyTelemetry() {
  await requirePrepared();
  const observed = Object.fromEntries(
    await Promise.all(
      expectedPanelMetrics.map(async (metric) => [
        metric,
        await waitFor(metric, async () => {
          const result = await prometheusQuery(metric);
          return result.length > 0 ? result.length : null;
        }),
      ])
    )
  );
  const datasource = await waitFor("Grafana datasource", () =>
    grafanaHostUrl().then((base) => request(`${base}/api/datasources/uid/prometheus-local`))
  );
  const dashboard = await waitFor("Grafana dashboard", () =>
    grafanaHostUrl().then((base) => request(`${base}/api/dashboards/uid/curve-m0-operations`))
  );
  if (datasource.uid !== "prometheus-local" || datasource.url !== "http://prometheus:9090") {
    throw new Error("Grafana Prometheus datasource differs from OBS-BIND-001");
  }
  if (dashboard.meta?.folderUid !== "curve" || dashboard.dashboard?.panels?.length !== 10) {
    throw new Error("Grafana Curve dashboard provisioning is incomplete");
  }
  const logs = compose(["logs", "--no-color", "otel-collector"], { capture: true }).stdout;
  for (const forbidden of [
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "CURVE_PROTECTED_SENTINEL_M0_S3",
  ]) {
    if (logs.includes(forbidden)) throw new Error("Collector logs contain a protected proof value");
  }
  console.log(
    JSON.stringify({
      phase: "TELEMETRY_VERIFIED",
      metrics: observed,
      dashboard_uid: dashboard.dashboard.uid,
      dashboard_panels: dashboard.dashboard.panels.length,
      datasource_uid: datasource.uid,
      protected_values_absent_from_collector_logs: true,
    })
  );
}

async function verifyAlerts() {
  await requirePrepared();
  const promtool = compose(
    [
      "run",
      "--rm",
      "--no-deps",
      "--entrypoint",
      "/bin/promtool",
      "prometheus",
      "test",
      "rules",
      "/etc/prometheus/tests/prometheus-alert-tests.yaml",
    ],
    { capture: true }
  );
  const rules = await request("http://127.0.0.1:9091/api/v1/rules?type=alert");
  const names = rules.data.groups.flatMap(({ rules: items }) => items.map(({ name }) => name)).toSorted();
  const expected = [
    "CURVE_AUDIT_APPEND_FAILURE",
    "CURVE_OPERATION_FAILURE_RATIO",
    "CURVE_OTEL_COLLECTOR_DOWN",
    "CURVE_OTEL_EXPORT_PATH_DOWN",
    "CURVE_OUTBOX_STUCK",
    "CURVE_WORKER_HEARTBEAT_STALE",
  ].toSorted();
  if (JSON.stringify(names) !== JSON.stringify(expected)) throw new Error("Prometheus loaded an unexpected alert set");
  console.log(
    JSON.stringify({
      phase: "ALERTS_VERIFIED",
      rules: names,
      promtool: promtool.stdout.includes("SUCCESS") ? "SUCCESS" : "PASSED",
      external_delivery: "DISABLED",
    })
  );
}

async function verifyPathFailure() {
  await requirePrepared();
  compose(["stop", "otel-collector"]);
  try {
    await Promise.all(
      ["otel-collector-self", "curve-otel-metrics"].map((job) =>
        waitFor(`${job} scrape failure`, async () => {
          const result = await prometheusQuery(`up{job="${job}"} == 0`);
          return result.length > 0 ? true : null;
        })
      )
    );
    await Promise.all(
      ["CURVE_OTEL_COLLECTOR_DOWN", "CURVE_OTEL_EXPORT_PATH_DOWN"].map((alert) =>
        waitFor(
          `${alert} firing`,
          async () => {
            const result = await prometheusQuery(`ALERTS{alertname="${alert}",alertstate="firing"}`);
            return result.length > 0 ? true : null;
          },
          { timeoutMillis: 90_000 }
        )
      )
    );
  } finally {
    compose(["start", "otel-collector"]);
  }
  await waitFor("Collector recovery", () => request("http://127.0.0.1:13133/"));
  await Promise.all(
    ["otel-collector-self", "curve-otel-metrics"].map((job) =>
      waitFor(`${job} scrape recovery`, async () => {
        const result = await prometheusQuery(`up{job="${job}"} == 1`);
        return result.length > 0 ? true : null;
      })
    )
  );
  console.log(
    JSON.stringify({
      phase: "PATH_FAILURE_VERIFIED",
      firing_alerts: ["CURVE_OTEL_COLLECTOR_DOWN", "CURVE_OTEL_EXPORT_PATH_DOWN"],
      collector_recovered: true,
    })
  );
}

async function verifyDisablement() {
  await requirePrepared();
  const before = await prometheusQuery("sum(curve_operation_started_total)");
  const beforeValue = before[0]?.value?.[1] ?? "0";
  await writeEnvironment("DISABLED");
  composeCore(["up", "-d", "--no-deps", "--build", "--force-recreate", "api", "curve-worker"]);
  await waitFor("disabled Curve worker", async () => {
    const result = composeCore(["ps", "--format", "json", "curve-worker"], { capture: true });
    return result.stdout.includes("healthy") ? true : null;
  });
  const foundation = composeCore(["exec", "-T", "curve-worker", "python", "-m", "plane.curve.temporal.proof", "run"], {
    capture: true,
  });
  await new Promise((resolve) => setTimeout(resolve, 10_000));
  const after = await prometheusQuery("sum(curve_operation_started_total)");
  const afterValue = after[0]?.value?.[1] ?? "0";
  if (afterValue !== beforeValue) throw new Error("Disabled Curve execution changed exported operation telemetry");
  const workerLogs = composeCore(["logs", "--no-color", "--since", "2m", "curve-worker"], { capture: true }).stdout;
  if (workerLogs.includes("CURVE_TELEMETRY_EXPORT_FAILED")) {
    throw new Error("Disabled Curve worker attempted telemetry export");
  }
  console.log(
    JSON.stringify({
      phase: "DISABLEMENT_VERIFIED",
      foundation: sanitizeFoundationEvidence(parseLastJsonLine(foundation.stdout)),
      operation_metric_unchanged: true,
      exporter_failure_absent: true,
      telemetry_mode: "DISABLED",
    })
  );
}

async function cleanup() {
  await requirePrepared();
  compose(["stop", "grafana", "prometheus", "otel-collector"], { allowFailure: true });
  compose(["rm", "-f", "grafana", "prometheus", "otel-collector"], { allowFailure: true });
  const volumes = [`${projectName}_curve_prometheus_data`, `${projectName}_curve_grafana_data`];
  for (const volume of volumes) run("docker", ["volume", "rm", volume], { capture: true, allowFailure: true });
  await rm(stateDirectory, { recursive: true, force: true });
  console.log(
    JSON.stringify({
      phase: "CLEANED",
      project: projectName,
      removed_services: ["grafana", "otel-collector", "prometheus"],
      removed_volumes: volumes,
      base_plane_services_preserved: true,
    })
  );
}

export async function main(argv = process.argv) {
  const command = parseCommand(argv);
  const actions = {
    prepare,
    up,
    "verify-health": verifyHealth,
    "run-foundation": runFoundation,
    "verify-telemetry": verifyTelemetry,
    "verify-alerts": verifyAlerts,
    "verify-path-failure": verifyPathFailure,
    "verify-disablement": verifyDisablement,
    cleanup,
  };
  await actions[command]();
}

if (fileURLToPath(import.meta.url) === process.argv[1]) {
  main().catch((error) => {
    console.error(`Curve observability proof failed: ${error.message}`);
    process.exitCode = 1;
  });
}
