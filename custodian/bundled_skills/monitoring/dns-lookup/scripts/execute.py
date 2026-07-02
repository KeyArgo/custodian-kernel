#!/usr/bin/env python3
import argparse, json, socket
p = argparse.ArgumentParser()
p.add_argument("--host", required=True)
p.add_argument("--record-type", default="A")
a = p.parse_args()
try:
    results = socket.getaddrinfo(a.host, None)
    addrs = list({r[4][0] for r in results})
    print(json.dumps({"ok": True, "tool": "dns-lookup", "host": a.host, "addresses": addrs}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "dns-lookup", "error": str(e)}))
