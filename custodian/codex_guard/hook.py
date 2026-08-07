"""Shim so ``python -m custodian.codex_guard.hook`` keeps working."""
from custodian.guards.codex.hook import *  # noqa: F401,F403
from custodian.guards.codex.hook import main

if __name__ == "__main__":
    raise SystemExit(main())
