# Custodian 0.4 control-plane topology

Status: normative implementation specification for the coordinated 0.4 release.

## Product shape

Custodian is a platform with separately installable integrations. The kernel
defines neutral authority and event contracts; adapters translate proposals;
an executor enforces approved capabilities; Paladin mediates credentials; the
operator service owns human approval; and the Console presents the system.

```text
                            HUMAN OPERATOR
                                  |
                    +-------------v-------------+
                    |     CUSTODIAN CONSOLE     |
                    | TUI / optional local GUI  |
                    | approvals, policy, audit  |
                    | adapters, emergency stop  |
                    +-------------+-------------+
                                  | authenticated local channel
                    +-------------v-------------+
                    |   OPERATOR CONTROL PLANE  |
                    | identity and authentication|
                    | approval lifecycle        |
                    | configuration and health  |
                    +--------+----------+--------+
                             |          |
                     decision|          |events/queries
                     requests|          |
                  +----------v--+   +---v-------------------+
                  | CUSTODIAN   |   | UNIVERSAL LEDGER      |
                  | KERNEL      +-->| append-only events    |
                  | authority   |   | correlation/idempotency|
                  | policy      |   | tamper evidence       |
                  | allow/ask/deny | | execution outcomes   |
                  +------^------+   +-----------^-----------+
                         |                      |
                         | normalized proposals | normalized events
        +----------------+----------------------+----------------+
        |                 ADAPTER / BROKER LAYER                 |
        | Codex | Talaria/Hermes | Claude | Stripe | custom/RMM |
        | translate proposals, enforce verdicts, report outcome  |
        +----------+----------------------+---------------------+
                   |                      |
                   | authorized capability|credential reference
             +-----v----------------+  +--v--------------------+
             | DELEGATED EXECUTOR   |  | PALADIN               |
             | verify signature     |  | vault and grants      |
             | enforce single use   |  | scoped injection      |
             | sandbox + egress     |  | never return raw value|
             +----------+-----------+  +----------+------------+
                        |                         |
        +---------------v-------------------------v-------------+
        |                    REAL SYSTEMS                       |
        | files, shell, GitHub, cloud, production, money, SaaS |
        +-------------------------------------------------------+
```

## Required action lifecycle

```text
proposed -> evaluated -> allowed
                     -> denied
                     -> approval_requested -> denied/expired
                                           -> approved
approved -> capability_issued -> execution_started
          -> succeeded | failed | reversed
```

Every transition uses one correlation ID. Retries use an idempotency key.
Approvals and capabilities bind the exact effective action, requester,
workspace/tenant, policy version, expiry, and permitted execution count.

## Trust boundary

Agents may propose actions and read sanitized outcomes. They may not mint,
approve, extend, or reset authority. Only the authenticated operator channel
may approve or deny. The executor accepts a signed, unexpired, unconsumed
capability and records the result. Paladin injects an authorized credential
into the target process or connector without returning it to model context.

Enforcement strength is explicit for every adapter:

- `advisory`: recommendation only;
- `routed`: cooperating caller consults Custodian;
- `brokered`: real capability exists only behind the Custodian executor;
- `native`: host lifecycle hook prevents bypass.

No UI or documentation may describe a routed adapter as universal
interception.

## Component ownership

- **Kernel:** neutral proposal, verdict, policy and ledger interfaces.
- **Universal ledger:** durable normalized lifecycle evidence, not business
  logic and never raw secrets/prompts/file contents. Every event/receipt is
  stamped with its originating harness (server-side, never model-supplied).
  No adapter sees any records by default, not even its own — the agent being
  governed is exactly the party a denial log exists to constrain, and
  self-visibility would turn the ledger into an oracle it could probe to
  learn the enforcement boundary. Visibility, including an adapter's own
  history, is only ever an explicit operator grant
  (`custodian/control/ledger_access_policy.py`, editable via `custodian
  console`'s `[G]` key). The operator's own view stays unscoped across every
  adapter — the isolation boundary is agent-to-adapter, not operator-to-agent.
- **Operator service:** authenticated approvals, denials, configuration,
  adapter health and emergency recovery.
- **Console:** TUI first; an optional local web GUI uses the same service API.
- **Executor:** capability validation, sandbox/egress enforcement and outcome
  reporting.
- **Paladin:** vault, grants and credential injection after authorization.
- **Adapters:** translation plus mechanical enforcement; no approval authority.
- **Websites:** clients of public APIs, never hardcoded into kernel behavior.

## Repository and package boundaries

- `custodian-kernel`: kernel and stable neutral contracts.
- `custodian-codex`: Codex plugin, MCP bridge and Codex-facing Console profile.
- `custodian-talaria`: thick Hermes integration.
- additional harness/provider integrations follow the same dependency pattern.

The coordinated product may be marketed as Custodian 0.4 while remaining
separately installable. Integration packages depend on a bounded compatible
kernel version; the kernel never imports an integration.

## Compatibility requirements

- Preserve existing 0.4 kernel, Paladin vault and Codex receipt data.
- Migrations are explicit, atomic, restartable and tested on copies.
- Linux and Windows are first-class; macOS must not be intentionally blocked.
- `custodian setup` remains the umbrella installer; detected software is never
  installed or enabled without explicit confirmation.
- `custodian doctor` reports missing integrations without changing state.
- Emergency disable preserves ledger, approvals and diagnostic evidence.

## Release gates

No merge, tag or publication occurs until focused adversarial tests, full
regression tests, clean artifact installation, upgrade compatibility, secret
scanning, plugin validation and Linux/Windows smoke tests pass. Hackathon
submission may use a release-candidate branch, but must state the enforcement
boundary honestly.
