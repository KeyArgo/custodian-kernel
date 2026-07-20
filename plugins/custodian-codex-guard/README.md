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
codex mcp add custodian-codex-guard -- custodian-codex-guard-mcp
```

The plugin manifest is at
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

`guard_action` only returns `autonomous`, `escalation_required`, or `denied`.
An escalation is never permission to execute. The caller must enforce the
result and must fail closed if Guard is unavailable. Arguments are inspected
but never persisted; receipts contain the tool name and decision metadata, not
commands, file contents, prompts, or secret values.
