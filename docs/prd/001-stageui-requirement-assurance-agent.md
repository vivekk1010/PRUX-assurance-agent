# PRD-001: Agentic StageUI Requirement & UX Assurance

| Field | Value |
|---|---|
| Status | Draft (living document) |
| Author | Vivek Kaushik |
| Owner | Vivek Kaushik |
| Release | v1.0 |
| Related | [Architecture](../architecture/architecture.md), [Stories](../../stories/), [README](../../README.md) |

## 1. Problem

QA and product teams hand-translate Jira stories and Figma designs into test cases. Gaps appear when:

- an acceptance criterion (AC) is vague or untested,
- the StageUI build behaves differently from the approved UX,
- a number on screen is wrong even though the page "works".

A passing code review or a green scripted test does not prove that the StageUI application satisfies the story or matches the design.

**Question we answer:** *Does this StageUI build match what the story and its Figma design asked for, and what evidence proves it?*

## 2. Target users

| Persona | Need |
|---|---|
| QA engineer | Run assurance on a story without hand-writing every scenario; get evidence to attach to a bug |
| Product owner / designer | See which ACs are met and where StageUI drifts from Figma before sign-off |
| Developer | Reproduce a reported GAP or DEFECT from screenshots, trace, and API/data evidence |

## 3. Goals

1. Give a per-frame verdict on whether StageUI matches the Figma design, with design and live screenshots side by side.
2. Turn a Jira story and its Figma design into an explicit, reviewable expected-behavior record.
3. Generate executable scenarios that trace back to specific ACs.
4. Operate the StageUI application like a user, within a restricted set of safe actions.
5. Validate UI, API, stored data, and business calculations, not just the screen.
6. Classify every frame and every AC as **PASS**, **GAP**, **DEFECT**, or **RISK** with an auditable evidence trail.
7. Produce a report a human can review in under 5 minutes per story.

## 4. Non-goals

- Reviewing or changing source code.
- Running against production or any non-StageUI environment.
- Pixel-perfect visual QA. Visual review is advisory; verdicts rest on component, flow and data checks.
- Release sign-off. The agent advises; a human decides.
- Destructive actions (delete, admin, payments) during assurance runs.

## 5. Scope (v1.0)

One StageUI application: **Blog Notes**, a web app where a user logs in and stores blog posts as plain text with metadata (author, date, tags, word count, reading time).

Figma file: three frames (Login, My Blogs, New Post) with component instances, prototype flows, frame routes and approved variances.

Five stories:

| Story | Title | Intent |
|---|---|---|
| BLOG-101 | Log in | Valid login lands on My Blogs; invalid login shows an error |
| BLOG-102 | Create a blog post | Title, content, tags; author auto-filled; saved post appears with today's date |
| BLOG-103 | Blog metadata and reading time | List shows metadata; word count and reading time follow the business rule |
| BLOG-104 | Filter posts by tags | Filter by one or more tags; clear filters |
| BLOG-105 | Log out and session protection | Logout ends session; protected pages redirect to login |

The current StageUI build has known issues; §11 lists the expected findings.

## 6. User stories (for the agent itself)

| ID | As a… | I want to… | So that… |
|---|---|---|---|
| US-1 | QA engineer | run assurance for one story by its Jira key | I get a verdict per AC without writing tests |
| US-2 | QA engineer | run assurance for all stories in a release | I get one report for the StageUI build |
| US-3 | Product owner | see the expected-behavior record the agent built | I can confirm it did not invent requirements |
| US-4 | Developer | open screenshots, browser trace, API and data evidence per AC | I can reproduce the issue |
| US-5 | Designer | see each Figma frame next to the live StageUI screen with differences highlighted | I know exactly which components drift, excluding approved variances |
| US-6 | QA engineer | have vague ACs flagged instead of guessed | I can fix the story rather than trust a false PASS |

## 7. Functional requirements

| ID | Requirement |
|---|---|
| FR-1 | The agent accepts a story key (or "all") and loads the story, its ACs, and business rules from the requirements source. |
| FR-2 | The agent loads UX intent: frames, components (kind, label, state, position), prototype flows, frame routes, approved variances and frame images. |
| FR-3 | The agent builds an expected-behavior record per story before any execution, and saves it with the run. |
| FR-4 | The agent retrieves supporting context (business rules, glossary, UI/API contract, test data) from a local knowledge base, and cites what it used. |
| FR-5 | Every generated scenario references exactly one story key and at least one AC ID. |
| FR-6 | The agent performs only allow-listed user actions on StageUI. Destructive or out-of-environment actions are refused and recorded. |
| FR-7 | Credentials and personal data are never sent to the reasoning model and are masked in evidence. |
| FR-8 | For each scenario, the agent captures step-level actions, screenshots, a browser trace, and relevant network responses. |
| FR-9 | For calculation ACs, the agent compares four values: UI shown, API returned, independently calculated, and source data. |
| FR-10 | The agent compares StageUI screens to UX intent by components, labels, control types, read-only state and table columns, and tolerates approved variances. |
| FR-11 | Each AC receives exactly one label: PASS, GAP, DEFECT, or RISK, with a short rationale and links to evidence. |
| FR-12 | An AC with missing evidence cannot be labelled PASS. |
| FR-13 | Unmeasurable ACs (e.g. "fast", "user friendly") are labelled RISK with the reason "expected behavior not specified". |
| FR-14 | The run produces a human-readable report and a machine-readable result file (§10). |
| FR-15 | The agent can run without a reasoning-model key in replay mode, using recorded model outputs. |
| FR-16 | **Figma conformance.** For every frame, the agent opens the frame's route on StageUI, captures a live screenshot at the design viewport, and places it next to the Figma frame image. |
| FR-17 | Each frame receives one label: component missing or mismatched → GAP; prototype flow lands on the wrong route → DEFECT; flow trigger missing → GAP; screen unreachable → RISK; otherwise PASS. |
| FR-18 | For each prototype flow, the agent clicks the trigger (filling prerequisite fields from controlled test data) and compares the landing route with the destination frame's route. |
| FR-19 | Mismatched and approved-variance components are highlighted on the design image at their Figma position. |
| FR-20 | An optional vision-model review lists layout and style differences. It is advisory and never changes a label. |

## 8. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-1 | A single story run completes in under 2 minutes on a laptop without GPU. |
| NFR-2 | Re-running the same story on the same StageUI build and data produces the same labels (flake rate is reported). |
| NFR-3 | Model cost per story and for the visual review is tracked (tokens, calls, model) and shown in the report. |
| NFR-4 | All secrets come from environment configuration; none are committed. |
| NFR-5 | StageUI data is reset to a known seed before an assurance run. |

## 9. Label definitions

| Label | Meaning |
|---|---|
| PASS | Expected behavior and design observed; evidence is consistent |
| GAP | Required behavior or UX element is missing, incomplete, or a different control type |
| DEFECT | Observed behavior contradicts the expected behavior, with supporting evidence |
| RISK | Possible issue, ambiguous AC, refused action, or incomplete evidence; needs a human |

Precedence when several apply: DEFECT > GAP > RISK > PASS.

## 10. Outputs

Each run writes `runs/<run-id>/`.

### 10.1 HTML report (`report.html`)

| Section | Content |
|---|---|
| Run header | Run id, author, StageUI URL, LLM provider and model, UX source, RAG embedder |
| Figma conformance summary | One row per frame: route, verdict, rationale |
| Frame card | Design PNG and live screenshot side by side; red outlines on missing or mismatched components, amber on approved variances |
| Components table | Figma node id, kind, label, status (`matched`, `missing`, `mismatch`, `approved_variance`, `skipped`), observed detail |
| Flows table | Trigger, designed destination route, observed URL, status |
| Visual review | Advisory differences with severity from the vision model |
| Story sections | Story verdict, recommendation, per-AC verdict and rationale with links to screenshots, traces, network and calculation evidence |

### 10.2 Result file (`results.json`)

Top-level keys: `meta` (run id, author, provider, models, UX source, token usage), `figma_conformance` (one object per frame: `frame`, `node_id`, `route`, `label`, `rationale`, `components[]`, `flows[]`, `visual_review`, `design_image`, `live_image`, `trace_path`) and `stories` (one object per story: `story_key`, `label`, `recommendation`, `ac_verdicts[]`, `scenario_results[]`, `intent_path`, `scenarios_path`, `llm_usage`). Suitable for CI gates and dashboards.

### 10.3 Evidence folders

- `figma/<frame-slug>/`: `design.png`, `live.png`, `verdict.json`, step screenshots, `trace.zip`, `network.json`.
- `<story-key>/`: `intent.json`, `scenarios.json`, `result.json`, and one folder per scenario with step screenshots, `trace.zip`, `network.json` and calculation files.

## 11. Verification criteria (expected findings on the current StageUI build)

| ID | Given | Expected |
|---|---|---|
| VC-1 | BLOG-101 on the seeded StageUI build | All ACs PASS |
| VC-2 | BLOG-102, where StageUI uses an approved label variance for the save button | PASS, with the variance noted |
| VC-3 | BLOG-103, where StageUI computes reading time incorrectly | AC-03 is DEFECT, with four values shown |
| VC-4 | BLOG-104, where Figma shows a multi-select but StageUI has a single-select | AC-01 is GAP, with the Figma component referenced |
| VC-5 | BLOG-105 with an unmeasurable "loads fast" AC | That AC is RISK; measured load time is still recorded |
| VC-6 | Figma conformance for Login and New Post | PASS; New Post notes the approved variance |
| VC-7 | Figma conformance for My Blogs | GAP on node 2:6 `Filter by tags`, highlighted on the design image |
| VC-8 | Any scenario requesting a delete action | Action refused and logged; the AC cannot be PASS |
| VC-9 | Any run | Report, network logs and traces contain no plaintext password |
| VC-10 | Replay mode with no model key | Full pipeline completes and produces a report |

## 12. Success metrics

| Metric | Target |
|---|---|
| Requirement coverage (ACs with a scenario and a label) | 100% of in-scope ACs |
| Label accuracy vs human gold labels (ACs and frames) | ≥ 90% |
| Known issues detected (GAP/DEFECT/RISK) | 3 of 3 |
| False positives (GAP/DEFECT rejected by human) | 0 |
| Evidence completeness per AC and per frame | 100% |
| Flake rate over 3 reruns | 0% |
| Time from trigger to report (all frames and stories) | < 10 minutes |

## 13. Dependencies

- A reasoning model with tool calling and vision (OpenAI or Azure OpenAI), or replay mode.
- A browser automation runtime.
- A requirements source (Jira export or Jira Cloud) and a UX intent source (Figma REST or fixture).

## 14. Risks

| Risk | Mitigation (product level) |
|---|---|
| Model invents expected behavior | Expected-behavior record is built first and reviewable; ambiguity becomes RISK |
| Flaky UI runs | Reset data; state-aware waits; flake rate reported |
| Unsafe actions | Allow-list; refusal is recorded |
| Visual false positives | Verdicts use component, flow and data checks; vision review is advisory and filtered for approved variances and conditional states |
| Cost overrun | Replay mode; per-run token usage shown; vision model configurable |

## 15. Open questions

- TODO-human-decision: Move the requirements source from Jira export to Jira Cloud REST?
- TODO-human-decision: Point the Figma source at the production design file via REST token?
- TODO-human-decision: Should a GAP on Figma conformance fail CI, or only DEFECT?
