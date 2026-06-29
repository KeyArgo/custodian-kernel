#!/usr/bin/env python3
import argparse, json, os, socket
p = argparse.ArgumentParser()
p.add_argument("--key", required=True)
a = p.parse_args()
url = os.environ.get("REDIS_URL", "")
if not url:
    print(json.dumps({"ok": False, "stub": True, "tool": "redis-get", "message": "Set REDIS_URL to enable"})); exit(0)
try:
    import urllib.parse
    u = urllib.parse.urlparse(url)
    host, port = u.hostname or "localhost", u.port or 6379
    s = socket.socket(); s.settimeout(5); s.connect((host, port))
    if u.password:
        s.sendall(f"AUTH {u.password}\r\n".encode()); s.recv(1024)
    s.sendall(f"GET {a.key}\r\n".encode())
    resp = s.recv(4096).decode(); s.close()
    val = resp.split("\r\n")[1] if "$" in resp and "-1" not in resp.split("\r\n")[0] else None
    print(json.dumps({"ok": True, "tool": "redis-get", "key": a.key, "value": val, "found": val is not None}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "redis-get", "error": str(e)}))
