#!/usr/bin/env python3
import argparse, json, os, urllib.request
p = argparse.ArgumentParser()
p.add_argument("--text", required=True)
p.add_argument("--model", default="embed-english-v3.0")
a = p.parse_args()
key = os.environ.get("COHERE_API_KEY", "")
if not key:
    print(json.dumps({"ok": False, "stub": True, "tool": "cohere-embed", "message": "Set COHERE_API_KEY to enable"})); exit(0)
try:
    payload = json.dumps({"texts": [a.text], "model": a.model, "input_type": "search_query"}).encode()
    req = urllib.request.Request("https://api.cohere.ai/v1/embed", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read())
    emb = d["embeddings"][0]
    print(json.dumps({"ok": True, "tool": "cohere-embed", "model": a.model, "dimensions": len(emb), "embedding_preview": emb[:5]}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "cohere-embed", "error": str(e)}))
