#!/usr/bin/env python3
import argparse, ipaddress, json, socket
import requests
from urllib.parse import urlsplit

# This tool is declared L1 (autonomous, no human approval) and its whole
# purpose is posting to a caller-supplied URL -- unlike a fixed-destination
# tool (e.g. stripe-spend), there's no single host to declare via SKILL.md's
# allowed_hosts mechanism (see custodian/egress_proxy.py). Left completely
# unrestricted, any caller could reach internal-only services or the cloud
# metadata endpoint (169.254.169.254) with zero human approval. Block the
# private/loopback/link-local/metadata ranges by default instead -- this
# still allows genuine external webhook destinations, which is the tool's
# actual purpose.
def _is_blocked_destination(hostname: str) -> bool:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return True  # can't resolve -- fail closed, not open
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
    return False


def main():
    p = argparse.ArgumentParser(); p.add_argument("--url",required=True); p.add_argument("--payload",default="{}"); p.add_argument("--headers",default="{}")
    a = p.parse_args()
    try:
        parsed = urlsplit(a.url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"scheme not allowed: {parsed.scheme!r}")
        if not parsed.hostname or _is_blocked_destination(parsed.hostname):
            raise ValueError(f"destination not allowed: {parsed.hostname!r}")
        payload = json.loads(a.payload); headers = json.loads(a.headers) or {"Content-Type":"application/json"}
        # Don't follow redirects -- a validated initial URL could otherwise
        # redirect to a blocked destination after the check above already ran.
        r = requests.post(a.url, json=payload, headers=headers, timeout=10, allow_redirects=False)
        print(json.dumps({"ok":r.ok,"tool":"webhook-post","status":r.status_code,"body":r.text[:500]}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"webhook-post","error":str(e)}))
if __name__=="__main__": main()
