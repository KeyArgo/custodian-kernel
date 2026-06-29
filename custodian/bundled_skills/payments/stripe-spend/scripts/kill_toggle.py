#!/usr/bin/env python3
"""Engage/release the kill switch. See SKILL.md for usage.

This is operator-only infrastructure -- spend.py and refund.py can only ever
CONSULT this table (_check_kill_switch), never write to it. This script is
the one and only writer, and it takes no input from the agent at all: it's
invoked directly by a human, not requested by spend.py/refund.py the way an
escalation is. Uses plain stdlib sqlite3, matching the rest of this skill's
dependency-free design -- there is no sqlite3 CLI in this sandbox.
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DB_PATH = SKILL_DIR / "state" / "custodian.db"


def _ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kill_switch (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            killed      INTEGER NOT NULL DEFAULT 0,
            reason      TEXT    NOT NULL DEFAULT '',
            by          TEXT    NOT NULL DEFAULT '',
            changed_at  REAL    NOT NULL
        )
    """)
    conn.execute(
        "INSERT OR IGNORE INTO kill_switch (id, killed, reason, by, changed_at) VALUES (1, 0, '', '', ?)",
        (time.time(),),
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["engage", "release", "status"])
    p.add_argument("--by", help="Operator name/ID (required for engage/release)")
    p.add_argument("--reason", default="", help="Why the kill switch is being engaged")
    args = p.parse_args()

    if args.action in ("engage", "release") and not args.by:
        print("error: --by is required for engage/release", file=sys.stderr)
        sys.exit(1)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    _ensure_table(conn)

    if args.action == "status":
        row = conn.execute("SELECT killed, reason, by, changed_at FROM kill_switch WHERE id = 1").fetchone()
        conn.close()
        killed, reason, by, changed_at = row
        if killed:
            print(f"[kill-switch] ENGAGED by {by}{f' ({reason})' if reason else ''}")
        else:
            print("[kill-switch] released -- spend/refund requests are evaluated normally")
        sys.exit(0)

    killed_value = 1 if args.action == "engage" else 0
    conn.execute(
        "UPDATE kill_switch SET killed = ?, reason = ?, by = ?, changed_at = ? WHERE id = 1",
        (killed_value, args.reason if args.action == "engage" else "", args.by, time.time()),
    )
    conn.commit()
    conn.close()

    if args.action == "engage":
        print(f"[kill-switch] ENGAGED by {args.by}{f' -- {args.reason}' if args.reason else ''}")
        print("[kill-switch] Every spend/refund request is now denied, regardless of band or cap. "
              "Run `kill_toggle.py release --by <name>` to release it.")
    else:
        print(f"[kill-switch] released by {args.by} -- requests are evaluated normally again")


if __name__ == "__main__":
    main()
