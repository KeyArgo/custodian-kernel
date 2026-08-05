# Paladin handover — 2026-08-03

Repository: `/mnt/homes/Development/custodian-dev`  
Branch: `feat/confined-bubblewrap-beta`

Make all changes only in this repository, not under `~/`. Do not push, tag,
publish, install over the live Paladin vault, or touch real credentials without
explicit operator authorization. Never request, print, or handle raw
credentials; use `paladin://…` references.

## Snapshot

The worktree was clean immediately after commit `967879d`. Custodian Guard
receipt integrity verified with 7,965 valid receipts. No deployment, release,
push, or live-vault change was performed.

Recent commits, newest first:

```
967879d feat(paladin): preserve imported credential usernames
f8a92eb feat(paladin): add optional credential usernames
88140f1 docs: prepare repository for open source contributors
f564d44 fix(release): validate hardened beta path
0bed854 Seal Paladin backup metadata
265e917 Fail closed when Paladin audit cannot be read
c2a8b20 feat(sandbox): harden confined profile readiness
dac26da Make Paladin entry edits atomic
c9358fa Report Paladin Guard forensic audit status
c9d3515 Add Paladin audit integrity guard
26138c9 Link Custodian menu to Paladin credential console
d124b7f Support atomic Paladin entry rename and full metadata editing
cfb694e feat(sandbox): add opt-in confined execution core
```

## Completed work

### Optional credential usernames

`paladin add` and `paladin edit` now support `--username`. The interactive
menu validates IDs before prompting for a value and asks for an optional account
or login name. Secret IDs accept only letters, numbers, `.`, `_`, `-`, and `/`;
the error explains that spaces are not allowed and that the login should be
stored with `--username`.

Username is stored within the encrypted vault entry and returned in entry
metadata, but not shown in the default list table. Blank username on edit
clears it.

Relevant files:

- `paladin/vault.py`
- `paladin/cli.py`
- `paladin/menu.py`
- `docs/PALADIN.md`
- `tests/test_paladin.py`
- `tests/test_paladin_menu.py`

### Username-preserving imports

Supported imports preserve optional usernames from password-manager records,
CSV, and JSON object arrays. The importer passes that value into `Vault.add`.

Relevant files:

- `paladin/importer.py`
- `tests/test_paladin_import.py`

Focused validation passed:

```
53 passed in 8.38s
```

### Open-source front doors

Added contributor, security-reporting, and conduct documents plus GitHub issue
and pull-request templates. Security contact: `hello@inovinlabs.com`.

No direct comparison material or competitor references should be reintroduced
into docs, comments, tests, commits, issues, PRs, or release notes.

## Existing security properties

### Atomic edits

Entry edits validate and save atomically, avoiding partial rename, rotation, or
grant-migration state after an invalid field.

### Audit integrity / Paladin Guard

Non-owner credential resolution verifies the HMAC audit chain first. Invalid or
unreadable audit records fail closed for non-owner access; `user:cli` remains an
operator recovery path. This identity is only a label, not proof of a human,
until process confinement prevents same-user impersonation.

Commands:

```bash
paladin guard
paladin guard --backups ~/paladin-backups
paladin audit verify
```

### Sealed backups

`paladin-backup/2` encrypts the vault, audit, and manifest together with
authenticated encryption. Restore remains compatible with legacy ZIP backups
and bare vault files. Historic backups are not changed; make a fresh sealed
backup only after safely validating the upgraded code.

## Bubblewrap boundary

Target interface:

```bash
paladin exec --sandbox --with <paladin-ref> -- <command>
```

Required behavior:

- no plaintext credential in the child environment;
- no unrestricted child networking;
- credential-bearing calls only through constrained Paladin egress;
- grants, hosts, HTTP method/path scope, TTL, and audit enforced;
- sandbox mode fails closed if Bubblewrap is unavailable.

Earlier local testing found `bwrap` present but unavailable because a direct
test could not create a `NETLINK_ROUTE` socket. Treat this as a host/container
policy or user-namespace issue. Do not silently fall back to unsandboxed
injection.

## Remaining work, in priority order

1. Validate the existing Bubblewrap implementation on a supported host with a
   disposable vault. Confirm that child processes cannot access vault files,
   inherited plaintext environment values, or unrestricted network; confirm
   constrained egress works and is audited.
2. Make sandboxed execution the default for agent-facing credential use. Keep a
   compatibility path only with an obvious unsafe warning and preferably an
   explicit operator acknowledgement.
3. Harden egress in `paladin/broker.py` against DNS rebinding, unsafe redirects,
   IP/private-network bypasses, and hostname-normalization edge cases.
4. Complete and isolate-test Bitwarden Secrets Manager integration. Do not use a
   real production vault first. Ensure references, grants, audit, failures, and
   revocation work without leaking values.
5. Extend `paladin guard --backups` so sealed backup audit trails can be
   authenticated and compared without exposing values.
6. Add an ANSI operator dashboard for Guard state, sandbox readiness, active
   grants/TTLs, backup freshness, audit verification, and unsafe-mode warnings.
7. Before release: full suite, clean install/build, disposable-vault integration
   tests, migration/backup-restore validation, independent threat-model review,
   version/changelog/release notes. Only then push/tag/publish with explicit
   authorization.

## Known limits and public positioning

Do not claim perfect security. Describe this as an early security-focused beta
with opt-in confinement and explicit compatibility limitations.

- Sandbox protection depends on Bubblewrap functioning on the host.
- Legacy unsandboxed injection is unsafe and still exists for compatibility.
- Egress needs DNS-rebinding and redirect hardening.
- `user:cli` is not human authentication without confinement.
- Provider integration needs isolated end-to-end validation.
- No independent external security audit or penetration test has occurred.

## Test history

Earlier full suite:

```
2864 passed, 1 skipped, 83 deselected in 159.49s
```

Recent focused suite:

```
53 passed in 8.38s
```

Do not say the full project has been revalidated after the latest commits until
the full suite is run again.

## Required operating procedure

Before consequential writes, tests, network actions, deployments, or credential
operations, read and follow:

```
/home/dev/.codex/plugins/cache/custodian-build-week/custodian-codex-guard/0.1.0/skills/govern-codex/SKILL.md
```

Call `mcp__custodian_codex_guard__guard_action` and proceed only with an
`autonomous` or explicit `approved` verdict. After substantial work, call
`mcp__custodian_codex_guard__verify_receipts`.

Use `apply_patch` for edits. Preserve any unrelated changes if they appear; do
not reset, checkout, or discard work.
