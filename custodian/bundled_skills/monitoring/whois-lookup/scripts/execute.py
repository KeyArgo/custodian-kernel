#!/usr/bin/env python3
import argparse, json, socket
p = argparse.ArgumentParser()
p.add_argument("--domain", required=True)
a = p.parse_args()
try:
    tld = a.domain.split(".")[-1]
    server = f"whois.iana.org"
    s = socket.socket()
    s.settimeout(10)
    s.connect((server, 43))
    s.send((a.domain + "\r\n").encode())
    resp = b""
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        resp += chunk
    s.close()
    text = resp.decode("utf-8", errors="replace")
    print(json.dumps({"ok": True, "tool": "whois-lookup", "domain": a.domain, "raw": text[:2000]}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "whois-lookup", "domain": a.domain, "error": str(e)}))
