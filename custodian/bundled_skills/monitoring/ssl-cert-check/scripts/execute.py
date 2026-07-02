#!/usr/bin/env python3
import argparse, json, ssl, socket
from datetime import datetime, timezone
p = argparse.ArgumentParser()
p.add_argument("--host", required=True)
p.add_argument("--port", type=int, default=443)
a = p.parse_args()
try:
    ctx = ssl.create_default_context()
    with ctx.wrap_socket(socket.socket(), server_hostname=a.host) as s:
        s.settimeout(10)
        s.connect((a.host, a.port))
        cert = s.getpeercert()
    exp = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    days = (exp - datetime.now(timezone.utc)).days
    print(json.dumps({"ok": True, "tool": "ssl-cert-check", "host": a.host,
        "expires": cert["notAfter"], "days_remaining": days, "valid": days > 0,
        "subject": dict(x[0] for x in cert["subject"])}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "ssl-cert-check", "host": a.host, "error": str(e)}))
