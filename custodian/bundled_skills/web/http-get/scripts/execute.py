#!/usr/bin/env python3
import argparse, ipaddress, json, socket
import requests
from urllib.parse import urlsplit

# Declared L0 ("read-only, no real-world effects"), but an unrestricted
# caller-supplied --url is a real SSRF vector -- reading the cloud metadata
# endpoint or an internal-only admin API is a genuine, high-impact effect,
# not a harmless read. Block private/loopback/link-local/reserved ranges,
# and re-check on every redirect hop (a validated initial URL could
# otherwise 302 to a blocked destination).
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


def _validate_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"scheme not allowed: {parsed.scheme!r}")
    if not parsed.hostname or _is_blocked_destination(parsed.hostname):
        raise ValueError(f"destination not allowed: {parsed.hostname!r}")


def main():
    p = argparse.ArgumentParser(); p.add_argument("--url",required=True); p.add_argument("--timeout",type=int,default=10)
    a = p.parse_args()
    try:
        url = a.url
        _validate_url(url)
        # Follow redirects manually so each hop is re-validated -- requests'
        # built-in allow_redirects would happily follow a validated URL's
        # 302 straight to a blocked destination.
        for _ in range(5):
            r = requests.get(url, timeout=a.timeout, headers={"User-Agent":"custodian/1.0"}, allow_redirects=False)
            if r.is_redirect and r.headers.get("Location"):
                url = requests.compat.urljoin(url, r.headers["Location"])
                _validate_url(url)
                continue
            break
        print(json.dumps({"ok":r.ok,"tool":"http-get","status":r.status_code,"body":r.text[:3000]}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"http-get","error":str(e)}))
if __name__=="__main__": main()
