# Paladin handoff — 2026-08-03

Repository: `/mnt/homes/Development/custodian-dev`  
Branch: `feat/confined-bubblewrap-beta`

Do not handle or request raw credentials. Use only `paladin://…` references.

## Current state

Develop Paladin only in this monorepo. The live installed `paladin` command is
still older than this branch: do not install over, repair, or test against the
live vault until an isolated copy has passed testing.

The BWS broker-only provider work is committed as `69587d0`; do not discard or
overwrite it. It accepts only preconfigured UUID mappings, never exposes a
general BWS CLI runner or inventory, and keeps the BWS token and plaintext
value out of agent environments. External references are egress-only and
require explicit allowed hosts.

## Completed work

Recent relevant commits, newest first:

- `69587d0` feat(paladin): add broker-only BWS provider
- `0bed854` Seal Paladin backup metadata
- `265e917` Fail closed when Paladin audit cannot be read
- `c2a8b20` feat(sandbox): harden confined profile readiness
- `dac26da` Make Paladin entry edits atomic
- `c9358fa` Report Paladin Guard forensic audit status
- `c9d3515` Add Paladin audit integrity guard
- `26138c9` Link Custodian menu to Paladin credential console
- `d124b7f` Support atomic Paladin entry rename and full metadata editing
- `cfb694e` feat(sandbox): add opt-in confined execution core

### Entry editing

`paladin edit` supports rename, rotation, kind, profile, environment-variable,
note, and repeatable `--allowed-host` updates. `Vault.edit()` validates and
saves the complete change atomically; a rejected field cannot leave an entry
or exact-name grant partly migrated. Wildcard grants intentionally do not
migrate on rename.

Relevant files: `paladin/vault.py`, `paladin/cli.py`, and
`tests/test_paladin.py`.

### Audit integrity and recovery

`PaladinGuard` verifies the HMAC audit chain before a non-owner requester can
resolve a credential. Invalid or unreadable audit data fails closed for agents;
`user:cli` retains an operator recovery path. This label is not proof of a
human: an agent with arbitrary commands under the same OS identity can
impersonate it. Custodian/Bubblewrap confinement is needed to make that
distinction meaningful.

Commands:

```text
paladin guard
paladin guard --backups ~/paladin-backups
paladin audit verify
```

`paladin guard --backups` compares value-free audit hashes from legacy readable
backup ZIPs. Sealed backups need a future authenticated, key-aware comparison
path.

### Backup privacy

New `paladin-backup/2` files encrypt the entire internal archive, including the
encrypted vault, audit, and manifest, using a purpose-bound derived key. New
default filenames end in `.paladin-backup`; restore remains compatible with
legacy ZIP backups and bare vault files. Existing legacy backups remain legacy:
after the upgraded runtime is validated, create and store a fresh sealed backup
off-device.

Relevant files: `paladin/backup.py`, `paladin/cli.py`, and
`tests/test_paladin_backup.py`.

### Bubblewrap boundary

Do not independently rewrite the Bubblewrap implementation without coordinating
with its owner. Intended sandbox behavior:

```text
paladin exec --sandbox --with <paladin-ref> -- <command>
```

The child must not receive plaintext credentials or general network access.
Credential-bearing HTTP calls must use the constrained egress gateway, which
enforces grants, allowed hosts, HTTP method/path scope, TTL, and auditing.
Sandbox mode must fail closed if Bubblewrap is unavailable. A prior local probe
found `bwrap` present but unable to create a NETLINK_ROUTE socket; treat this as
host/container policy and never silently fall back to unsandboxed injection.

## Remaining work

1. Review and finish the Bubblewrap changes.
2. Route all agent-facing credential execution through `--sandbox`; mark legacy
   environment injection as unsafe.
3. Add an explicit operator-only migration/deprecation acknowledgement for
   unsandboxed execution.
4. Make `paladin guard --backups` compare sealed audit trails after authenticated
   decryption without exposing values.
5. Add an ANSI operator dashboard for Guard state, sandbox readiness, active
   grants/TTLs, backup freshness, audit verification, and unsafe-mode warnings.
6. Add operator configuration and service wiring for the committed BWS provider;
   preserve its broker-only, fixed-reference model.
7. Test in a disposable copy of the real Paladin home before installing the new
   runtime. Only then create a new sealed backup and copy it off-device.

## Tests and live-vault safety

Previously passed: `pytest -q tests/test_paladin.py` and
`pytest -q tests/test_paladin_backup.py`. The BWS provider's focused tests pass
four of four. They cover fixed BWS retrieval, minimal environment, safe error
handling, grant/host denial before provider access, egress-only use, and
response redaction.

The live Paladin audit previously failed at record 20; the same sequence was in
an older backup, so it predates this work. Preserve it: do not repair or
overwrite it. The live installation does not contain these commits. Custodian
receipt verification was last confirmed valid.
