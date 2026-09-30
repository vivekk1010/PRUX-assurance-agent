# PRD-003 — Requirements Alchemist

**Author:** Vivek
**Status:** Implemented foundation / human validation required
**Product type:** Local-first requirements engineering and backlog-generation application
**Primary outcome:** Convert Figma and/or PRD evidence into detailed, traceable, human-reviewed,
Jira-ready stories without treating model output as approved product intent.

## 1. Problem

Product intent is fragmented across PRDs, Confluence, Jira, Figma, meetings, and team memory.
The resulting backlog often loses source traceability, negative behavior, non-functional
requirements, UX states, dependencies, and unresolved questions. Writing complete stories
manually is slow; generating them directly with an LLM can produce plausible but unsupported
requirements.

The product needs a controlled middle path:

1. collect explicit evidence;
2. retrieve examples of well-formed stories as writing guidance;
3. use an LLM to decompose intent into a strict schema;
4. preserve ambiguity instead of hallucinating answers;
5. support grounded discussion with the evidence;
6. require human review; and
7. publish approved results to Jira or export them to Excel.

## 2. Product principles

1. **Evidence before prose.** Product facts come only from loaded sources.
2. **Examples teach form, not facts.** RAG examples may shape completeness and wording but
   cannot introduce behavior into the product backlog.
3. **Draft by default.** Every generated story starts as `DRAFT`.
4. **Human authority.** Approval and Jira publication are explicit human acts.
5. **Traceability is part of the artifact.** Criteria and stories retain source IDs.
6. **Local-first and provider-neutral.** Replay and local OpenAI-compatible models are valid
   operation modes; a hosted model is optional.
7. **Least privilege.** Source connectors are read-only. Jira write access is separately gated.
8. **Canonical JSON.** UI and Excel are projections of versionable structured data.

## 3. Personas

| Persona | Need |
|---|---|
| Product manager | Turn product intent into a complete candidate backlog and expose missing decisions |
| Business analyst | Retain exact source traceability, assumptions, rules, data, and exceptions |
| Product owner | Review value, scope, priority, readiness, and publish only accepted stories |
| UX designer | Ensure Figma states, labels, flows, validation, responsive behavior, and accessibility are represented |
| Engineer | Receive implementable slices with explicit dependencies, NFRs, edge cases, and open questions |
| QA engineer | Receive observable Given/When/Then criteria and test notes |
| Architect/security reviewer | See integration, data, privacy, security, reliability, and operational expectations |

## 4. Inputs

### 4.1 Supported in the implemented foundation

- pasted PRD or requirement text;
- `.txt`, `.md`, `.json`, `.yaml`, and `.yml` uploads;
- allowlisted HTTPS requirement pages;
- Figma design/file URLs using a personal access token;
- Confluence Cloud page URLs using Atlassian credentials;
- Jira Cloud issue URLs using Atlassian credentials;
- bundled licensed reference records; and
- human-approved generated stories added to local reference storage.

### 4.2 Input precedence

There is no automatic conflict winner. If sources disagree, generation must record the
conflict as an unresolved question. A Figma design does not silently override a PRD, and a
related Jira issue does not silently amend either.

### 4.3 Future input adapters

PDF/DOCX parsing, Figma image understanding, Confluence space traversal, Jira JQL batch import,
meeting transcripts, and requirements repositories are extension points, not claims of the
current implementation.

## 5. Canonical output

A story package contains:

- package ID, title, objective, source IDs, generation timestamp, and generator;
- cross-cutting requirements, package assumptions, glossary, and unresolved questions;
- one or more stories containing:
  - local ID and epic;
  - title;
  - persona, capability, benefit, and canonical narrative;
  - business value and detailed description;
  - in-scope and out-of-scope behavior;
  - Given/When/Then acceptance criteria, including negative criteria where needed;
  - measurable non-functional requirements by category;
  - UX, data, analytics, and test requirements;
  - dependencies, assumptions, risks, and open questions;
  - Definition of Ready and Definition of Done;
  - labels, priority, optional story points, confidence, and citations;
  - review status, reviewer, review comment, and Jira key.

Story points are a suggestion only. Team estimation remains authoritative.

## 6. Functional requirements

### FR-001 — Evidence workspace

The user can add, list, and remove evidence in a working session. The UI identifies source
kind, title, source ID or URL, and text size. Empty evidence is rejected.

### FR-002 — Safe URL acquisition

URL acquisition must:

- require HTTPS;
- enforce a configurable hostname allowlist when present;
- resolve DNS and reject loopback, private, link-local, and reserved addresses;
- refuse redirects;
- apply request timeouts and response-size limits; and
- avoid returning credentials or authorization headers to clients.

### FR-003 — Figma extraction

Given a Figma `/design/{key}` or `/file/{key}` URL, the connector reads the file through the
Figma API and extracts the node hierarchy, node types, component/frame names, and text. File
key, version, and last-modified metadata are retained. The foundation does not claim pixel,
image, variable, or prototype-semantic interpretation.

### FR-004 — Confluence extraction

Given a supported Confluence Cloud page URL, the connector resolves the page ID, requests the
storage body, removes executable/style markup, and retains title, version, URL, and page ID.

### FR-005 — Jira context extraction

Given a Jira Cloud browse URL, the connector reads summary, description, type, status,
priority, and labels. Atlassian Document Format is flattened to grounded text.

### FR-006 — Reference RAG

The application chunks loaded evidence and reference records and indexes them with local BM25.
Retrieval is deterministic, inspectable, and requires no API key. Each returned chunk retains
source ID, title, score, metadata, and license/provenance when applicable.

### FR-007 — Exemplary-story learning loop

Only a story with status `APPROVED` may be added to the local exemplary-story corpus. The
record includes reviewer and provenance. This action does not change the source product
requirements and must not convert example content into product evidence.

### FR-008 — Structured generation

Generation sends the objective, full loaded product evidence, retrieved examples, instructions,
and JSON schema to the configured LLM. The response must validate against the canonical
Pydantic schema. It must:

- decompose broad intent into independently valuable slices;
- retain unknowns as questions or assumptions;
- create observable criteria;
- avoid unsupported metrics or business rules;
- cite valid product source IDs;
- identify cross-cutting concerns; and
- return every story as `DRAFT`.

After validation, local story and criterion IDs are normalized and any invalid source
references are removed.

### FR-009 — Provider configuration

The user can configure:

- replay mode for keyless workflow demonstration;
- OpenAI-compatible hosted services;
- local Ollama or vLLM OpenAI-compatible endpoints; or
- Azure OpenAI.

Provider secrets are environment-only. The provider and model are visible in the UI.

### FR-010 — Human web review

The browser displays source evidence, generated stories, acceptance criteria, NFRs, questions,
review status, reviewer, and comments. A reviewer can set `DRAFT`, `APPROVED`, `NEEDS_CHANGE`,
or `REJECTED`.

### FR-011 — Excel review

The user can export a macro-free workbook with:

- Package;
- Stories;
- Acceptance Criteria;
- Non-functional;
- Human Review; and
- Sources sheets.

Only the Human Review projection is imported. Formula-like cells, credential-like values,
oversized files, unknown IDs, altered columns, and mismatched package IDs are rejected. Story
text edited in Excel is not silently accepted into canonical JSON.

### FR-012 — Jira publication

Jira publication must be disabled by default. When enabled, it:

- requires Atlassian base URL, project key, email, and API token;
- skips unapproved stories when human approval is required;
- skips stories that already contain a Jira key;
- creates Jira Cloud issues using ADF descriptions;
- includes narrative, business value, criteria, open questions, and traceability;
- adds a generator label and issue property; and
- returns a per-story `CREATED`, `SKIPPED`, or `FAILED` result.

Publication does not create epics, links, components, releases, custom fields, or transitions
unless a future configured field-mapping enhancement explicitly supports them.

### FR-013 — Grounded chat

The user can ask questions about loaded evidence and generated stories. For every turn the
application retrieves relevant workspace chunks and instructs the LLM to:

- answer from context;
- distinguish facts, recommendations, and unknowns;
- cite source IDs;
- avoid claiming approval or publication without evidence; and
- identify missing evidence.

The current implementation retains a bounded in-memory conversation for the local session.

### FR-014 — Persistence

Generated packages are saved as canonical JSON under a configured output directory. Generated
outputs and temporary workspace data are ignored by Git. Reference examples intentionally
added by a reviewer are persisted separately.

### FR-015 — Reset

The user can clear current source documents, generated package, and chat history. Bundled and
persisted exemplary references remain intact.

### FR-016 — Assurance handoff

Approved stories can be downloaded as a ZIP containing one `agent.models.Story` JSON file per
story. The projection retains actor, priority, description, criteria, relevant rules/NFRs,
labels, and Jira/local key so the existing assurance loop can consume the generated backlog.
Unapproved stories are excluded.

## 7. User flow

1. Configure model and optional connectors.
2. Open the local browser application.
3. Add PRD text/files and any Figma, Confluence, or Jira links.
4. Verify the evidence inventory.
5. Enter backlog title, objective, and optional reference query.
6. Generate a draft story package.
7. Ask the grounded copilot about gaps, conflicts, scope, risks, or dependencies.
8. Review each story in the UI or Excel.
9. Resolve questions outside the tool and regenerate or annotate review.
10. Approve suitable stories.
11. Optionally promote approved examples into local RAG.
12. Export the approved workbook and/or explicitly enable Jira publication.
13. Optionally export approved stories to the existing assurance agent.
14. Inspect per-story Jira results and canonical JSON.

## 8. UX requirements

- Present the workflow as evidence, generation, review/delivery, and chat.
- Make draft/approval state visible beside every story.
- Keep Jira publication unavailable when configuration disables it.
- Require confirmation before Jira creation and workspace reset.
- Never render model or source HTML directly; user/model text is escaped.
- Keep the interface usable at desktop and narrow/mobile widths.
- Show actionable connector and validation errors without revealing secret values.

## 9. Non-functional requirements

### Security

- Default binding is loopback.
- Browser mutations require a per-session CSRF token.
- Uploads are limited to 2 MB at the web tier and constrained extensions.
- Connectors implement SSRF controls.
- Secrets are loaded from named environment variables and excluded from artifacts.
- Excel formulas are neutralized on export and rejected on import.
- Jira write capability is deny-by-default and human-gated.

### Reliability and integrity

- Canonical schema validation occurs before persistence.
- Human review cannot silently alter generated content.
- Partial Jira results are explicit per story.
- Existing Jira keys prevent accidental duplicate publication from the same package.

### Performance

- Evidence text defaults to 120,000 characters per source.
- Retrieval is in-memory and intended for a team-sized local corpus.
- Network operations have 30–90 second timeouts.
- Long-running production deployments should move generation and ingestion to a job queue.

### Privacy

- The selected LLM receives source text and retrieved examples during generation.
- The selected LLM receives retrieved workspace chunks during chat.
- Operators must select a provider and retention policy suitable for the data classification.
- Replay or local models are available when external disclosure is not acceptable.

### Accessibility

- The UI uses semantic headings, labels, native controls, keyboard-operable buttons, responsive
  layout, and non-color status text.
- A formal WCAG 2.2 AA audit remains an acceptance activity before production deployment.

## 10. Acceptance criteria

| ID | Criterion |
|---|---|
| AC-01 | Pasted PRD evidence can produce a schema-valid DRAFT package in replay mode without keys |
| AC-02 | A live configured LLM receives source evidence and retrieved reference patterns |
| AC-03 | Generated criteria use structured Given/When/Then fields and source IDs |
| AC-04 | Approved and rejected states can be saved in the UI |
| AC-05 | Excel export contains story, criteria, NFR, review, and source sheets |
| AC-06 | Excel import updates review metadata but ignores edits to story content |
| AC-07 | Jira publishing is refused when disabled |
| AC-08 | With human gating enabled, an unapproved story is skipped without an API write |
| AC-09 | An approved story maps to Jira ADF containing criteria and traceability |
| AC-10 | Chat retrieves workspace context and returns source identifiers |
| AC-11 | Only approved stories can enter the exemplary reference corpus |
| AC-12 | Private/reserved URL targets and non-HTTPS source URLs are rejected |
| AC-13 | Credentials are not committed, logged in responses, or written to generated artifacts |

## 11. Non-goals

- Autonomous product decisions or approval;
- replacing discovery, stakeholder interviews, architecture, threat modeling, or estimation;
- bidirectional Jira synchronization;
- automatic editing of PRDs or Figma;
- pixel-level Figma conformance;
- production multi-tenancy, SSO, RBAC, audit retention, or a durable job queue;
- guaranteeing completeness from incomplete input; and
- using reference examples as authoritative product requirements.

## 12. Success measures

- percentage of generated stories with at least one valid product citation;
- acceptance-criterion coverage of identified requirement statements;
- percentage of generated assumptions/open questions resolved before approval;
- reviewer edit distance and rejection rate;
- duplicate Jira publication rate (target: zero);
- approved-story reuse retrieval rate;
- median generation-to-approved-backlog time; and
- secret/PII leakage incidents (target: zero).

Automated quality scores must remain advisory; reviewer approval and source traceability are
the release gates.

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Hallucinated behavior | strict prompt, schema, source-ID filtering, questions, human approval |
| Reference contamination | examples explicitly marked as style-only, license/provenance retained |
| Incomplete Figma semantics | document extraction boundary; do not claim image/prototype understanding |
| Jira duplicates | persisted Jira key, issue property, explicit confirmation; future remote dedup query |
| Sensitive PRD disclosure | local/replay model options, provider choice, environment-only secrets |
| Prompt injection in sources | source content is evidence, not instructions; system rules precede it |
| Spreadsheet injection | escape on export and reject formulas on import |
| SSRF | HTTPS, allowlist, DNS/IP rejection, no redirects |
| Overlarge backlog | human objective/scope, model slicing instructions; future maximum-story setting |
| Local single-user state | documented foundation boundary; add durable tenant store before shared hosting |

## 14. Delivery phases

### Phase 1 — Implemented foundation

Local web UI, source connectors, BM25 RAG, strict generation schema, replay/live provider
selection, canonical JSON, Excel review, approved-reference loop, guarded Jira publishing,
grounded chat, docs, and focused tests.

### Phase 2 — Production hardening

OAuth/SSO, encrypted durable storage, tenant isolation, asynchronous jobs, connector retries,
rate-limit handling, observability, field mappings, remote duplicate detection, source-version
snapshots, and formal security/accessibility testing.

### Phase 3 — Quality intelligence

Requirement-statement coverage, contradiction detection, configurable review rubrics,
DeepEval advisory scoring, evaluation datasets, reviewer feedback analytics, and regression
evaluation across model/prompt versions.
