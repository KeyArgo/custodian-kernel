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


def _resp(*parts):
    out = f"*{len(parts)}\r\n".encode()
    for part in parts:
        raw = part if isinstance(part, bytes) else str(part).encode()
        out += f"${len(raw)}\r\n".encode() + raw + b"\r\n"
    return out


try:
    import urllib.parse
    u = urllib.parse.urlparse(url)
    host, port = u.hostname or "localhost", u.port or 6379
    s = socket.socket(); s.settimeout(5); s.connect((host, port))
    if u.password:
        s.sendall(_resp("AUTH", u.password)); s.recv(1024)
    if a.ttl:
        cmd = _resp("SET", a.key, a.value, "EX", a.ttl)
    else:
        cmd = _resp("SET", a.key, a.value)
    s.sendall(cmd)
    resp = s.recv(1024).decode(); s.close()
    print(json.dumps({"ok": "+OK" in resp, "tool": "redis-set", "key": a.key}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "redis-set", "error": str(e)}))
