# Developer Install / Update

_Last updated: 2026-07-21_

A single script — `scripts/dev-install.py` — handles every local install
workflow.  All modes are **idempotent**: running twice is safe.

## Quick start

```bash
python scripts/dev-install.py
```

This runs `pip install -e ".[dev]"` in editable mode so source changes are
picked up immediately.

## Modes

| Mode | Flag | pip equivalent | Use case |
|---|---|---|---|
| **editable** | `--mode editable` (default) | `pip install -e ".[dev]"` | Day-to-day development; source changes reload automatically |
| **fresh** | `--mode fresh` | Creates venv ↓ then editable-install | Clean isolated environment |
| **upgrade** | `--mode upgrade` | `pip install --upgrade -e ".[dev]"` | Pull in new dependency versions |
| **repair** | `--mode repair` | `pip install --force-reinstall --no-cache-dir -e ".[dev]"` | Fix a corrupted or stale install |

## Flags

| Flag | Effect |
|---|---|
| `--dry-run` | Print what would be done without executing anything |
| `--verbose` | Show pip output in real time |
| `--print-pip-cmd` | Print the equivalent pip command and exit |
| `--help` | Show usage and exit |

## Examples

```bash
# Show the command for a fresh venv install
python scripts/dev-install.py --mode fresh --print-pip-cmd

# Check what a repair would do (without touching the environment)
python scripts/dev-install.py --mode repair --dry-run

# After a git pull, upgrade dependencies
python scripts/dev-install.py --mode upgrade

# Fix a broken install
python scripts/dev-install.py --mode repair
```

## Windows

The script uses `sys.executable` and `subprocess` throughout — no shell
commands, no hard-coded `/` paths.  It works identically on Windows and
Linux.  The `fresh` mode creates a venv with `Scripts\python.exe` on
Windows and `bin/python` on Linux.

## CI / non-interactive use

```bash
python scripts/dev-install.py --mode upgrade --verbose
```

Because the script only depends on the Python standard library and pip, it
runs in any environment that has Python >=3.11.  No shell, git, network
tools, or credentials are required by the script itself (pip may fetch
packages over the network as usual).

## Idempotence

Each mode is designed to be safe to repeat:
- **editable** / **upgrade** / **repair** — pip handles up-to-date checks
  natively; repeated runs are no-ops.
- **fresh** — skips venv creation if the target venv directory already
  exists, then runs editable install on the existing venv.

## Diagnostics

On success the script prints a short summary from pip plus a confirmation
that the package is importable.  On failure it prints the pip error and
returns a non-zero exit code.  Use `--verbose` to see the full pip log.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `pip: command not found` | pip not installed | `python -m ensurepip --upgrade` or see [pip docs](https://pip.pypa.io/en/stable/installation/) |
| `error: can't find Rust compiler` | A dependency needs native compilation | `pip install --upgrade setuptools` or install a pre-built wheel via `pip install --only-binary :all: -e ".[dev]"` |
| Package imports fail after `editable` install | Build metadata changed | Run `repair` mode to force a fresh build |
| `Permission denied` on venv creation | Trying to create venv inside a protected directory | Run outside a system-owned path, or use a dedicated workspace |
