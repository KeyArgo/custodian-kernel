# Custodian Site Flowchart

_Last updated: 2026-06-30_

This is the current user-facing flow as the codebase implements it today, plus the intended guided path you described.

## Implemented user journey

```mermaid
flowchart TD
    A[Start: Home /] --> A1{Choose a mode}
    A1 -->|Quick walkthrough| B[Console /console]
    A1 -->|Deep dive| B
    A1 -->|Browse freely| C[Browse any page]
    A --> A2[Mobile greeting only]

    B --> B1[Quick mode auto-starts 6-step Console explainer]
    B --> B2[Deep mode opens Nemotron in explainer mode]
    B --> B3[Console AI points to Operator at the right moment]
    B3 --> D[Operator /operator]

    D --> D1[Step 0: Earn $1200]
    D1 --> D2[Step 1: Autonomous $85 spend]
    D2 --> D3[Step 2: Request $3500]
    D3 --> D4[Step 3: Human approves by SMS]
    D4 --> D5[Step 4: Engage kill switch]
    D5 --> D6[Step 5: Prove kill switch blocks spend]
    D6 --> D7[Step 6: Release kill switch]
    D7 --> D8[Step 7: Refund $85]
    D8 --> D9[Step 8: Human approves refund by SMS]
    D9 --> E[Return to Console audit + policy]

    E --> F[Triage /triage]
    F --> F1[Run preset or custom lie]
    F1 --> F2[Nemotron reasons]
    F2 --> F3[Verifier contradicts or confirms]
    F3 --> G[Tools /tools]
    G --> H[Docs /docs]
```

## Assistant continuity now

```mermaid
flowchart LR
    S[site-tour.js shared state] --> H[Console]
    S --> O[Operator]
    S --> R[Triage]
    S --> T[Tools]
    S --> D[Docs]
    H -->|shared Nemotron history| O
    O -->|step 8 sets pending console followup| H
    R -->|triage completion nudges tools| T
    T -->|tools completion nudges docs| D

    X[Shared backend prompt + site_context] --> H
    X --> O
    X --> R
    X --> T
    X --> D
```

## What is working now

1. Home now offers `Quick walkthrough`, `Deep dive`, and `Browse freely`.
2. Mobile does not auto-open a blocking assistant panel.
3. Console and operator share state and chat history.
4. Operator step completion now hands the user back to the console audit.
5. Triage, tools, and docs are part of the same guided path.
6. Tools and docs now include lightweight guide copy instead of a dead-end surface.

## Desired story the site now tells

```mermaid
flowchart TD
    A[Home] --> B[Fast orientation]
    B --> C[Console explains the system]
    C --> D[Operator proves it live]
    D --> E[Console interprets the proof]
    E --> F[Triage proves AI alone is not enough]
    F --> G[Tools proves the scope is broad]
    G --> H[Docs explains the architecture]
    I[Dismiss AI any time] --> J[Small reopen path remains]
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
