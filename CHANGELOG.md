# Changelog

All notable changes to custodian-kernel are recorded here. Dates are UTC.

## [0.4.1] — 2026-07-17

Correctness and security hardening. Every fix below ships with a regression
test verified to fail against the pre-fix code. Full suite: 1827 passed,
3 skipped (the 3 are POSIX-only file-permission assertions that Windows cannot
express; see below).

### Money path

- **Concurrent spends no longer lose money or blow the session cap.** The spend
  path did read-modify-write on `spent_this_session` across the Stripe call, so
  two concurrent spends both read the stale total and the second write clobbered
  the first's increment — money moved could exceed money recorded, and the
  session cap was breachable. Spends now reserve budget under an OS advisory
  lock (fcntl / msvcrt) *before* charging; a failed charge releases the
  reservation. Verified: 8 concurrent \$250 spends against a \$1000 cap → exactly
  4 charged, recorded equals charged, cap never exceeded.
- **`daily_envelope` is now enforced on the pack/triage path.** `enforcer.decide`
  never forwarded a ledger, so the envelope gate silently never ran there
  (\$145 through a \$100 envelope). It also refuses to delegate to a remote Spark
  node whenever the policy configures a gate the node cannot see
  (`daily_envelope`, `margins`, `no_self_dealing`) — those always enforce
  locally, fail-safe.
- **Refunds can no longer exceed the original charge in aggregate.** The check
  compared each refund to the original amount only, so three \$100 refunds
  against a \$100 charge each passed. Cumulative prior refunds are now summed at
  the point money moves; over-refunding is refused.
- **Money gates fail closed.** `daily_envelope`, `margins` and `no_self_dealing`
  previously swallowed any internal error and continued, silently removing the
  gate. They now escalate to a human when a check cannot be evaluated.

### Security

- **Auto-downgrade can no longer escalate authority.** A downgrade recorded from
  a high-band task could raise a later request that had routed to a *lower* band
  (an L1 action running under L3's cap). Autorank now only ever lowers authority.
- **Enforcement-routing flags moved out of world-writable `/tmp`.** The Spark
  disable flag and enforcement-mode flag lived in `/tmp` (mode 1777), so any
  local user could flip enforcement routing. They now default under the state
  dir (guarded by `kernel-self-protection`), overridable via
  `CUSTODIAN_STATE_DIR`; the legacy `/tmp` path is still read for backward
  compatibility.

### Credential import

- **Quoted `.env` values containing `#` are no longer truncated.** Inline
  comments were stripped before quotes, so `PASS="Str0ng #Pass!"` imported as
  `Str0ng`. Quoted values are now treated as literal; only unquoted trailing
  comments are removed.

### Notes

- The 3 skipped tests assert `0600`/`0700` POSIX file modes, which `os.chmod`
  cannot express on Windows (it toggles only the read-only bit). On Windows the
  vault's at-rest protection is AES-256-GCM encryption plus NTFS ACLs, not POSIX
  modes; these tests run and pass on POSIX CI.

## [0.4.0] — 2026-07-16

- Security hardening, first-class backup/restore, Windows support, PII purge.
- Bulk credential onboarding: `.env`, Bitwarden, 1Password, and discovery.
- Rename of the credential broker package to `paladin`, with a read-only
  compatibility surface for pre-rename vaults, refs, env vars, and audit chains.
