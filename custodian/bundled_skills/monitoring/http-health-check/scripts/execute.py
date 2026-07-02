#!/usr/bin/env python3
import argparse, json, time, urllib.request, urllib.error
p = argparse.ArgumentParser()
p.add_argument("--url", required=True)
p.add_argument("--timeout", type=int, default=10)
a = p.parse_args()
try:
    t0 = time.monotonic()
    req = urllib.request.Request(a.url, headers={"User-Agent": "custodian-health-check/1.0"})
    with urllib.request.urlopen(req, timeout=a.timeout) as resp:
        ms = round((time.monotonic() - t0) * 1000, 1)
        print(json.dumps({"ok": True, "tool": "http-health-check", "url": a.url,
            "status": resp.status, "latency_ms": ms}))
except urllib.error.HTTPError as e:
    print(json.dumps({"ok": False, "tool": "http-health-check", "url": a.url, "status": e.code, "error": str(e)}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "http-health-check", "url": a.url, "error": str(e)}))
