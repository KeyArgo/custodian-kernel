#!/usr/bin/env python3
import argparse, ipaddress, json, socket
import requests
from urllib.parse import urlsplit

# Declared L1 ("trivial autonomous spend or free side-effect"), but an
# unrestricted caller-supplied --url + arbitrary --payload lets any caller
# issue a real mutating POST to any internal admin API, webhook, or cloud
# metadata write endpoint with zero human approval. Block private/loopback/
# link-local/reserved ranges before dispatch.
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
    p = argparse.ArgumentParser(); p.add_argument("--url",required=True); p.add_argument("--payload",default="{}"); p.add_argument("--timeout",type=int,default=10)
    a = p.parse_args()
    try:
        parsed = urlsplit(a.url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"scheme not allowed: {parsed.scheme!r}")
        if not parsed.hostname or _is_blocked_destination(parsed.hostname):
            raise ValueError(f"destination not allowed: {parsed.hostname!r}")
        payload = json.loads(a.payload)
        # Don't follow redirects -- a validated initial URL could otherwise
        # redirect to a blocked destination after the check above already ran.
        r = requests.post(a.url, json=payload, timeout=a.timeout, allow_redirects=False)
        print(json.dumps({"ok":r.ok,"tool":"http-post","status":r.status_code,"body":r.text[:3000]}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"http-post","error":str(e)}))
if __name__=="__main__": main()
