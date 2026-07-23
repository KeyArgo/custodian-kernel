#!/usr/bin/env python3
import argparse, json, subprocess, re, sys
p = argparse.ArgumentParser()
p.add_argument("--host", required=True)
p.add_argument("--count", type=int, default=4)
a = p.parse_args()
try:
    r = subprocess.run(["ping", "-c", str(a.count), a.host], capture_output=True, text=True, timeout=15)
    loss = re.search(r"(\d+)% packet loss", r.stdout)
    rtt = re.search(r"rtt min/avg/max.*?= ([\d.]+)/([\d.]+)/([\d.]+)", r.stdout)
    print(json.dumps({"ok": r.returncode==0, "tool": "ping-host", "host": a.host,
        "packet_loss_pct": int(loss.group(1)) if loss else None,
        "rtt_avg_ms": float(rtt.group(2)) if rtt else None, "raw": r.stdout.strip()}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "ping-host", "error": str(e)}))
