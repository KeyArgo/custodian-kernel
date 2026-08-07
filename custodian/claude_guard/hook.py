"""Shim so ``python -m custodian.claude_guard.hook`` keeps working."""
from custodian.guards.claude.hook import *  # noqa: F401,F403
from custodian.guards.claude.hook import main

if __name__ == "__main__":
    raise SystemExit(main())
