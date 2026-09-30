# Local performance observability

This optional stack runs only on loopback interfaces:

- Prometheus receives k6 remote-write data and scrapes OpenTelemetry metrics;
- Tempo stores frontend/backend traces;
- OpenTelemetry Collector accepts OTLP HTTP/gRPC;
- Grafana is provisioned with both data sources and a current-vs-golden
  dashboard.

## Start

```bash
cd observability
cp .env.example .env
# Set a strong local-only admin password in .env.
docker compose up -d
docker compose ps
```

Open http://127.0.0.1:3000 and select **UI Quality Performance: Current vs
Golden**.

The platform exports OTLP metrics when a profile enables
`integrations.opentelemetry` and `export.otlp_endpoint` points to
`http://127.0.0.1:4318`.

For k6 Prometheus remote write:

```bash
K6_PROMETHEUS_RW_SERVER_URL=http://127.0.0.1:9090/api/v1/write \
k6 run -o experimental-prometheus-rw performance.js
```

The generated profile runner sets the endpoint when
`tool_options.prometheus_remote_write_url` is configured.

## Golden overlays

Golden baselines are approved JSON artifacts under `performance-baselines/`.
They are not stored only in Grafana. A measured run with a matching baseline
exports both `run_kind=current` and `run_kind=baseline`, which the provisioned
dashboard overlays.

## Stop

```bash
docker compose down
```

Use `docker compose down -v` only when intentionally deleting local metrics,
traces, dashboards, and Grafana state.
