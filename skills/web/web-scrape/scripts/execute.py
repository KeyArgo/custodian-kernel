#!/usr/bin/env python3
import argparse, json, requests
from html.parser import HTMLParser
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
        r = requests.get(a.url, timeout=12, headers={"User-Agent":"Mozilla/5.0"})
        ex = TextExtractor(); ex.feed(r.text)
        print(json.dumps({"ok":True,"tool":"web-scrape","url":a.url,"text":" ".join(ex.text)[:3000]}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"web-scrape","error":str(e)}))
if __name__=="__main__": main()
