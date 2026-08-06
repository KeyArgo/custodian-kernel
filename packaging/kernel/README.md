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

Optional integrations such as Custodian Codex Guard and Talaria are separate
packages. Removing `custodian-kernel` does not remove `~/.custodian`,
`~/.paladin`, or other user data.

Custodian is alpha software. It is defense in depth, not an operating-system
sandbox. Review the threat-model boundaries in
[SECURITY.md](SECURITY.md) before relying on it for consequential actions.

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

- Documentation: https://getcustodian.xyz/docs
- Source: https://github.com/KeyArgo/custodian-kernel
- Package: https://pypi.org/project/custodian-kernel/
- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md)
