# Custodian Site Flowchart

_Last updated: 2026-06-30_

This is the current user-facing flow as the codebase implements it today, plus the intended guided path you described.

## Current user journey

```mermaid
flowchart TD
    A[Start: Home /] --> B[Console /hermes]
    A --> C[Operator /operator]
    A --> D[Triage /triage]
    A --> E[Tools /tools]
    A --> F[Docs /docs]

    B --> B1[Read static 3-box flow explainer]
    B --> B2[Watch live pipeline rail]
    B --> B3[Open Nemotron chat]
    B3 --> B4[Ask 2 questions]
    B4 --> B5[Console nudges visitor to Operator]
    B5 --> C

    C --> C1[Step 0: Earn $1200]
    C1 --> C2[Step 1: Autonomous $85 spend]
    C2 --> C3[Step 2: Request $3500]
    C3 --> C4[Step 3: Human approves by SMS]
    C4 --> C5[Step 4: Engage kill switch]
    C5 --> C6[Step 5: Prove kill switch blocks spend]
    C6 --> C7[Step 6: Release kill switch]
    C7 --> C8[Step 7: Refund $85]
    C8 --> C9[Step 8: Human approves refund by SMS]

    C --> C10[Mini audit feed updates]
    C --> C11[Operator Nemotron chat opens if history exists]

    C9 -. missing explicit handoff .-> B6[Return to Console audit feed]
    B6 --> B7[Inspect exact audit entries]

    B --> D
    D --> D1[Try preset lie or custom claim]
    D1 --> D2[Nemotron reasons]
    D2 --> D3[Verifier contradicts or confirms]
    D3 --> D4[Triage Nemotron explains why]

    D --> E
    E --> E1[Browse governed tools]
    E --> E2[No assistant today]

    E --> F
    F --> F1[Read docs]
    F --> F2[No assistant today]
```

## Assistant continuity today

```mermaid
flowchart LR
    H[Console chat] -->|localStorage history| O[Operator chat]
    H -->|not implemented directly| T[Tools]
    H -->|not implemented directly| D[Docs]
    O -->|localStorage history| H
    O -->|soft continuity only| R[Triage chat]
    R -->|sessionStorage history only| R2[Same tab triage continuity]

    X[Shared backend prompt] --> H
    X --> O
    X --> R

    style T fill:#2b1d1d,stroke:#ff5c5c,color:#fff
    style D fill:#2b1d1d,stroke:#ff5c5c,color:#fff
    style R fill:#2b1d1d,stroke:#ffb000,color:#fff
```

## What is working now

1. The console is the strongest guided experience.
2. The console assistant can push people into the operator panel.
3. The operator panel preserves conversation history from the console.
4. The operator panel has a live mini audit feed, so the user can see something updating while they run steps.
5. The triage page has its own assistant and can explain lie-catch behavior.

## Where the flow breaks now

1. The “flow chart” on the console explains architecture, not the full site journey.
2. After the operator refund flow finishes, the AI does not explicitly say “go back to the console audit feed now.”
3. The operator assistant is not event-aware. It does not react to step completion with contextual next-step guidance.
4. Triage uses `sessionStorage` for history while console/operator use `localStorage`, so continuity is inconsistent.
5. Tools and docs have no assistant layer, so the guided journey stops there.
6. There is no single persistent assistant shell shared across all pages.

## Intended guided path

```mermaid
flowchart TD
    A[Start on Home] --> B[Open Console]
    B --> C[AI introduces itself and the big idea]
    C --> D[AI suggests: run the live Operator demo]
    D --> E[Open Operator]
    E --> F[Run all 9 demo steps]
    F --> G[AI notices the final refund approval completed]
    G --> H[AI offers: go back to Console audit feed]
    H --> I[Return to Console]
    I --> J[AI highlights the exact audit entries]
    J --> K[AI suggests: now try Lie-Catch / Triage]
    K --> L[Open Triage]
    L --> M[Run a lie scenario]
    M --> N[AI explains why verifier beat the model]
    N --> O[AI suggests: inspect the governed tool surface]
    O --> P[Open Tools]
    P --> Q[AI suggests likely questions about tool bands]
    Q --> R[Open Docs]
    R --> S[AI helps answer deeper architecture questions]

    U[User wants quiet browsing] --> V[Dismiss AI]
    V --> W[Small reopen button remains available]
```

## Short version

If you want the site to feel coherent, the assistant should own this exact sequence:

1. `Home -> Console`
2. `Console -> Operator`
3. `Operator -> Console audit`
4. `Console audit -> Triage`
5. `Triage -> Tools`
6. `Tools -> Docs`

And the assistant should be dismissible, not mandatory.

