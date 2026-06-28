#!/usr/bin/env python3
"""Stub execute script for kv-delete.

Replace this with a real implementation.
OpenCode prompt: custodian/opencode-prompts/memory-tools.md
"""
import argparse, json, os, sys

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args, rest = p.parse_known_args()

    configured = bool(os.environ.get("KV_DELETE_CONFIGURED"))
    if not configured:
        print(json.dumps({
            "ok": False,
            "stub": True,
            "tool": "kv-delete",
            "message": "Set KV_DELETE_CONFIGURED=1 (and required credentials) to enable.",
        }))
        sys.exit(0)

    # TODO: real implementation
    print(json.dumps({"ok": True, "tool": "kv-delete", "result": "stub"}))

if __name__ == "__main__":
    main()
