#!/usr/bin/env python3
import argparse, json, os, socket
p = argparse.ArgumentParser()
p.add_argument("--key", required=True)
p.add_argument("--value", required=True)
p.add_argument("--ttl", type=int, default=0)
a = p.parse_args()
url = os.environ.get("REDIS_URL", "")
if not url:
    print(json.dumps({"ok": False, "stub": True, "tool": "redis-set", "message": "Set REDIS_URL to enable"})); exit(0)
try:
    import urllib.parse
    u = urllib.parse.urlparse(url)
    host, port = u.hostname or "localhost", u.port or 6379
    s = socket.socket(); s.settimeout(5); s.connect((host, port))
    if u.password:
        s.sendall(f"AUTH {u.password}\r\n".encode()); s.recv(1024)
    cmd = f"SET {a.key} {a.value}" + (f" EX {a.ttl}" if a.ttl else "") + "\r\n"
    s.sendall(cmd.encode())
    resp = s.recv(1024).decode(); s.close()
    print(json.dumps({"ok": "+OK" in resp, "tool": "redis-set", "key": a.key}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "redis-set", "error": str(e)}))
