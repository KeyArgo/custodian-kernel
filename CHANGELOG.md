# Changelog

All notable changes to custodian-kernel are recorded here. Dates are UTC.

## [0.4.0] — unreleased

First 0.4 release. Adds a first-class credential broker (`paladin`), Windows
support, backup/restore, and bulk credential onboarding — and carries a round
of money/security hardening with a regression test for every fix (each verified
to fail against the pre-fix code).

### Credential broker (`paladin`)

- Encrypted vault (AES-256-GCM, scrypt), deny-by-default grants, hash-chained
  audit, and egress-only secret injection — the agent holds a `paladin://` ref,
  never the value.
- **Backup / restore** to a single encrypted archive. Restore verifies the
  backup decrypts *before* touching the destination and saves any overwritten
  files to `*.pre-restore` first.
- **Bulk import** from many sources, all reporting names/kinds/counts only —
  never values:
  - `.env` files (single, or a whole tree),
  - **CSV** password-manager exports (Chrome, Firefox, Bitwarden, LastPass,
    1Password, KeePass) — offline, no CLI; the value/name columns are
    auto-detected from the header, and headerless `KEY,value` files work too,
  - **JSON** secrets dumps (flat `{"NAME": "value"}` or an array of
    `{name, value}`),
  - **Bitwarden** and **1Password** via their CLIs,
  - `discover` — report-only: shows where credentials live (`.env`, shell-rc
    exports, password-manager exports in Downloads/Desktop) and the exact
    command to import each.

### Money path

- **Concurrent spends no longer lose money or blow the session cap.** Spends
  reserve budget under an OS advisory lock *before* charging; a failed charge
  releases the reservation. Was: two concurrent spends could each read a stale
  total, both charge, and record only one — money moved exceeding money
  recorded, cap breachable. Verified: 8 concurrent \$250 spends against \$1000
  → exactly 4 charged, recorded equals charged.
- **`daily_envelope` is now enforced on the pack/triage path**, and the router
  refuses to delegate to a remote Spark node whenever a gate the node cannot
  see (`daily_envelope`, `margins`, `no_self_dealing`) is configured — those
  always enforce locally, fail-safe.
- **Refunds cannot exceed the original charge in aggregate** (prior refunds are
  summed at the point money moves).
- **Money gates fail closed:** `daily_envelope`, `margins` and `no_self_dealing`
  now escalate to a human if a check errors, instead of silently continuing.

### Security

- **Auto-downgrade can no longer escalate authority.** A downgrade recorded
  from a high-band task could raise a later request that had routed to a lower
  band; autorank now only ever lowers authority.
- **Enforcement-routing flags moved out of world-writable `/tmp`** to the state
  dir (guarded by `kernel-self-protection`); the legacy path is still read for
  backward compatibility.
- **`@govern` tamper snapshots moved out of `/tmp`** and keyed by qualified
  module + name; a tamper-drift denial is now audited instead of silent.
- Rename of the credential broker package to `paladin`, with a read-only
  compatibility surface for pre-rename vaults, refs, env vars, and audit chains
  (the on-disk format magic is honored, so existing vaults keep opening).

### Correctness / portability

- Governed tools now run under `sys.executable`, not a hardcoded `python3`
  (the tool registry was non-functional on Windows).
- `tzdata` is declared as a dependency (timezone tools failed on Windows and
  slim images).
- Quoted `.env` values containing `#` are no longer truncated
  (`PASS="Str0ng #Pass!"` was imported as `Str0ng`).
- `custodian init` now initializes authority state (it created an empty state
  dir before, so every following command warned "no authority state found").
- `SqliteStorage` load→modify→save no longer crashes on the band field.

### Notes

- On Windows there is no in-process sandbox (that comes from an external,
  Linux-only helper); the control plane, crypto, guards, and audit are
  identical on both platforms. File-mode assertions (`0600`/`0700`) are
  POSIX-only and skip on Windows, where NTFS ACLs and AES-256-GCM provide
  at-rest protection.
