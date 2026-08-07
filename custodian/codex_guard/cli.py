"""Shim so ``python -m custodian.codex_guard.cli`` keeps working."""
from custodian.guards.codex.cli import *  # noqa: F401,F403
from custodian.guards.codex.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
