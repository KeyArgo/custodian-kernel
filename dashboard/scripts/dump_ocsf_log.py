#!/usr/bin/env python3
"""Narrowly-scoped OCSF log dumper.

This is the ONLY process in this whole deployment that needs Docker socket
access -- and it does exactly one thing: find the sandbox container, pull
its OCSF kernel policy log lines, write them to a plain text file.

The public-facing dashboard (gunicorn/Flask) reads that file and never
touches the Docker socket itself. That matters: argobox-lite is a shared
production host running many other real services. A public-facing process
with Docker socket access can, in principle, enumerate and interact with
every container on the host, not just this sandbox -- a much bigger blast
radius than a demo dashboard should ever carry. Splitting "has Docker
access" from "is reachable from the internet" into two separate processes
is the actual fix; this script is the only one of the two with broad access,
and it's not reachable from outside the host at all.

Run on a timer (cron, systemd timer, or a simple sleep loop) -- not as part
of request handling.
"""
from __future__ import annotations

import sys
from pathlib import Path

OUTPUT_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/hermes-state-snapshot/ocsf_log.txt")
TAIL_LINES = 300


def main() -> int:
    try:
        import docker
    except ImportError:
        print("error: docker package not installed", file=sys.stderr)
        return 1

    try:
        client = docker.from_env()
        sandbox = next(
            (c for c in client.containers.list()
             if c.name.startswith("openshell-hermes-hackathon")),
            None,
        )
        if sandbox is None:
            print("warning: sandbox container not found", file=sys.stderr)
            OUTPUT_PATH.write_text("")
            return 0

        raw = sandbox.logs(tail=TAIL_LINES).decode("utf-8", errors="replace")
        ocsf_lines = [line for line in raw.splitlines() if "OCSF" in line]
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text("\n".join(ocsf_lines) + "\n" if ocsf_lines else "")
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
