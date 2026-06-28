#!/usr/bin/env python3
import argparse, json, requests
from html.parser import HTMLParser
class DDGParser(HTMLParser):
    def __init__(self): super().__init__(); self.results=[]; self._cur=None; self._in_title=False
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag=="a" and "result__a" in d.get("class",""):
            self._cur={"url":d.get("href",""),"title":"","snippet":""}; self._in_title=True
    def handle_endtag(self,tag):
        if self._in_title and tag=="a":
            self._in_title=False
            if self._cur and self._cur.get("title"): self.results.append(self._cur); self._cur=None
    def handle_data(self,data):
        if self._in_title and self._cur: self._cur["title"]+=data.strip()
def main():
    p = argparse.ArgumentParser(); p.add_argument("--query",required=True); p.add_argument("--limit",type=int,default=5)
    a = p.parse_args()
    try:
        r = requests.get("https://html.duckduckgo.com/html/", params={"q":a.query}, headers={"User-Agent":"Mozilla/5.0"}, timeout=12)
        parser = DDGParser(); parser.feed(r.text)
        results = parser.results[:a.limit]
        print(json.dumps({"ok":True,"tool":"web-search","query":a.query,"results":results,"count":len(results)}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"web-search","error":str(e)}))
if __name__=="__main__": main()
