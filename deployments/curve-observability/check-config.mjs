// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.

import { readFile } from "node:fs/promises";

const repositoryRoot = new URL("../../", import.meta.url);
const readText = (path) => readFile(new URL(path, repositoryRoot), "utf8");
const readJson = async (path) => JSON.parse(await readText(path));
const requireText = (contents, expected, source) => {
  if (!contents.includes(expected)) throw new Error(`${source} omits ${expected}`);
};

const binding = await readJson("apps/api/plane/curve/contracts/observability/obs-bind-001-local-v1.json");
const telemetry = await readJson("apps/api/plane/curve/contracts/observability/m0-s5-telemetry-v1.json");
const dashboard = await readJson("apps/api/plane/curve/observability/grafana/curve-m0-dashboard.json");
const applicationRules = await readJson("apps/api/plane/curve/observability/prometheus/curve-m0-alerts.yaml");
const pathRules = await readJson("deployments/curve-observability/curve-path-alerts.yaml");
const compose = await readText("docker-compose-curve.yml");
const collector = await readText("deployments/curve-observability/otel-collector.yaml");
const prometheus = await readText("deployments/curve-observability/prometheus.yml");
const datasource = await readText("deployments/curve-observability/grafana/provisioning/datasources/prometheus.yaml");
const dashboardProvider = await readText("deployments/curve-observability/grafana/provisioning/dashboards/curve.yaml");

if (
  binding.schema_version !== "curve.observability-binding/v1" ||
  binding.binding_id !== "OBS-BIND-001" ||
  binding.decision.status !== "DECIDED_LOCAL_ONLY" ||
  binding.topology.network !== "dev_env" ||
  binding.topology.host_bind_address !== "127.0.0.1"
) {
  throw new Error("OBS-BIND-001 local authority is unavailable");
}

for (const image of Object.values(binding.images)) requireText(compose, image.reference, "Compose overlay");
for (const service of ["otel-collector:", "prometheus:", "grafana:"]) {
  requireText(compose, service, "Compose overlay");
}
for (const port of [
  "127.0.0.1:4317:4317",
  "127.0.0.1:13133:13133",
  "127.0.0.1:9091:9090",
  "127.0.0.1:${CURVE_GRAFANA_HOST_PORT:-3001}:3000",
]) {
  requireText(compose, port, "Compose loopback bindings");
}
for (const variable of [
  "CURVE_OTEL_EXPORTER_OTLP_ENDPOINT",
  "CURVE_OTEL_EXPORTER_OTLP_PROTOCOL",
  "CURVE_OTEL_EXPORTER_OTLP_INSECURE",
  "CURVE_TELEMETRY_SCOPE_HMAC_KEY",
  "CURVE_TELEMETRY_SCOPE_KEY_ID",
]) {
  if (compose.split(variable).length !== 5) {
    throw new Error(`Compose must bind ${variable} exactly once for the API and worker`);
  }
}
if (/ports:\s*[\s\S]{0,120}-\s*["']?(?!127\.0\.0\.1:)(?:4317|13133|9091|3001):/m.test(compose)) {
  throw new Error("Curve observability host ports must remain loopback-bound");
}
for (const volume of binding.persistence.volumes) requireText(compose, `${volume}:`, "Compose named volumes");
requireText(compose, "- curve-observability", "Compose profile");
requireText(compose, "- dev_env", "Compose network");

requireText(collector, "endpoint: 0.0.0.0:4317", "Collector OTLP receiver");
requireText(collector, "endpoint: 0.0.0.0:13133", "Collector health extension");
requireText(collector, "endpoint: 0.0.0.0:8889", "Collector Prometheus exporter");
requireText(collector, "translation_strategy: UnderscoreEscapingWithSuffixes", "Collector metric translation");
requireText(collector, "port: 8888", "Collector self-metrics");
requireText(collector, "- debug", "Collector local trace sink");
if (/https?:\/\//.test(collector)) throw new Error("Collector configuration contains an external URL");

for (const job of binding.prometheus.scrape_jobs) requireText(prometheus, `job_name: ${job}`, "Prometheus scrape jobs");
for (const value of [
  "regex: curve_outbox_backlog_ratio",
  "target_label: __name__",
  "replacement: curve_outbox_backlog",
]) {
  requireText(prometheus, value, "Prometheus dimensionless-gauge compatibility mapping");
}
for (const rule of ["curve-m0-alerts.yaml", "curve-path-alerts.yaml"]) {
  requireText(prometheus, rule, "Prometheus rule files");
}
if (/remote_(write|read)|alertmanagers:/m.test(prometheus)) {
  throw new Error("Local Prometheus configuration contains an external delivery path");
}

requireText(datasource, `uid: ${binding.grafana.datasource_uid}`, "Grafana datasource");
requireText(datasource, `url: ${binding.prometheus.internal_url}`, "Grafana datasource");
requireText(dashboardProvider, `folder: ${binding.grafana.folder_title}`, "Grafana dashboard provider");
requireText(dashboardProvider, `folderUid: ${binding.grafana.folder_uid}`, "Grafana dashboard provider");
requireText(dashboardProvider, "allowUiUpdates: false", "Grafana dashboard provider");

const panels = dashboard.panels ?? [];
if (panels.length !== 10 || new Set(panels.map(({ id }) => id)).size !== panels.length) {
  throw new Error("The provisioned Curve dashboard must contain ten unique panels");
}
if (dashboard.uid !== "curve-m0-operations" || dashboard.templating?.list?.[0]?.name !== "DS_PROMETHEUS") {
  throw new Error("The provisioned Curve dashboard identity differs from the telemetry contract");
}

const rules = [...applicationRules.groups, ...pathRules.groups].flatMap(({ rules: items }) => items ?? []);
const expectedRuleIds = [
  ...telemetry.alerts.rules.map(({ id }) => id),
  ...binding.path_health.required_rules,
].toSorted();
const observedRuleIds = rules.map(({ alert }) => alert).toSorted();
if (JSON.stringify(observedRuleIds) !== JSON.stringify(expectedRuleIds)) {
  throw new Error("The provisioned alert identifiers differ from the M0-S5 contracts");
}
if (rules.some((rule) => rule.labels?.severity !== "CRITICAL" && rule.labels?.severity !== "WARNING")) {
  throw new Error("The provisioned alert severities are outside the bounded local vocabulary");
}

console.log(
  `Curve M0-S5B local configuration passed: ${panels.length} panels, ${rules.length} alerts, and ${binding.prometheus.scrape_jobs.length} scrape paths`
);
