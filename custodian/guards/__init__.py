"""Custodian harness guards, consolidated.

Each guard (claude, codex, hermes, opencode) lives in its own subpackage so
the whole adapter surface is in one place. The pre-0.5.0 module paths
(``custodian.claude_guard`` etc.) remain as aliasing shims — existing hook
wiring, imports, and console scripts keep working unchanged.
"""
