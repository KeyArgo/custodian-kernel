"""Fail-closed Claude Code integration for Custodian's shared control plane.

Unlike the Codex integration -- where the model must *choose* to call the
``guard_action`` MCP tool before acting -- this guard runs inside Claude Code's
``PreToolUse`` hook. The harness invokes it deterministically before every tool
call, so enforcement does not depend on model cooperation, a loaded skill, or a
prompt surviving injection. A denied decision blocks the tool even in
``bypassPermissions`` mode.
"""

from .bridge import classify_tool, evaluate_tool

__all__ = ["classify_tool", "evaluate_tool"]
