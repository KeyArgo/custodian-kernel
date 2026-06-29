#!/usr/bin/env python3
"""Entry point for stripe-spend — delegates to spend_v2.py for the full earn→spend flow."""
import argparse, json, os, subprocess, sys
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--amount", type=float, required=True, help="Amount in USD")
p.add_argument("--description", default="agent spend")
p.add_argument("--customer-id", default=None)
a = p.parse_args()

key = os.environ.get("STRIPE_SECRET_KEY", "")
if not key:
    print(json.dumps({"ok": False, "stub": True, "tool": "stripe-spend",
        "message": "Set STRIPE_SECRET_KEY to enable"}))
    sys.exit(0)

here = Path(__file__).parent
spend_script = here / "spend_v2.py"
if not spend_script.exists():
    spend_script = here / "spend.py"

cmd = [sys.executable, str(spend_script), "--amount", str(a.amount), "--description", a.description]
if a.customer_id:
    cmd += ["--customer-id", a.customer_id]

try:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(here))
    try:
        print(r.stdout.strip())
    except Exception:
        print(json.dumps({"ok": r.returncode == 0, "tool": "stripe-spend", "output": r.stdout.strip()}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "stripe-spend", "error": str(e)}))
