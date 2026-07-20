# Custodian Guard for Codex

A capability firewall for coding agents. Codex can inspect, test, and edit
inside an approved workspace; credential use, network operations, destructive
commands, production changes, money movement, and governance changes stop at a
human-approval boundary. Every decision produces a value-free HMAC hash-chained
receipt.

This plugin is generic. It does not know about `getcustodian.xyz`, the demo
website, or any particular operator. A site or IDE is a client of the MCP
boundary, never part of the kernel.

## Install for judging

From the repository root, with Python 3.11 or later:

```bash
python -m venv .venv
# Linux/macOS
. .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e .
custodian-codex doctor
codex plugin marketplace add .
codex plugin add custodian-codex-guard@custodian-build-week
```

Start a new Codex thread after installation so it loads the plugin. The plugin manifest is at
`plugins/custodian-codex-guard/.codex-plugin/plugin.json`. Its skill is at
`plugins/custodian-codex-guard/skills/govern-codex/SKILL.md`; install/import
that plugin in Codex to make the pre-action workflow automatic in conversation.

## Sixty-second proof

```bash
python scripts/codex-guard-demo.py
pytest -q tests/test_codex_guard.py
```

The demo performs no network calls and changes no external state. It shows a
safe test and workspace edit passing, `.env` access being denied, deliberately
misclassified delete/deploy commands being independently upgraded to human
escalation, a valid receipt chain, and rejection after receipt tampering.

## Enforcement contract

`guard_action` returns `autonomous`, `escalation_required`, `approved`, or
`denied`. An escalation is never permission. The model can create a pending
request but cannot approve it; the operator runs `custodian-codex approve ID`
outside the model tool boundary. Approval binds the exact tool, effective risk
class, arguments, resolved workspace, requester, and policy version; it expires
and can be consumed once. Arguments are inspected but never persisted;
receipts contain decision metadata, not commands, file contents, prompts, or
secret values.

This is an application-layer guard for actions routed through the plugin. It
complements Codex sandboxing and approvals; it does not claim to intercept an
unintegrated runner or replace operating-system isolation.
