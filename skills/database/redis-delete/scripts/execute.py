#!/usr/bin/env python3
import argparse, json, os, socket
p = argparse.ArgumentParser()
p.add_argument("--key", required=True)
a = p.parse_args()
url = os.environ.get("REDIS_URL", "")
if not url:
    print(json.dumps({"ok": False, "stub": True, "tool": "redis-delete", "message": "Set REDIS_URL to enable"})); exit(0)


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
    s.sendall(_resp("DEL", a.key))
    resp = s.recv(1024).decode(); s.close()
    deleted = int(resp.strip().lstrip(":")) > 0 if resp.strip().startswith(":") else False
    print(json.dumps({"ok": True, "tool": "redis-delete", "key": a.key, "deleted": deleted}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "redis-delete", "error": str(e)}))
