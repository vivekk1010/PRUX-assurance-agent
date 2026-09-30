# Requirements Alchemist

Requirements Alchemist is a local-first companion application that converts product
evidence into detailed, traceable, human-reviewed Jira stories.

It accepts:

- pasted or uploaded PRDs (`.md`, `.txt`, `.json`, `.yaml`);
- HTTPS PRD pages on explicitly allowed hosts;
- Figma file links through the Figma REST API;
- Confluence Cloud page links; and
- Jira Cloud issue links that provide related context.

It produces:

- canonical JSON story packages;
- macro-free Excel workbooks for human review;
- a ZIP of approved stories in the existing assurance-agent JSON contract;
- approved Jira Cloud stories, when publishing is explicitly enabled;
- a local RAG corpus of licensed sample patterns and human-approved stories; and
- a browser chat experience grounded in loaded sources and generated stories.

## Run

From the repository root:

```bash
python -m requirements_alchemist
```

Open `http://127.0.0.1:5070`. The default configuration uses `replay`, which
demonstrates the workflow without sending data to an LLM. For live generation:

```bash
RA_LLM_PROVIDER=openai-compatible
RA_LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=...
python -m requirements_alchemist
```

For Ollama or vLLM:

```bash
RA_LLM_PROVIDER=openai-compatible
RA_LLM_BASE_URL=http://127.0.0.1:11434/v1
RA_LLM_MODEL=qwen2.5:14b
python -m requirements_alchemist
```

The local model must support reliable JSON-object output. Larger instruction models
generally produce more complete decomposition and traceability.

For a keyless recording, select **Load guided demo** in the UI. It loads a bundled expense
reimbursement PRD and three detailed draft stories. The complete recording script is
`docs/demo/requirements-alchemist-video-guide.md`.

## Connect Figma and Atlassian

Provide secrets only through environment variables:

```bash
FIGMA_ACCESS_TOKEN=...
ATLASSIAN_BASE_URL=https://your-domain.atlassian.net
ATLASSIAN_EMAIL=...
ATLASSIAN_API_TOKEN=...
JIRA_PROJECT_KEY=PROJ
```

Then edit `config/requirements-alchemist.json`:

1. Add approved PRD hostnames to `allowed_source_hosts`.
2. Set `atlassian_base_url` or use `ATLASSIAN_BASE_URL`.
3. Set `jira_project_key` or use `JIRA_PROJECT_KEY`.
4. Keep `jira_push_enabled` false until the workflow is verified.
5. Set `RA_JIRA_PUSH_ENABLED=true` only when Jira creation is intended.

Jira publication is append-only. It skips unapproved stories when
`require_human_approval` is true, records the created key in canonical JSON, and
skips stories that already have a key.

## Human review workflow

1. Load all available product evidence.
2. Generate a DRAFT package.
3. Review source citations, assumptions, open questions, scope, acceptance criteria,
   and non-functional requirements in the UI or exported workbook.
4. Set each accepted story to `APPROVED` and name the reviewer.
5. Import the workbook, if review occurred in Excel.
6. Optionally add approved high-quality stories to local RAG.
7. Export approved stories to the assurance agent and/or enable Jira publishing.

The workbook is a review projection, not the source of truth. Only the `Human Review`
sheet is imported. Story content remains in canonical JSON to prevent unnoticed
spreadsheet edits.

## Safety and operating boundaries

- The service binds to loopback by default and uses per-session CSRF tokens.
- URL ingestion requires HTTPS, checks DNS, rejects private/reserved addresses, does
  not follow redirects, and can be restricted to an explicit hostname allowlist.
- Secrets are never stored in configuration, generated JSON, Excel, or RAG files.
- Figma, Confluence, and Jira ingestion is read-only. Jira writes require a separate
  configuration gate and human approval.
- Generated requirements are advisory drafts. They do not replace product-owner,
  architecture, security, legal, accessibility, or engineering review.
- The reference corpus supplies writing patterns only. Product facts must cite loaded
  product evidence.

See the full PRD and flow in `docs/prd/003-requirements-alchemist.md` and
`docs/diagrams/requirements-alchemist-flow.md`.
