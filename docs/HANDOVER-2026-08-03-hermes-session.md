# Hermes session handover — 2026-08-03 (Bubblewrap validation + guard protocol)

Repository: `/mnt/homes/Development/custodian-dev` (also reachable as `~/Development/custodian-dev`, symlink to `/mnt/homes/Development`)
Branch: `feat/confined-bubblewrap-beta`
HEAD at handover time: `1dc0ec6` (967879d from the prior handover is an ancestor)

Author: Hermes agent session (dev profile). This doc records what that session verified, what it left
unresolved, and the process constraints a next session must respect. Read `docs/PALADIN-HANDOFF-2026-08-03.md`
first — it is the source handover this session worked from (still untracked in the repo; preserve it).

## 1. Working conventions and standing restrictions (must persist)

- Work only inside this repository. Never under `~/` (except ~/Development which resolves here).
- Use only existing repos; do not create new repos/project dirs unless explicitly asked.
- Never push, tag, publish, install over the live Paladin vault, or touch real credentials without
  explicit user authorization. Never request/print/handle raw credentials — use `paladin://…` refs.
- Preserve unrelated dirty files: never `git reset`, `checkout`, or discard others' work.
- Standing restrictions: never share files from this PC with the 192.168.50.0/24 network; Area51
  (100.101.237.69) must remain restricted from this PC and /mnt/AllShare/.
- IMPORTANT: Hermes memory was DISABLED in the source session (both `memory` targets rejected with
  "Memory is not available"). If memory works after /reset, save the conventions above immediately —
  the source session could not.

## 2. Verified environment facts (all checked this session, real execution)

- bwrap 0.11.2 at /usr/bin/bwrap; unprivileged user namespaces WORK on this host:
  `unshare --user --map-root-user true` → exit 0.
- The exact probe `sandbox_available()` uses — `bwrap --unshare-all --ro-bind / / --dev /dev
  --die-with-parent true` — exits 0. The prior handover's "sandbox availability: no /
  NETLINK_ROUTE Operation not permitted" condition is STALE on this host. `paladin doctor` now
  reports "sandbox available: yes".
- System python3 (3.13.13) resolves the repo's `paladin` package directly (needed because sandbox
  children run under system python3). `.venv-dev/bin/python` also resolves the repo (editable install).
- Local Custodian guard engine is healthy: state dir /home/dev/.custodian, receipt chain VALID
  (8025 receipts at session start, verified via `python -m custodian.codex_guard.cli status`).

## 3. What this session did (all results real)

1. Reviewed the Bubblewrap implementation as-is (`paladin/sandbox.py`, `custodian/sandbox.py`,
   `paladin/egress.py`, `paladin/egress_client.py`, `paladin/broker.py`) — did NOT rewrite it.
2. Ran the existing sandbox red-team corpus on this host where it previously skipped:
   `pytest tests/test_sandbox.py tests/test_confined_sandbox.py tests/test_paladin_sandbox.py
   tests/test_paladin_egress.py -q`
   → **37 passed in ~19s, 0 skipped** (ran twice; still 37 passed after the concurrent commits).
   Coverage: secret + PALADIN_PASSPHRASE absent from child env and /proc/self/environ; vault and
   ~/.ssh masked to empty; no direct network (loopback blocked); PID namespace isolation; read-only
   FS outside declared rw dirs; confined profile (only workspace writable, no network, no
   unsandboxed fallback); gateway egress with host-side credential injection (upstream saw the
   Bearer value the child never held); ungranted ref denied AND audited; concurrent egress keeps
   the audit hash chain intact (verify() >= 60); fail-closed SandboxUnavailableError paths.
   => Handover task #1 (validate Bubblewrap) is effectively DONE at the library level on this host.
3. Exercised the local guard protocol (see §6) — this is the workable replacement for the MCP
   `guard_action`/`verify_receipts` tools, which do NOT exist in Hermes sessions.

## 4. OPEN BUG — Paladin CLI vault create→open roundtrip failure (unresolved)

Reproduction (disposable vault under the repo, fake passphrase/secret only):
`export PALADIN_HOME=$TMP/home; export PALADIN_PASSPHRASE="e2e-local-passphrase-only";
paladin init` → rc 0, creates vault.paladin (157 bytes, valid header:
`PALADIN1 {"kdf":"scrypt","n":131072,"p":1,"r":8,"salt":"438413e5fa517b22587b1f6ddb1c72e6"}`).
Then `paladin add api/e2e --stdin` FAILS, and `paladin list` fails with:
`paladin: vault failed to unlock: wrong passphrase/keyfile, or the file was tampered with`.

Why this is suspicious: `init` derives the key from the SAME env passphrase via
`Vault.create(passphrase=env_pp)`; `open_from_env` reads the same env var and derives from the
SAME params persisted in the header (`crypto.KdfParams.from_header`). Static reading of
`paladin/vault.py` (create/open/_load_key_material/save) and `paladin/crypto.py` (KdfParams,
derive_key) shows no asymmetry — yet create→open fails. The library tests never catch it because
they use the in-memory Vault object and never re-open via a fresh process + env.

Hypotheses NOT yet ruled out: env-var timing/name subtlety in the CLI subprocess; some interaction
with the vault `.lock` (0-byte file present); passphrase content edge case (ASCII, no newline).
The root cause is UNCONFIRMED.

NEXT STEP (needs explicit user approval — see §5): one stderr-visible repro, e.g. run `paladin add`
(and `paladin list`) against the leftover vault with `PALADIN_PASSPHRASE` set, without suppressing
stderr, OR run the in-process decrypt test:
`python - <<'PY'` trying `crypto.derive_key("e2e-local-passphrase-only", params)` +
`crypto.decrypt_blob` on the leftover vault file to distinguish passphrase mismatch from corruption.

## 5. Leftover artifacts (cleanup NOT done — requires user approval)

- `.tmp-e2e-rVRUdN/` (12K) — empty encrypted vault + 0-byte vault.lock from the failed e2e; the
  vault does NOT unlock with the init passphrase (see §4). Contains no real credentials.
- `.tmp-e2e-run.sh` — the e2e harness script (bash -n syntax OK; NOT execution-verified because
  executing it is the §4 repro flow).
- `/tmp/paladin_e2e_validate.sh`, `/tmp/guard-proposal-{1..4}.json` — earlier harness/proposals;
  /tmp copies are harmless but can be deleted.
Proposed cleanup (only with user approval): `rm -rf .tmp-e2e-rVRUdN .tmp-e2e-run.sh` in the repo
root, plus the /tmp files. Do NOT delete anything else.

## 6. Guard protocol actually used in this session (read carefully)

The MCP tools `mcp__custodian_codex_guard__guard_action`, `verify_receipts`, `wait_for_approval`
are NOT available in Hermes sessions. The local equivalent works:

- Read `/home/dev/.codex/plugins/cache/custodian-build-week/custodian-codex-guard/0.1.0/skills/govern-codex/SKILL.md`.
- Evaluate a proposal:
  `echo '<json>' | .venv-dev/bin/python -m custodian.hermes_guard.cli evaluate`
  JSON: `{"tool": "terminal", "arguments": {"command": "<exact cmd>"}, "workspace":
  "/mnt/homes/Development/custodian-dev", "requester": "hermes:custodian-handover-2026-08-03",
  "session_id": "...", "intent": "..."}`
  Tool names follow `custodian/hermes_guard/contract.py` (terminal/process/execute_code → test;
  write_file/patch → write; unknown tools → governance = escalation).
- Verdicts: autonomous → proceed with the EXACT command; escalation_required → NOT permission,
  operator must run `custodian-codex approve <id> --digest <digest>`; denied → do not execute.
- Path fence: reads/writes are confined to the workspace root — /tmp proposals get DENIED. Keep
  disposable artifacts inside the repo (hidden `.tmp-*`) and clean them up.
- Receipts: every evaluate appends a value-free HMAC receipt. Verify via
  `.venv-dev/bin/python -m custodian.codex_guard.cli status` (prints "receipts: valid (N)").
- The command-string inspector promotes risky commands (network, destructive, credentials, etc.)
  out of the autonomous band, so propose honestly.

Session guard results: pytest corpus → autonomous (ran). e2e script run → autonomous (ran, failed at
`add`). /tmp-path script → denied (outside workspace). A paladin init/add debug command and an
in-process decrypt attempt were DENIED BY THE USER — see §7.

## 7. Explicit user denials — do NOT retry, rephrase, or route around

The user denied, mid-session: (a) a debug reproduction of `paladin init` + `paladin add` with
errors visible, and (b) an in-process decrypt attempt against the leftover vault. The denial message
said: do not retry, do not rephrase, do not attempt the same outcome via a different command. The
next session must obtain fresh explicit user approval before ANY re-run of the §4 repro flow or
before deleting the §5 artifacts. Also note: an earlier `clarify` timed out with no user response —
the user is available but not always responsive; do not stall indefinitely, but do not push past a
denial.

## 8. Concurrent workstream (committed during this session — preserve, do not touch)

While this session ran, another workstream committed three commits (branch moved 967879d → 1dc0ec6):
- `494aa1c` feat(hermes-guard): define public hook contract and runtime adapter
- `a72f7b2` feat(hermes-guard): package repository-owned Hermes plugin
- `1dc0ec6` fix(test): neutralize HERMES_HOME in setup detection tests
This landed the previously-untracked `custodian/hermes_guard/` package, added the `custodian-hermes`
console script + plugin package-data in pyproject.toml, and fenced `~/.hermes` in
`custodian/codex_guard/mcp_server.py` inherited_deny. Sandbox tests still pass on top of these.
`docs/PALADIN-HANDOFF-2026-08-03.md` remains untracked (the source handover) — leave it.

## 9. Verification evidence (from this session)

- `pytest tests/test_sandbox.py tests/test_confined_sandbox.py tests/test_paladin_sandbox.py tests/test_paladin_egress.py -q` → 37 passed (19.79s, then 19.10s on rerun).
- `python -m custodian.codex_guard.cli status` → receipts: valid (8025).
- `bwrap --unshare-all --ro-bind / / --dev /dev --die-with-parent true` → exit 0.
- `custodian-hermes doctor` (via `python -m custodian.hermes_guard.cli doctor`) → OK, contract v1.0.
- `bash -n` on both harness scripts → syntax OK.

## 10. Remaining work (from the source handover, ordered by value)

1. [DONE at library level, §3] Bubblewrap validation. Remaining: CLI-level `paladin exec --sandbox`
   e2e is blocked on the §4 bug; a real operator-facing demo still needs that fixed first.
2. Deprecate unsafe (unsandboxed) execution: prominent warning, explicit operator acknowledgement
   for `--allow-unsandboxed` / legacy injection; migration path, no abrupt removal.
3. Harden constrained egress (paladin/broker.py): DNS rebinding, redirects to unapproved
   destinations, IP-literal/private-network bypasses, hostname normalization.
4. Bitwarden Secrets Manager: real operator config + isolated e2e on a disposable account/mock.
5. Sealed-backup audit comparison: `paladin guard --backups` needs authenticated decryption for
   sealed (paladin-backup/2) backups, without exposing secret values.
6. Operator dashboard (ANSI): guard state, sandbox readiness, grants+TTLs, backup freshness,
   audit verification, unsafe-mode warnings.
7. Release validation: full suite, clean build/install, disposable-copy vault test, migration +
   backup/restore, fresh sealed backup off-device, threat-model review, changelog, then push/tag
   only with explicit authorization.

Known framing that must be kept: "Early security-focused beta, with opt-in confinement and explicit
compatibility limitations." Never claim perfect security; bwrap dependence, legacy injection,
egress hardening gaps, user:cli identity limits, and no external audit all remain.

## 11. First actions for the next session

1. Save §1 conventions to memory if memory works (the source session could not).
2. `git status` + `git log --oneline -5` to re-anchor (tree moves under you here).
3. Ask the user for approval to: (a) clean §5 artifacts, (b) run the §4 stderr-visible repro to
   confirm the init→open roundtrip bug, then fix it in-repo with a regression test (a CLI-level
   init→add→list roundtrip test is missing from the suite and should be added).
4. Then proceed to §10 task #2 (unsafe-mode deprecation).
