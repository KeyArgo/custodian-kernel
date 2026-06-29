#!/usr/bin/env python3
"""Status/log inspection for the stripe-spend skill. See SKILL.md for usage."""
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = SKILL_DIR / "state" / "authority.json"
LOG_FILE = SKILL_DIR / "state" / "audit_log.jsonl"

DEFAULT_STATE = {
    "band": "L2",
    "per_action_cap": 250.00,
    "session_cap": 1000.00,
    "spent_this_session": 0.0,
}


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return dict(DEFAULT_STATE)


def cmd_status():
    s = load_state()
    remaining = s["session_cap"] - s["spent_this_session"]
    print(f"Band: {s['band']} (auto-approve up to ${s['per_action_cap']:.2f}/action, "
          f"${s['session_cap']:.2f}/session)")
    print(f"Spent this session: ${s['spent_this_session']:.2f}")
    print(f"Remaining: ${remaining:.2f}")


def cmd_log():
    if not LOG_FILE.exists():
        print("No audit log entries yet.")
        return
    for line in LOG_FILE.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        print(f"{rec.get('iso', '?')}  {rec.get('event', '?'):<20}  "
              f"${rec.get('amount', 0):.2f}  {rec.get('description', '')}")


def cmd_reset():
    s = load_state()
    s["spent_this_session"] = 0.0
    STATE_FILE.write_text(json.dumps(s, indent=2))
    print("Session spend reset to $0.00. Audit log preserved.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("status", "log", "reset"):
        print("Usage: authority.py [status|log|reset]")
        sys.exit(1)
    {"status": cmd_status, "log": cmd_log, "reset": cmd_reset}[sys.argv[1]]()
