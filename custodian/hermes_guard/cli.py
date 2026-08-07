"""Shim so ``python -m custodian.hermes_guard.cli`` keeps working."""
from custodian.guards.hermes.cli import *  # noqa: F401,F403
from custodian.guards.hermes.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
