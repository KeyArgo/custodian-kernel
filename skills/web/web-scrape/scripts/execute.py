#!/usr/bin/env python3
import argparse, ipaddress, json, socket
import requests
from html.parser import HTMLParser
from urllib.parse import urlsplit

# Declared L0 ("read-only, no real-world effects"), but an unrestricted
# caller-supplied --url is a real SSRF vector, same as http-get. Block
# private/loopback/link-local/reserved ranges, and re-check on every
# redirect hop.
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


class TextExtractor(HTMLParser):
    def __init__(self): super().__init__(); self.text=[]; self._skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","nav","footer","head"): self._skip+=1
    def handle_endtag(self,tag):
        if tag in ("script","style","nav","footer","head"): self._skip=max(0,self._skip-1)
    def handle_data(self,data):
        if not self._skip and data.strip(): self.text.append(data.strip())
def main():
    p = argparse.ArgumentParser(); p.add_argument("--url",required=True)
    a = p.parse_args()
    try:
        url = a.url
        _validate_url(url)
        for _ in range(5):
            r = requests.get(url, timeout=12, headers={"User-Agent":"Mozilla/5.0"}, allow_redirects=False)
            if r.is_redirect and r.headers.get("Location"):
                url = requests.compat.urljoin(url, r.headers["Location"])
                _validate_url(url)
                continue
            break
        ex = TextExtractor(); ex.feed(r.text)
        print(json.dumps({"ok":True,"tool":"web-scrape","url":a.url,"text":" ".join(ex.text)[:3000]}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"web-scrape","error":str(e)}))
if __name__=="__main__": main()
