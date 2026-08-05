# Bubblewrap Containment Layer

Filesystem isolation for governed agent sessions. This is **not** a complete
security boundary: a same-user process outside the sandbox can interfere with
the bwrap process. The adversarial model requires a separate sidecar Custodian
service and VM-level isolation; the Bubblewrap layer provides the
filesystem-isolation enforcement boundary in front of that.

## Threat model

A confined agent must never see, even read-only:

- **Credential homes**: `~/.ssh`, `~/.aws`, `~/.gnupg`,
  `~/.config/gcloud`, `~/.kube`, `~/.docker`, `~/.paladin`, `~/.talaria`
- **Container runtime sockets**: `/var/run/docker.sock`,
  `/run/docker.sock`, `/run/podman/podman.sock` (a socket would let the
  agent drive the host container runtime)
- **Env-driven vault paths**: `PALADIN_VAULT_PATH`, `PALADIN_KEYFILE`
- **Custodian state dir non-policy content**: `codex-guard-receipts.jsonl`
  (evidence chain), `codex-approvals/`, `ledger.db`, `*.key` receipt/approval
  HMAC material (forge target), `tamper/`, and `kill_switch.json` — a
  sandboxed agent must not learn whether the kill switch is armed

Inside the state dir, only the four policy files are mounted, read-only:

- `approval-policy.json`
- `control-settings.json`
- `filesystem-policy.json`
- `gate-policy.json`

The agent cannot read the evidence chain or forge receipts. The sensitive-path
model that encodes all of this lives in **`custodian/containment_audit.py`**
(the `custodian/` package must not import `paladin/`, so the deny list is
maintained there, matching the Paladin sandbox's own mask list).

## Launching a governed session

`scripts/hermes-bwrap` builds the bwrap mount set and execs Hermes inside it:

```bash
hermes-bwrap --workspace /path/to/project --profile dev -- <hermes args...>
```

Mount layout:

- **Writable**: `<workspace>` (bound last so a workspace under `/tmp` is not
  shadowed by the scratch tmpfs), `/tmp`, `/dev/shm`, `~/.hermes/logs`,
  `~/.hermes/memories` — logs and memories are tmpfs, so each governed
  session starts clean (pre-existing `memory.json` is seeded in read-only)
- **Read-only**: `~/.hermes/config.yaml`, `profiles/`, `plugins/`,
  `skills/`, and the four Custodian policy JSONs (bound individually — the
  rest of the state dir is never mounted)
- **Excluded**: every credential path above. Paths that exist on the host
  are masked with an empty tmpfs bind so the agent cannot even list their
  contents; a model asking to `cat ~/.ssh/id_rsa` gets "No such file"
  regardless of tool choice

Hardening defaults:

- **Network denied by default** (`--unshare-net`). Opt in with
  `--allow-network`, which grants full host network access — use only with
  an independently controlled egress gateway
- **User namespace unshared** (`--unshare-user`), plus `--unshare-ipc`,
  `--unshare-pid`, `--unshare-uts`, `--unshare-cgroup`, `--die-with-parent`,
  `--new-session`
- **YOLO bypass flags rejected at the wrapper level**: `--yolo`, `-y`, `-z`,
  `--oneshot`, `--yes`, `--force` abort the launch (exit 2) before any
  sandbox is created — the model cannot talk its way around the gate

Environment: `HERMES_BWRAP_WORKSPACE` / `HERMES_BWRAP_PROFILE` set defaults;
`PALADIN_KEYFILE` and `PALADIN_PASSPHRASE` are stripped from the child
environment; `--policy-dir` defaults to `$CUSTODIAN_STATE_DIR` or
`~/.custodian`.

## Pre-flight leak gate

Before exec, `hermes-bwrap` audits its own mount argv with the same engine as
`sandbox-audit check` (`custodian.containment_audit.audit_mount_spec`). Any
**critical** or **high** finding refuses the launch:

```text
hermes-bwrap: REFUSING launch: containment audit found N leak(s):
  [high] /home/user/.custodian -> /home/user/.custodian (ro) exposes ...
Run `sandbox-audit check` for the full report.
```

Exit code **3** = launch refused by the containment gate. If the audit module
cannot be imported, the wrapper fails closed and refuses the launch rather
than proceeding un-audited.

## Sandbox-audit sidecar

`scripts/sandbox-audit` checks the same security property three independent
ways, so a leak (e.g. a whole-state-dir bind exposing the receipt chain and
HMAC keys) is caught at build time, at runtime, and empirically:

| Command | Kind | What it does |
|---|---|---|
| `sandbox-audit check` | static | Audits the mount specs the real launchers would build **now** (`hermes-bwrap` + the Paladin egress sandbox). No sandbox run. |
| `sandbox-audit live` | runtime | Parses `/proc/<pid>/mountinfo` of every live bwrap process on the host and flags binds whose source is a sensitive path — watches what is **actually** mounted, even for sandboxes built by other code |
| `sandbox-audit probe` | empirical | Plants fake secrets (`.ssh/id_rsa`, `.paladin/vault.key`, receipt + key markers) in a fake HOME, runs a real probe through `hermes-bwrap`, and verifies none are visible — any `LEAK:` line fails the probe |

Exit codes: **0** = clean, **1** = critical/high findings (or probe failure),
**2** = usage error. Running with no subcommand does static + live. Suitable
as a pre-flight gate or a cron watchdog.
