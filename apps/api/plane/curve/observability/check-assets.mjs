// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.

import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

const repositoryRoot = new URL("../../../../../", import.meta.url);
const manifestUrl = new URL("apps/api/plane/curve/contracts/observability/m0-s5-telemetry-v1.json", repositoryRoot);
const manifestBytes = await readFile(manifestUrl);
const digest = createHash("sha256").update(manifestBytes).digest("hex");
if (digest !== "8ba95e5e605188e829df03374114eb2ec0d2cbea0218f1d286198cbbb2d34d9b") {
  throw new Error("Curve telemetry manifest digest mismatch");
}
const manifest = JSON.parse(manifestBytes);
const dashboard = JSON.parse(await readFile(new URL(manifest.dashboard.implementation_path, repositoryRoot), "utf8"));
const alertDocument = JSON.parse(await readFile(new URL(manifest.alerts.implementation_path, repositoryRoot), "utf8"));

const unique = (values) => new Set(values).size === values.length;
const observedPanels = dashboard.panels.map(({ id, title, targets }) => ({ id, title, query: targets?.[0]?.expr }));
if (
  !unique(observedPanels.map(({ id }) => id)) ||
  JSON.stringify(observedPanels) !== JSON.stringify(manifest.dashboard.panels)
) {
  throw new Error("Curve dashboard panels differ from the telemetry manifest");
}
if (dashboard.templating?.list?.[0]?.name !== manifest.dashboard.datasource_variable) {
  throw new Error("Curve dashboard datasource variable differs from the telemetry manifest");
}

const observedRules = alertDocument.groups
  ?.flatMap(({ rules }) => rules ?? [])
  .map((rule) => ({
    id: rule.alert,
    severity: rule.labels?.severity,
    expression: rule.expr,
    for: rule.for,
    summary: rule.annotations?.summary,
  }));
if (
  !observedRules ||
  !unique(observedRules.map(({ id }) => id)) ||
  JSON.stringify(observedRules) !== JSON.stringify(manifest.alerts.rules)
) {
  throw new Error("Curve alert rules differ from the telemetry manifest");
}

const metricNames = new Set(
  manifest.metrics.filter(({ name }) => name !== "curve.telemetry.export.failure").map(({ name }) => name)
);
const translated = new Set();
for (const metric of manifest.metrics) {
  if (metric.name === "curve.telemetry.export.failure") continue;
  let name = metric.name.replaceAll(".", "_");
  if (metric.unit === "s") name += "_seconds";
  if (metric.instrument === "COUNTER") name += "_total";
  translated.add(name);
}
const queries = [...observedPanels.map(({ query }) => query), ...observedRules.map(({ expression }) => expression)];
for (const query of queries) {
  if (/(workspace_id|operation_id|event_id|workflow_id|correlation_id|telemetry_export_failure)/.test(query)) {
    throw new Error(`Curve PromQL contains a prohibited identifier or local-only metric: ${query}`);
  }
}
if (!queries.some((query) => query.includes("absent(curve_worker_heartbeat_age_seconds)"))) {
  throw new Error("Curve alert assets do not prove the absent-worker clause");
}
if (!queries.some((query) => query.includes('curve_operation_completed_total{curve_result="FAILED"}[5m]'))) {
  throw new Error("Curve alert assets do not contain the bounded five-minute failure ratio");
}
if (metricNames.size !== manifest.metrics.length - 1 || translated.size !== manifest.metrics.length - 1) {
  throw new Error("Curve metric names do not translate uniquely");
}

console.log(
  `Curve M0-S5 assets passed: ${observedPanels.length} panels and ${observedRules.length} alerts using ${manifest.dashboard.metric_translation_strategy}`
);
