# Curve Local Observability

This directory implements `OBS-BIND-001` (approved local OpenTelemetry,
Prometheus, and Grafana binding) for the existing Plane Docker Compose stack.
It is a disposable development proof: Curve exports OTLP/gRPC without TLS to a
local Collector, the Collector exposes metrics to local Prometheus, and Grafana
loads the version-controlled `Curve` folder and dashboard.

## Prerequisites

- The existing Plane local stack is running under Compose project `plane`.
- The Curve profile is available and its Temporal service is healthy.
- Docker can pull the exact digest-pinned Collector, Prometheus, and Grafana
  images declared in `docker-compose-curve.yml` (Curve and local runtime
  service overlay).
- Host ports `4317`, `13133`, and `9091` are free. Grafana uses `3001` by
  default and supports a local override.

The proof runner discovers the main Plane checkout through Git's common
directory, then combines its `docker-compose-local.yml` (Plane local stack)
with the current worktree's `docker-compose-curve.yml` (Curve and local runtime
service overlay). It always reuses the existing `plane` Compose project.

## Run the proof

From the repository root:

```bash
node scripts/curve-observability-proof.mjs prepare
node scripts/curve-observability-proof.mjs up
node scripts/curve-observability-proof.mjs verify-health
node scripts/curve-observability-proof.mjs run-foundation
node scripts/curve-observability-proof.mjs verify-telemetry
node scripts/curve-observability-proof.mjs verify-alerts
node scripts/curve-observability-proof.mjs verify-path-failure
node scripts/curve-observability-proof.mjs verify-disablement
```

If port `3001` is occupied, choose another loopback port when preparing the
environment:

```bash
CURVE_GRAFANA_HOST_PORT=3003 \
  node scripts/curve-observability-proof.mjs prepare
```

The prepared environment and receipt are written below `.curve-local/` with
owner-only permissions. This directory is ignored by Git. The workspace-scope
HMAC key is generated for the proof and is never printed in the receipt.

## Acceptance evidence

The complete proof establishes:

1. Collector, Prometheus, Grafana, API, and Curve worker health.
2. A successful foundation operation, cancellation, durable cancellation,
   duplicate-start rejection, and deterministic history replay.
3. All ten metrics from `m0-s5-telemetry-v1.json` (M0 telemetry contract) in
   Prometheus and all ten panels in the provisioned Grafana dashboard.
4. Six local alert rules, including Collector and export-path failure signals.
5. Two distinct pseudonymous workspace scopes, a scope-key rotation result,
   and absence of raw workspace identifiers from exported telemetry.
6. Collector interruption detection and automatic recovery.
7. Successful application behavior with telemetry disabled and no metric
   increase after disablement.

Grafana is available at `http://127.0.0.1:3001` by default, Prometheus at
`http://127.0.0.1:9091`, and Collector health at
`http://127.0.0.1:13133`. The Grafana datasource UID is `prometheus-local`.

## Cleanup

Run the targeted cleanup after the proof:

```bash
node scripts/curve-observability-proof.mjs cleanup
```

The command removes only the three Curve observability containers, the
`plane_curve_prometheus_data` and `plane_curve_grafana_data` volumes, and the
generated `.curve-local/` state. The existing Plane database, Redis,
RabbitMQ, MinIO, Temporal, API, worker, Beat, and Curve worker remain in place.

For a completely disposable Compose project, `docker compose down -v` remains
the environment-wide cleanup command. Do not use it against the shared `plane`
project when its application data must remain available.

## Validation

Run the static configuration and proof-runner tests without starting Docker:

```bash
pnpm check:curve-observability
pnpm check:contracts
```

The Docker-backed proof performs the native configuration validation through
the same Compose mounts used at runtime:

```bash
node scripts/curve-observability-proof.mjs up
node scripts/curve-observability-proof.mjs verify-health
node scripts/curve-observability-proof.mjs verify-alerts
```

`up` first executes `docker compose config --quiet`, then the Collector and
Prometheus processes accept their mounted configurations before they become
available. `verify-health` requires Collector health plus both Prometheus scrape
paths. `verify-alerts` runs `promtool test rules` inside a short-lived instance
of the exact digest-pinned Prometheus service and verifies the six loaded alert
identifiers through the Prometheus API.

The implementation follows the upstream configuration contracts documented by
OpenTelemetry Collector internal telemetry
([opentelemetry.io](https://opentelemetry.io/docs/collector/internal-telemetry/)),
the Collector Prometheus exporter
([github.com](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/exporter/prometheusexporter/README.md)),
Prometheus configuration and metric relabeling
([prometheus.io](https://prometheus.io/docs/prometheus/latest/configuration/configuration/)),
Prometheus alerting rules
([prometheus.io](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)),
and Grafana provisioning
([grafana.com](https://grafana.com/docs/grafana/latest/administration/provisioning/)).

## Local ownership and promotion

The developer running the environment owns local alert evaluation. Alerts stay
inside local Grafana; no external receiver is configured. Prometheus and
Grafana use disposable Docker named volumes with a 24-hour Prometheus
retention window.

Staging promotion requires a separate infrastructure decision covering the
Example Organization-managed Collector/export endpoint, TLS and authentication, Prometheus and
Grafana identities, retention, alert routing, secrets, and Platform Operations
ownership.
