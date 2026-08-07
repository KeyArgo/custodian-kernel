"""Shim so ``python -m custodian.codex_guard.mcp_server`` keeps working.

Existing MCP configurations (e.g. ``~/.codex/config.toml`` pointing at
the pre-0.5.0 module path) launch the MCP server this way; the shim
re-exports the canonical implementation so those configs keep working
without an edit.
"""
from custodian.guards.codex.mcp_server import *  # noqa: F401,F403
from custodian.guards.codex.mcp_server import main

if __name__ == "__main__":
    raise SystemExit(main())
