# Custodian Codex Guard

Policy guard for Codex CLI. Evaluates every coding-agent action (read, write,
execute, network, package, approval) before execution — fail-closed, evidence-
preserving, and independent of the model or approval backend.

Watch the demo: [Custodian Codex Guard: A Safety Layer for AI Coding
Agents](https://youtu.be/lnIwDIbzZf0).

## Install

Custodian Codex Guard 0.1.2 supports Linux and macOS with Python 3.11 through
3.13. Windows is not supported by this release because it depends on Custodian
Kernel 0.4.1. Windows support is planned with Custodian Kernel 0.4.2.

```bash
python -m pip install custodian-codex-guard
custodian-codex setup
custodian-codex doctor
```

Requires `custodian-kernel` (installed automatically as a dependency).
Users do not need to activate or manage a virtual environment when Custodian
is installed through its managed installer.

Run setup from any directory. The installed package carries the Codex plugin
files it needs; a source checkout is not required.

## Gate behavior

Custodian's gate mode is an operator preference, shared by supported harnesses.
Inspect it with:

```bash
custodian gates status
```

`open` permits matching policy rules to auto-pass all action classes.
Notifications may be enabled to show those passes or disabled to avoid routine
messages. `protect` requires approval for configured high-risk classes.
Decisions continue to produce value-free evidence in the Custodian ledger.

The guard evaluates routed tool calls before Codex's own approval decision.
It supplements Codex's sandbox and permissions; it does not replace operating
system isolation or govern tools that are not routed through the installed
hook/MCP boundary.

## Remove

```bash
python -m pip uninstall custodian-codex-guard
```

Uninstalling the package does not delete `~/.custodian`, receipts, approvals,
gate preferences, policies, or vault data. To remove the Codex hook first:

```bash
custodian-codex hook-uninstall
```

## Security

Report vulnerabilities privately using the instructions in
[SECURITY.md](SECURITY.md). Do not include credentials, vault contents, or
private receipts in a public issue.

- Documentation: https://getcustodian.xyz/docs
- Source: https://github.com/KeyArgo/custodian-codex-guard
- Package: https://pypi.org/project/custodian-codex-guard/
