# Governed OpenCode

Install the fail-closed OpenCode hook once:

```console
custodian-opencode setup
custodian-opencode doctor
custodian-opencode
```

The generated global plugin evaluates every OpenCode tool call through the
same Custodian guard, approval store, filesystem policy, and receipt chain as
Codex. It covers reads, edits, writes, patches, shell commands, web access,
unknown tools, and delegated tasks. `opencode --auto` cannot override the
hook: the hook runs before the tool and throws on denial or escalation.

Harness identity is assigned by the installed adapter, not accepted from the
model. OpenCode-specific deny/ask/auto rules are evaluated for every action,
including ordinary reads and writes, before the tool is allowed to run.

Use `custodian-opencode`, rather than the raw binary, for a governed launch.
The wrapper refuses `--pure`, because OpenCode documents that option as
disabling external plugins. `custodian-opencode doctor` detects a missing,
modified, or interpreter-stale hook and refuses to launch.

## Enforcement boundary

This adapter provides routed enforcement inside OpenCode. A process running
under the same OS account can still invoke an unwrapped executable or modify
its own user configuration. Strong containment against a hostile same-user
process requires Custodian's brokered executor plus an OS sandbox or separate
service account. The adapter does not claim to replace that boundary.

If Custodian is unavailable, returns malformed data, encounters an unknown
tool, or cannot identify the workspace/requester, execution is denied.
