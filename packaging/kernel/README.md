# Custodian Kernel

Custodian is a provider-neutral authority kernel for AI agents. It evaluates
actions before execution, enforces approval and spend policy, records
tamper-evident evidence, and includes the Paladin encrypted credential broker.

## Install

Custodian Kernel 0.5.0 supports Linux and macOS with Python 3.11 through
3.13; Windows installs are supported through the managed installer below.

For Python environments that permit application installs:

```bash
python -m pip install custodian-kernel
custodian
```

Linux distributions that enforce PEP 668 reject even `pip install --user`.
Download `install-custodian.py` from the source repository or GitHub release
and run it. It owns the runtime so users never activate or maintain a
virtual environment — it creates a private two-slot managed runtime, installs
the package, and exposes `custodian` (and friends) in `~/.local/bin`:

```bash
python install-custodian.py            # or: ./install-custodian.py
custodian
```

Upgrades reuse the same installer (`python install-custodian.py` again swaps
to the second slot); uninstall preserves all user data:

```bash
python install-custodian.py --uninstall --dry-run
python install-custodian.py --uninstall
```

The installer refuses to touch directories it does not own (no
`active-slot` marker), never deletes user data, and requires Python 3.11+.

Running `custodian` opens the interactive menu. Useful checks:

```bash
custodian doctor
custodian health --format json
custodian console --once
custodian-verify
paladin --help
```

Optional integrations are included: the Claude, Codex, and Hermes harness
guards ship in the same wheel, so one install covers the kernel, Paladin, and
every harness guard. The CANONICAL Hermes path is the wheel's own entry point:
`pip install custodian-kernel` then `hermes plugins enable custodian-hermes-guard`.
The per-integration packages (custodian-codex-guard, custodian-claude-guard,
custodian-hermes-guard, custodian-stripe, talaria) remain available as
standalone legacy surfaces. Removing `custodian-kernel`
does not remove `~/.custodian`, `~/.paladin`, or other user data.

Custodian is pre-1.0 software. It is defense in depth, not an operating-system
sandbox. Review the threat-model boundaries in
[SECURITY.md](SECURITY.md) before relying on it for consequential actions.

Known limits (stated plainly):
- The Bubblewrap sandbox (`hermes-bwrap`) is OPT-IN and refuses to bind the
  filesystem root: `HERMES_AGENT_ROOT=/` (or an unresolvable agent root) aborts
  the launch instead of producing `--ro-bind / /`. It confines spawned tools;
  it is not a VM.
- `--allow-unsandboxed` bypasses the sandbox entirely and prints a loud
  deprecation warning. Do not use it for anything you care about; it will be
  removed in a future release.
- Audit and receipt evidence is stored locally on the governed machine. It is
  tamper-evident (HMAC-chained) but not cross-process serialized or anchored
  to an external store; a process with local root can erase its own trail.
- Application-governed enforcement covers actions routed through the guarded
  adapters. A process that never passes through an adapter is not governed;
  host-enforced and VM containment modes are on the roadmap.

Known gap: an OpenCode guard adapter exists internally but is not shipped in
this release — no public mirror, no `--with-opencode` installer flag, and no
`custodian guards enable opencode` target. It is tracked for a later release;
the three shipped guards (claude, codex, hermes) are at parity.

Test coverage note: 86 tests are marked `network` and deselected by default
(they require real network access); run `pytest -m network` to include them.

Residual risks (accepted for 0.5.0, tracked for hardening):
- The gate's symlink checks are path-based (check-then-use). A same-user
  attacker able to swap path components between the check and the read
  could race the check; the threat model assumes the state directory is
  user-owned and protected.
- Only the immediate state directory and state file are checked for
  symlinks; symlinked ancestor components of a custom nested
  `CUSTODIAN_STATE_DIR` are not detected.
- One cycle of production/telemetry watch on the gate fallback path
  (the dormant-fallback behavior on both read and write sides) is
  recommended before treating it as fully proven under real load.

Preview or perform a data-preserving package uninstall:

```bash
custodian uninstall --dry-run
custodian uninstall --yes
```

For an installation created by `install-custodian.py`, use the same downloaded
installer to remove its managed runtime and launchers while preserving data:

```bash
python install-custodian.py --uninstall --dry-run
python install-custodian.py --uninstall
```

## Test the install yourself

You can prove the full lifecycle in a scratch directory without touching your
system. This is exactly what the release CI runs on Linux, macOS, and Windows
for every release:

```bash
# 1. Scratch area, start clean
mkdir -p /tmp/custodian-e2e && cd /tmp/custodian-e2e

# 2. Point at a wheel (or the PyPI version: --package custodian-kernel==0.5.0)
WHEEL=/path/to/custodian_kernel-0.5.0-py3-none-any.whl

# 3. Fresh install into a throwaway runtime root
python install-custodian.py --package "$WHEEL" \
    --runtime-root "$PWD/runtime" --bin-dir "$PWD/bin"
cat runtime/active-slot          # expect: slot-b

# 4. The launcher works
./bin/custodian --version        # expect: custodian 0.5.0

# 5. Reinstall: exercises the two-slot swap
python install-custodian.py --package "$WHEEL" \
    --runtime-root "$PWD/runtime" --bin-dir "$PWD/bin"

# 6. Uninstall: removes launchers, preserves runtime data
python install-custodian.py --uninstall \
    --runtime-root "$PWD/runtime" --bin-dir "$PWD/bin"
```

Every step failing here is a bug worth reporting; the installer should never
touch anything outside the `runtime-root`/`bin-dir` you gave it.

- Documentation: https://getcustodian.xyz/docs
- Source: https://github.com/KeyArgo/custodian-kernel
- Package: https://pypi.org/project/custodian-kernel/
- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md)
