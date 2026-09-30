# Performance assurance presentation prototype

This static prototype demonstrates the configurable workflow without requiring
the target app, k6, Grafana, or an LLM:

1. select a page, feature, or component profile;
2. adjust iterations, virtual users, and p50/p90/p95 budgets;
3. run deterministic sample iterations;
4. compare the current distribution with the approved golden;
5. open a correlated browser/backend/database trace waterfall.

Run from the repository root:

```powershell
.venv\Scripts\python.exe -m http.server 8080 --directory prototype
```

Open http://127.0.0.1:8080.

The prototype loads `fixtures/performance-runs.json`. It is deliberately
dependency-free and does not contact external services. The Google Fonts link
is optional; system fonts are used when offline.
