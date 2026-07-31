# Custodian Kernel

### Give agents authority without giving away control.

Custodian is a provider-neutral policy and evidence kernel for AI agents. It
evaluates proposed actions against rules you own, routes consequential work to
an operator when needed, and records each decision in a tamper-evident ledger.

The kernel is not tied to one model or harness. Codex Guard brings it into
OpenAI Codex. Hermes Guard brings it into Hermes Agent. Talaria builds a richer
Hermes control experience on top.

## What it governs

Custodian uses the same decision boundary for:

- filesystem reads and writes;
- shell commands and package changes;
- network destinations and credentials;
- production and destructive operations;
- spending and other money-shaped actions;
- personal data, prompt injection, retry loops, and attempts to modify
  Custodian itself.

Each action receives a verdict, authority band, reason, and authenticated
receipt. Receipts store bounded metadata rather than prompts, credentials, or
tool results.

## Start here

Version 0.4.2 is available as a GitHub release.

Install from PyPI:

```bash
pipx install custodian-kernel
custodian doctor
custodian
```

The bare `custodian` command opens the operator menu. It can create a
workspace, inspect policy, manage gates, show evidence, and list guarded tools
without requiring you to memorize every subcommand.

On Linux distributions that enforce PEP 668, use `pipx` or a virtual
environment. Do not use `--break-system-packages`.

The repository also includes `install-custodian.py`, an atomic managed
installer for machines where an application-style runtime is preferable:

```bash
python install-custodian.py
```

It creates a private runtime and exposes the Custodian commands without
writing packages into the operating system's Python environment.

## Choose an integration

| Environment | Package | Operator command |
|---|---|---|
| Kernel and Paladin only | `custodian-kernel` | `custodian` |
| OpenAI Codex | `custodian-codex-guard` | `custodian-codex setup` |
| Hermes enforcement only | `custodian-hermes-guard` | `custodian-hermes setup` |
| Complete Hermes experience | `custodian-talaria` | `talaria setup` |

Integration packages depend on the kernel. The kernel does not import a
harness adapter.

## The decision path

```text
agent proposes an action
        |
        v
mandatory guards inspect tool, arguments, scope, and policy
        |
        +-- autonomous --> execute within the harness boundary
        |
        +-- ask --> wait for an exact, authenticated operator approval
        |
        +-- block --> stop with a reason
        |
        v
append a value-free, hash-chained receipt
```

An approval is not a reusable "yes." It is single-use, expires, and binds the
tool, action class, arguments, workspace, requester, and policy version. A
changed action requires a new decision.

## Gates

A fresh installation starts in open monitoring mode with visible notices.
That lets an operator observe real workloads before closing gates:

```bash
custodian gates status
custodian gates protect
custodian gates open
custodian gates notifications quiet
```

Open mode permits configured actions while retaining receipts. Protected mode
requires approval for configured consequential classes. Gate rules can target
a harness, tool, workspace, or action class.

## The control plane

```bash
custodian doctor
custodian health --format json
custodian console
custodian gates status
custodian adapters list
custodian-verify
```

`custodian console` is the live operator view for pending approvals, hard
blocks, gate policy, filesystem scopes, and receipt visibility. Hard blocks
are not pending approvals. They identify actions that violated a boundary,
such as declaring a home directory or filesystem root as the workspace.

## Paladin credential broker

The kernel distribution currently includes Paladin, an encrypted vault and
credential broker. Agents use a reference such as `paladin://github_token`
instead of receiving the value in a prompt or configuration file.

Grants restrict which requester and authority band may resolve each entry.
Paladin can also limit a credential to approved hosts. Vault values never
belong in Custodian receipts.

```bash
paladin init
paladin list
paladin audit verify
```

The code maintains a strict import boundary between Custodian and Paladin even
though they ship in the same distribution today.

## State and upgrades

Custodian keeps personal control-plane state under `~/.custodian`. Workspaces
keep their own policy and state in the directory you select. Paladin stores
vault and audit data under `~/.paladin`.

Package upgrades and normal uninstall operations preserve this data. Preview
removal before applying it:

```bash
custodian uninstall --dry-run
custodian uninstall --yes
```

## Security boundary

Custodian is defense in depth, not an operating-system sandbox. Its guarantees
depend on the harness routing actions through the installed enforcement
boundary and on protecting operator state from the agent.

Custodian is alpha software and has not received a third-party security audit.
Read [SECURITY.md](SECURITY.md) before using it for consequential work.

## Release status

The 0.4.2 release has passed more than 3,000 source tests, clean-wheel
installation, strict artifact validation, reproducible-build checks, and
independent qualification on Linux and Windows. macOS qualification remains
pending.

## Links

- [Source](https://github.com/KeyArgo/custodian-kernel)
- [Codex Guard](https://github.com/KeyArgo/custodian-codex-guard)
- [Hermes Guard](https://github.com/KeyArgo/custodian-hermes-guard)
- [Talaria](https://github.com/KeyArgo/custodian-talaria)
- [Documentation](https://getcustodian.xyz/docs)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
