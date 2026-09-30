# Requirements Alchemist — end-to-end flow

**Author:** Vivek

## Product flow

```mermaid
flowchart TD
    Start([Start local workspace]) --> Configure[Configure LLM and optional connector credentials]
    Configure --> Add{Add product evidence}
    Add -->|Paste / upload| PRD[PRD text document]
    Add -->|Figma URL| Figma[Figma node and text extraction]
    Add -->|Confluence URL| Conf[Confluence page extraction]
    Add -->|Jira URL| JiraRead[Jira issue context extraction]
    PRD --> Inventory[Evidence inventory]
    Figma --> Inventory
    Conf --> Inventory
    JiraRead --> Inventory
    Inventory --> Scope[Enter backlog objective and optional reference query]
    Scope --> Retrieve[Retrieve exemplary story patterns with local BM25]
    Retrieve --> Generate[LLM structured story decomposition]
    Inventory --> Generate
    Generate --> Validate{Schema and source references valid?}
    Validate -->|No| Error[Return actionable error; publish nothing]
    Error --> Scope
    Validate -->|Yes| Draft[Normalize IDs and force every story to DRAFT]
    Draft --> Save[(Save canonical JSON)]
    Save --> ReviewChoice{Review channel}
    ReviewChoice -->|Browser| Browser[Inspect criteria, NFRs, questions, citations]
    ReviewChoice -->|Excel| Export[Export macro-free workbook]
    Export --> HumanExcel[Human completes Human Review sheet]
    HumanExcel --> Import{Workbook safety and package checks pass?}
    Import -->|No| RejectImport[Reject workbook; preserve canonical JSON]
    RejectImport --> Export
    Import -->|Yes| Browser
    Browser --> Chat[Grounded chat over evidence and generated stories]
    Chat --> Browser
    Browser --> Decision{Reviewer decision per story}
    Decision -->|Needs change| Scope
    Decision -->|Reject| Rejected[Persist REJECTED with reason]
    Decision -->|Approve| Approved[Persist APPROVED with reviewer]
    Approved --> Reference{Exemplary enough for local RAG?}
    Reference -->|Yes| AddRag[Store approved story with provenance]
    Reference -->|No| Delivery
    AddRag --> Delivery{Delivery output}
    Delivery -->|Excel only| Done([Reviewed artifact complete])
    Delivery -->|Assurance ZIP| Assurance[Run approved stories through PR/UX assurance]
    Assurance --> Done
    Delivery -->|Jira disabled| Enable[Explicitly configure Jira write gate]
    Enable --> Delivery
    Delivery -->|Jira enabled| Gate{Approved and not previously published?}
    Gate -->|No| Skip[Return SKIPPED with reason]
    Gate -->|Yes| Create[Create Jira story with ADF and source traceability]
    Create --> Result{API result}
    Result -->|Success| PersistKey[Persist Jira key; future publication skips]
    Result -->|Failure| Failed[Return FAILED; retain draft package]
    PersistKey --> Done
    Failed --> Browser
    Skip --> Done
    Rejected --> Done
```

## Generation sequence

```mermaid
sequenceDiagram
    actor User
    participant UI as Browser UI
    participant WS as Workspace
    participant SL as Source Loader
    participant RAG as BM25 Corpus
    participant LLM as Configured LLM
    participant V as Pydantic Validator
    participant FS as Canonical JSON

    User->>UI: Add PRD/Figma/Confluence/Jira
    UI->>WS: CSRF-protected source request
    WS->>SL: Validate and load
    SL-->>WS: SourceDocument
    WS->>RAG: Rebuild source + reference chunks
    User->>UI: Generate(title, objective)
    UI->>WS: GenerationInput
    WS->>RAG: Search exemplary patterns
    RAG-->>WS: Licensed/provenanced chunks
    WS->>LLM: Policy + evidence + patterns + JSON schema
    LLM-->>WS: Story package JSON
    WS->>V: Validate contracts
    alt Invalid output
        V-->>UI: Validation error; no package persisted
    else Valid output
        V->>V: Normalize IDs, citations, DRAFT state
        V->>FS: Atomic package projection
        V-->>UI: Reviewable StoryPackage
    end
```

## Human review and Jira sequence

```mermaid
sequenceDiagram
    actor Reviewer
    participant UI as Browser / Excel
    participant Canonical as StoryPackage JSON
    participant Gate as Publication Gate
    participant Jira as Jira Cloud

    Canonical-->>UI: Review projection
    Reviewer->>UI: APPROVED / NEEDS_CHANGE / REJECTED + comment
    UI->>Canonical: Review metadata only
    Reviewer->>Gate: Publish approved stories
    Gate->>Gate: Check feature flag, config, approval, existing Jira key
    alt Not eligible
        Gate-->>Reviewer: SKIPPED + explicit reason
    else Eligible
        Gate->>Jira: Create issue (ADF + labels + issue property)
        alt Created
            Jira-->>Gate: Issue key
            Gate->>Canonical: Persist Jira key
            Gate-->>Reviewer: CREATED + browse URL
        else API failure
            Jira-->>Gate: Error
            Gate-->>Reviewer: FAILED; canonical story remains unpublished
        end
    end
```

## State model

```mermaid
stateDiagram-v2
    [*] --> DRAFT: generated
    DRAFT --> NEEDS_CHANGE: reviewer requests changes
    NEEDS_CHANGE --> DRAFT: regenerate or revise canonical source
    DRAFT --> REJECTED: reviewer rejects
    NEEDS_CHANGE --> REJECTED: reviewer rejects
    DRAFT --> APPROVED: reviewer accepts
    NEEDS_CHANGE --> APPROVED: issues resolved
    APPROVED --> PUBLISHED: Jira create succeeds
    APPROVED --> APPROVED: Jira disabled / failed / skipped
    REJECTED --> [*]
    PUBLISHED --> [*]
```

`PUBLISHED` is represented by an `APPROVED` story with a non-empty `jira_key`; it is shown
separately here to make the lifecycle explicit.
