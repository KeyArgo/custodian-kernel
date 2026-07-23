#!/usr/bin/env python3
import argparse, json, socket
p = argparse.ArgumentParser()
p.add_argument("--host", required=True)
p.add_argument("--ports", default="80,443,22,21,25,3306,5432,6379")
a = p.parse_args()
ports = [int(x.strip()) for x in a.ports.split(",") if x.strip()]
results = {}
for port in ports:
    try:
        s = socket.socket()
        s.settimeout(1)
        r = s.connect_ex((a.host, port))
        results[port] = "open" if r == 0 else "closed"
        s.close()
    except Exception:
        results[port] = "error"
open_ports = [p for p,s in results.items() if s == "open"]
print(json.dumps({"ok": True, "tool": "port-scan", "host": a.host, "open": open_ports, "results": results}))
