# PRD-002: Pluggable Requirement and UX Assurance Platform

| Field | Value |
|---|---|
| Status | Proposed |
| Author / Owner | Vivek Kaushik |
| Target release | v2.0 |
| Supersedes | The StageUI-only scope in [PRD-001](001-stageui-requirement-assurance-agent.md) |
| Architecture and design | [Pluggable Assurance Architecture](../architecture/002-pluggable-assurance-platform.md) |
| Reference implementation | [README](../../README.md) |

## 1. Executive summary

Product teams need to prove that a web implementation satisfies its Jira requirements and approved Figma design. Existing test automation usually begins after a human has interpreted the story, selected test data, and written test cases. This leaves three gaps:

1. requirements may be misunderstood before automation starts;
2. generated tests may execute without human approval;
3. passing functional tests may not prove Figma, business-rule, API, or evidence conformance.

The Pluggable Requirement and UX Assurance Platform creates a governed lifecycle:

```text
Jira + Figma + engineering knowledge
                ↓
Grounded, cited test-case generation
                ↓
Excel human review and approval
                ↓
Approved execution by story, frame, or feature
                ↓
Evidence-backed verdict report
                ↓
Deterministic report and artifact evaluation
```

The platform supports different web applications through target adapters and gives the reasoning harness access only to configured, schema-validated tools. LangGraph remains the default deterministic harness. A Claude Agent SDK harness may be added as an optional conversational orchestration layer without replacing the governed execution engine.

## 2. Problem statement

QA engineers, product owners, designers, and developers currently coordinate Jira, Figma, business rules, test data, browser automation, and release evidence through separate tools. Common failures include:

- an acceptance criterion is omitted from testing;
- a generated test invents an expected value;
- a Figma component or interaction is not linked to the corresponding requirement;
- a test executes before a human confirms its intent;
- automation passes against stale Jira, Figma, or knowledge sources;
- a browser agent performs an unsafe or out-of-environment action;
- a report claims PASS while required screenshots or traces are missing;
- an agent harness gains broad shell or application access merely to run a constrained test.

The platform must separate probabilistic reasoning from deterministic execution and classification.

## 3. Product principles

1. **Generate before executing.** Test design is a durable artifact, not an invisible intermediate prompt.
2. **Human approval is a boundary.** Draft or stale plans cannot execute through the governed path.
3. **Sources are cited.** Expected behavior must trace to Jira, Figma, business rules, contracts, or controlled test data.
4. **The model does not decide verdicts.** PASS, GAP, DEFECT, and RISK come from deterministic observations.
5. **Capabilities are explicit.** Applications and tools advertise supported behavior; unsupported checks become RISK.
6. **Evidence is evaluated.** A generated report is not trusted until its artifacts and internal consistency are audited.
7. **Harnesses are replaceable.** LangGraph, Claude, or another harness may orchestrate the same governed tools.

## 4. Personas

| Persona | Primary need |
|---|---|
| QA engineer | Generate comprehensive tests, review them, execute approved subsets, and receive reproducible evidence |
| Product owner | Confirm that tests represent the intended acceptance criteria before execution |
| Designer | Select a Figma frame or feature and see whether implementation and prototype flows conform |
| Developer | Reproduce a GAP or DEFECT from exact steps, traces, screenshots, API responses, and calculations |
| QA lead | Measure coverage, correctness, evidence completeness, flakiness, and cost across runs |
| Platform engineer | Configure applications, authentication, tools, Jira/Figma sources, policies, and CI gates |

## 5. Goals

### 5.1 Product goals

1. Convert Jira stories and Figma intent into versioned, AC-traceable test plans.
2. Export generated plans to a secure Excel workbook for human evaluation.
3. Import reviewer decisions and validated step edits into the canonical plan.
4. Execute only approved, current test cases.
5. Select execution by story, acceptance criterion, Figma frame, product feature, or case ID.
6. Support React and other browser-rendered web UIs through configurable target adapters.
7. Support form login, Playwright storage state, headers/cookies, and unauthenticated targets.
8. Provide a guarded registry for built-in, Python-plugin, and MCP tools.
9. Improve RAG with hybrid retrieval, metadata filters, citations, source freshness, and retrieval evals.
10. Evaluate every execution report and evidence tree before returning a successful quality-gate status.
11. Preserve replay mode and deterministic gold-label evaluation.
12. Permit an optional Claude Agent SDK harness without weakening approval or safety boundaries.
13. Measure page, feature, component, API, and load performance with controlled
    profiles, approved golden baselines, and deterministic budgets.
14. Correlate browser measurements with backend telemetry and visualize
    current-versus-golden trends in an optional local Grafana stack.

### 5.2 Success outcomes

- A reviewer can understand and approve generated tests without reading prompts or code.
- The same approved plan can be executed repeatedly without regeneration.
- A target application can be changed through configuration and a bounded adapter.
- Jira, Figma, RAG, execution, and evaluation are independently replaceable.
- Harness comparison uses the same inputs, tools, approved plans, and gold labels.

## 6. Non-goals

- Autonomous release approval without a human-defined policy.
- Testing production systems by default.
- Allowing unrestricted shell, file-write, browser, or administrative access to a reasoning model.
- Replacing Playwright with model-generated browser code.
- Letting an LLM determine PASS/GAP/DEFECT/RISK.
- Treating pixel comparison or vision output as the sole design oracle.
- Using Excel as the canonical executable format.
- Automatically completing CAPTCHA, MFA, or enterprise SSO challenges.
- Replacing Jira or Figma as systems of record.

## 7. End-to-end user journey

1. A platform engineer configures the target application, credentials, allowed origins, Jira source, Figma source, RAG sources, and agent tools.
2. A QA engineer requests test generation for one or more stories.
3. The platform retrieves context per AC, builds expected behavior, detects missing/conflicting sources, and generates constrained scenarios.
4. The platform writes immutable JSON and an Excel review projection.
5. A reviewer approves, rejects, requests changes, and optionally edits scenario steps.
6. The platform imports and validates the workbook. Invalid actions, ACs, formulas, secrets, URLs, or schemas are rejected.
7. A QA engineer or CI job selects approved tests by story, frame, or feature.
8. The platform rejects stale plans unless an explicit override is supplied.
9. The target adapter authenticates and exposes only supported capabilities.
10. Playwright executes constrained steps and captures evidence.
11. Deterministic classifiers assign AC, story, and Figma-frame verdicts.
12. Reporting produces HTML, JSON, evidence, and workbook result sheets.
13. The artifact evaluator checks coverage, consistency, evidence existence, source grounding, and secret leakage.
14. When enabled, the performance runner executes matching controlled profiles,
    compares distributions with approved baselines, and appends results to the
    report and workbook.
15. CI succeeds only when the configured functional, artifact-evaluation, and
    performance policies pass.

## 8. Functional requirements

### 8.1 Source ingestion and normalization

| ID | Requirement |
|---|---|
| FR-001 | The platform shall ingest stories from local Jira-export JSON or a configured live Jira adapter/MCP server. |
| FR-002 | Every story shall normalize into the existing `Story` contract with stable story and AC identifiers. |
| FR-003 | The platform shall ingest Figma frames, components, flows, routes, images, approved variances, story links, and feature mappings through MCP. |
| FR-004 | The platform shall support fixture and live Figma REST-backed sources behind the same contract. |
| FR-005 | The platform shall record source identifiers, versions, and content hashes used by each generated plan. |

### 8.2 RAG and expected behavior

| ID | Requirement |
|---|---|
| FR-010 | The platform shall index stories, ACs, business rules, API/UI contracts, glossary, controlled test data, flow prerequisites, Figma frames, and approved variances. |
| FR-011 | Retrieval shall combine dense similarity and lexical BM25 ranking. |
| FR-012 | Retrieval shall support metadata filters for source type, story, AC, rule, frame, feature, and labels. |
| FR-013 | Exact business-rule identifiers shall be resolved before semantic retrieval. |
| FR-014 | Retrieval shall execute per AC and check type rather than only at story level. |
| FR-015 | Generated intent and test cases shall retain stable citations to retrieved chunks. |
| FR-016 | Missing referenced rules and deterministic source conflicts shall be surfaced for human review. |
| FR-017 | The platform shall detect stale indexes using a manifest of source and Figma hashes. |

### 8.3 Test generation and catalog

| ID | Requirement |
|---|---|
| FR-020 | Test generation shall not open, reset, or mutate the target application. |
| FR-021 | Every generated test case shall cite one story and at least one valid AC. |
| FR-022 | Each test case shall contain stable case ID, rationale, constrained steps, feature/frame/node links, citations, status, and reviewer metadata. |
| FR-023 | Plans shall be versioned and stored as canonical JSON under a durable catalog. |
| FR-024 | Regeneration shall create a new version and shall not silently overwrite an approved version. |
| FR-025 | Plans shall record Jira/knowledge hashes and Figma version. |

### 8.4 Human review in Excel

| ID | Requirement |
|---|---|
| FR-030 | The platform shall export Summary, Test Cases, Steps, Coverage, Sources, and Human Review sheets. |
| FR-031 | Reviewers may change approval status, reviewer, comment, and constrained test steps. |
| FR-032 | JSON shall remain canonical; a workbook shall not execute directly. |
| FR-033 | Import shall reject macros, unknown columns, invalid actions, unknown ACs/cases, non-contiguous steps, disallowed origins, destructive actions, formulas, credential-like values, configured secrets, and oversized input. |
| FR-034 | Approved, rejected, draft, and needs-change states shall be supported. |

### 8.5 Selection and execution

| ID | Requirement |
|---|---|
| FR-040 | Execution shall accept story, frame, feature, or explicit case selection. |
| FR-041 | The governed path shall execute only APPROVED cases. |
| FR-042 | Execution shall reject changed Jira/knowledge/Figma sources unless an explicit stale override is supplied and recorded. |
| FR-043 | Browser execution shall use only the constrained step language. |
| FR-044 | Locator recovery may use a bounded reasoning loop but shall remain within registered recovery tools and retry limits. |
| FR-045 | Credentials shall be resolved locally from placeholders and never inserted into prompts, plans, or workbooks. |
| FR-046 | Evidence shall include step results, screenshots, trace, network records, and specialized calculation/data evidence when available. |

### 8.6 Target application adapters

| ID | Requirement |
|---|---|
| FR-050 | A StageUI adapter shall preserve the reference application's form login, seed reset, row semantics, SQLite probe, and calculations. |
| FR-051 | A generic-web adapter shall support form, storage-state, header/cookie, and no-auth modes. |
| FR-052 | Generic targets shall not reset or access databases unless the configured adapter explicitly declares those capabilities. |
| FR-053 | Navigation shall be restricted to parsed, exact allowed origins. |
| FR-054 | Unsupported target capabilities shall produce RISK or refusal instead of falling back to StageUI assumptions. |
| FR-055 | Target profiles shall configure health path, authentication selectors, list semantics, capabilities, and optional feature mappings. |

### 8.7 Tool registry and MCP

| ID | Requirement |
|---|---|
| FR-060 | Tools shall declare name, description, JSON schema, enabled state, surfaces, risk, timeout, required capabilities, and handler. |
| FR-061 | Built-in, Python import-path, and MCP handlers shall be supported. |
| FR-062 | MCP stdio, SSE, and streamable-HTTP transports shall be configurable. |
| FR-063 | Unauthorized tools shall not be presented to the model and shall be rejected if called directly. |
| FR-064 | Tool input shall be schema-validated before handler invocation. |
| FR-065 | Chat, recovery, and MCP exposure shall consume the same authorization model. |

### 8.8 Classification, reporting, and evaluation

| ID | Requirement |
|---|---|
| FR-070 | Verdicts shall remain deterministic and use PASS, GAP, DEFECT, and RISK. |
| FR-071 | Vision output and LLM recommendations shall remain advisory. |
| FR-072 | Every execution shall produce `results.json`, `report.html`, evidence folders, and `eval.json`. |
| FR-073 | The evaluator shall verify selected-case and AC coverage, label consistency, referenced evidence, report presence, and configured-secret absence. |
| FR-074 | Secret scanning shall inspect ordinary files and members inside trace ZIP archives. |
| FR-075 | Approved-plan workbooks shall receive Results and Evaluation sheets after execution. |
| FR-076 | Artifact evaluation shall not change requirement verdicts. |
| FR-077 | A failed artifact evaluation shall return a distinct non-zero exit status. |

### 8.9 Configurable performance assurance

| ID | Requirement |
|---|---|
| FR-080 | Performance assurance shall be disabled by default and enabled globally, automatically with approved tests, or explicitly per CLI/MCP run. |
| FR-081 | Profiles shall support page, feature journey, component interaction, API/service, and load scopes. |
| FR-082 | Profiles shall configure selectors, setup/actions, settled-state conditions, cold/warm cache, viewport, CPU/network profile, warm-ups, iterations, integrations, tags, and budgets. |
| FR-083 | Controlled browser runs shall capture navigation, Web Vitals, interaction, long-task, request-count, and transfer metrics without functional screenshot/trace overhead. |
| FR-084 | k6 browser and protocol integrations shall be optional and shall support browser journeys, backend load, thresholds, and Prometheus remote write. |
| FR-085 | Lighthouse CI shall be an optional page audit/resource-budget integration. |
| FR-086 | BenchmarkDotNet JSON shall be accepted as optional linked evidence for .NET microbenchmarks but shall not replace end-to-end UI measurements. |
| FR-087 | OpenTelemetry shall optionally correlate frontend actions with backend/service/database spans using W3C trace context. |
| FR-088 | Statistics shall retain raw samples and report median, p75, p90, p95, p99, standard deviation, MAD, and coefficient of variation. |
| FR-089 | Performance status shall be separate from functional labels and use PASS, WARN, FAIL, UNSTABLE, or NOT_MEASURED. |
| FR-090 | Absolute and relative-regression budgets shall be deterministic; ambiguous performance ACs shall remain RISK until a human approves a budget. |
| FR-091 | Golden baselines shall be immutable, human-promoted JSON artifacts tied to a source run and environment fingerprint. |
| FR-092 | Grafana, Prometheus, Tempo, and OpenTelemetry Collector shall be optional local services provisioned from version-controlled configuration. |
| FR-093 | Reports, JSON, Excel, MCP, and artifact evaluation shall expose performance summaries and baseline outcomes. |
| FR-094 | Time-series labels shall use bounded stable identifiers and shall not include user data, raw dynamic URLs, or secrets. |

### 8.10 Optional Claude Agent SDK harness

| ID | Requirement |
|---|---|
| FR-100 | Claude shall be an optional harness selected independently of the execution engine. |
| FR-101 | Claude shall access Jira, Figma, RAG, plan, execution, results, evaluation, and approved performance operations only through registered MCP tools. |
| FR-102 | Claude shall not receive unrestricted Bash, Write, Edit, or browser tools in the assurance profile. |
| FR-103 | Claude tool use shall be restricted with strict MCP configuration, explicit tools, capability policy, maximum turns, and budget. |
| FR-104 | A pre-tool hook shall deny unapproved/stale execution and out-of-policy target access. |
| FR-105 | Claude structured output shall use the platform's JSON/Pydantic contracts. |
| FR-106 | LangGraph shall remain available for deterministic CI and baseline comparison. |

## 9. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-001 | The same approved plan and target state shall produce stable labels across repeated runs. |
| NFR-002 | The platform shall run on Windows Python without GPU or native vector-database dependencies. |
| NFR-003 | Secrets shall come from environment configuration or protected storage-state/header files and shall never be committed. |
| NFR-004 | The default generic adapter shall be non-resetting and capability-minimal. |
| NFR-005 | Test and retrieval evals shall run offline with the hashing embedder and replay provider. |
| NFR-006 | All model and harness calls shall record token/call usage where the provider exposes it. |
| NFR-007 | Tool and harness execution shall enforce configurable timeout and budget limits. |
| NFR-008 | Existing StageUI gold labels and replay behavior shall remain backward compatible. |
| NFR-009 | Reports shall be understandable by a reviewer in under five minutes per story. |
| NFR-010 | New source, app, and harness integrations shall be isolated behind documented interfaces. |

## 10. Quality metrics

| Metric | Target |
|---|---|
| ACs represented by generated test cases | 100% |
| Approved selected cases executed | 100% |
| Evidence completeness | 100% |
| Label accuracy against human gold | ≥ 90% |
| Known issue detection | 100% of maintained gold issues |
| False-positive GAP/DEFECT rate | 0 for reference corpus |
| Flake rate over three replay-equivalent runs | 0% |
| Retrieval Hit@3 / Recall@3 | 100% for maintained retrieval gold |
| Forbidden tool calls successfully executed | 0 |
| Plaintext configured secrets in artifacts | 0 |
| Performance profile raw-sample retention | 100% |
| Performance budgets evaluated deterministically | 100% |
| Golden baseline promotions with approver and matching environment | 100% |
| High-cardinality or secret-bearing time-series labels | 0 |

## 11. Release phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Versioned generation, Excel review, approved execution, adapters, guarded tools, hybrid RAG, artifact eval | Implemented on feature branch |
| 2 | Live Jira Cloud adapter and production Figma configuration | Proposed |
| 3 | Optional Claude Agent SDK harness and harness-comparison evals | Proposed |
| 4 | Performance profiles, controlled browser collector, baselines, report/eval integration, local Grafana stack | Implemented on feature branch |
| 5 | Distributed load agents and organization-level plugin packaging | Future |

## 12. Acceptance criteria

1. A story can be generated into JSON and Excel without starting the target app.
2. An approved workbook can be imported and edited steps are validated.
3. Draft and stale plans cannot execute through the governed path.
4. Approved cases can be executed by story, Figma frame, or feature.
5. A generic target can use form or storage-state authentication without StageUI reset/database assumptions.
6. A configured Python or MCP tool is visible only on authorized surfaces.
7. RAG gold evaluation reaches the maintained threshold.
8. Performance can remain disabled with no behavior change or be enabled for a
   named page, feature, or component profile.
9. A performance run emits raw samples, statistical summaries, budget outcomes,
   `performance.json`, report content, and evaluation status.
10. A human can promote a stable passing run to an immutable golden baseline,
    and a later run reports current-to-golden regression.
11. The local Grafana stack starts from Compose and provides provisioned
    Prometheus/Tempo data sources and a current-versus-golden dashboard.
12. A completed execution produces a passing artifact evaluation when all evidence exists.
13. Deliberately missing evidence or an injected secret causes artifact evaluation to fail.
14. The reference suite and replay smoke remain green.
15. When the Claude harness is introduced, it can complete the same approved workflow without direct shell/browser access and without changing deterministic verdicts.

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Human edits make generated tests unsafe | Validate imported steps through schema, AC, URL, action, size, formula, and secret policies |
| Jira and Figma disagree | Preserve both citations, surface conflict, require human review |
| RAG retrieves irrelevant context | Hybrid retrieval, metadata filters, thresholds, exact rule lookup, retrieval gold |
| Application adapter becomes an unrestricted plugin | Capability interface, exact origins, read-only defaults, explicit secrets |
| MCP tool expands agent authority | Disabled by default, surface/risk/capability checks, strict input schemas and timeouts |
| Claude or another harness bypasses policy | Expose governed MCP tools only; pre-tool hooks; no unrestricted shell/edit tools |
| Report looks valid but evidence is incomplete | Deterministic post-report artifact evaluation and CI exit code |
| Storage-state file leaks tokens | Gitignore, local-only path, token scrubbing, secret scan |
| Model/provider behavior changes | Structured contracts, replay mode, gold labels, harness comparison |
| Performance noise creates false regressions | Controlled environment fingerprints, warm-ups, repeated samples, variance status, and distribution comparison |
| Dashboard becomes the only baseline record | Canonical approved JSON baseline; Grafana remains a projection |
| Time-series cardinality or telemetry leaks data | Stable bounded labels, local endpoints, secret scrubbing, and artifact metadata for run/trace IDs |

## 14. Configuration ownership

| Configuration | Owner |
|---|---|
| Jira project, authentication, and field mapping | Platform engineer / Jira administrator |
| Figma file, routes, features, and approved variances | Designer / product owner |
| Target profile, origins, and authentication | QA/platform engineer |
| Business rules and controlled test data | Product and QA |
| Tool registry and capability grants | Platform/security engineer |
| Gold labels and retrieval evals | QA lead |
| CI blocking policy | Release owner |
| Performance profiles and budgets | QA lead / service owner |
| Golden baseline promotion | Named human approver |
| Grafana, Prometheus, Tempo, and OTel retention/access | Platform engineer |

## 15. Open decisions

1. Jira Cloud REST adapter versus a standardized Jira MCP server.
2. Whether Excel approval requires one reviewer or dual approval for high-risk targets.
3. Whether GAP and RISK block CI globally or through per-project policy.
4. Whether Claude sessions may persist across review and execution or must be separated at approval.
5. Which Claude model and budget limits are approved for planning, chat, and visual review.
6. Whether organization-level tools are distributed as Claude plugins, MCP configuration, or platform-native packages.
