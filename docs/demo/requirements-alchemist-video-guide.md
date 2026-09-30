# Requirements Alchemist — demo video guide

**Author:** Vivek
**Recommended recording length:** 5–7 minutes
**Demo URL:** `http://127.0.0.1:5070`

## Before recording

From the repository root:

```bash
.venv/Scripts/python.exe -m requirements_alchemist
```

The committed configuration starts in keyless `replay` mode. No Figma, Atlassian, or LLM
credentials are required for the guided demo. Keep Jira publishing disabled while recording.

For live synthesized chat/generation with locally hosted Ollama:

```powershell
.\scripts\run-requirements-alchemist-ollama.ps1 -Pull
```

The first run downloads `qwen2.5:7b`; later runs omit `-Pull`. Model inference and prompts
remain on the machine.

## Recording script

### 1. Introduce the problem — 30 seconds

Show the header and explain:

> Requirements Alchemist turns PRD, Figma, Confluence, and Jira evidence into detailed,
> traceable stories. The model proposes; a human approves; Jira writes are disabled by default.

### 2. Load the guided source — 30 seconds

Select **Load guided demo**. Point out:

- the bundled expense-reimbursement PRD;
- evidence type and source ID;
- that this is a keyless, recorded fixture suitable for repeatable demos.

Optionally show that users can instead paste a PRD, upload a text/Markdown/JSON/YAML file, or
enter an allowlisted Figma, Confluence, Jira, or PRD URL.

### 3. Inspect generated stories — 2 minutes

Scroll through the three draft stories:

1. employee expense submission;
2. manager approval/rejection with self-review and concurrency controls;
3. finance CSV export with formula-injection protection.

Highlight:

- persona/capability/value narrative;
- in/out scope;
- positive and negative Given/When/Then criteria;
- measurable security, accessibility, reliability, privacy, and performance requirements;
- dependencies, assumptions, risks, test notes, confidence, and exact PRD citations;
- unresolved questions instead of invented answers.

### 4. Demonstrate grounded chat — 45 seconds

Ask:

> What requirements cover duplicate submissions and concurrent manager decisions?

In replay mode, the chat displays retrieved evidence and source IDs. With a live/local LLM it
synthesizes the grounded answer and citations.

Then ask:

> Which product decisions remain unresolved before these stories are ready?

### 5. Demonstrate human governance — 1 minute

For `STORY-001`:

1. set status to `APPROVED`;
2. enter reviewer `Vivek`;
3. add `Reviewed evidence, scope, and acceptance criteria`;
4. select **Save review**;
5. select **Add approved story to RAG**.

Explain that only approved stories can become future reference examples.

### 6. Show delivery choices — 1 minute

- **Export Excel:** explain Package, Stories, Acceptance Criteria, Non-functional, Human Review,
  and Sources sheets.
- **Export approved for assurance:** downloads the existing assurance-agent story contract.
- **Push approved to Jira:** show that it is disabled by default; enabling it requires explicit
  configuration and Atlassian credentials.

Mention that Excel imports only review decisions. Spreadsheet edits cannot silently overwrite
canonical story content.

### 7. Close — 20 seconds

Summarize:

> The result is a source-grounded, reviewable backlog with a controlled path to Excel, Jira,
> the assurance agent, and a continuously improving approved-story RAG corpus.

## Recording tips

- Use a 1440×900 or 1920×1080 browser window at 100% zoom.
- Hide bookmarks, notifications, terminals containing environment variables, and browser
  password-manager prompts.
- Do not enable or display real Atlassian/Figma tokens.
- Record the browser, not `.env` or connector configuration.
- Reset and reload the guided demo between takes for deterministic content.
