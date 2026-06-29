#!/usr/bin/env python3
import argparse, json, os, urllib.request
p = argparse.ArgumentParser()
p.add_argument("--repo", required=True, help="owner/repo")
p.add_argument("--tag", required=True)
p.add_argument("--name", default=None)
p.add_argument("--body", default="")
p.add_argument("--draft", action="store_true")
a = p.parse_args()
token = os.environ.get("GITHUB_TOKEN", "")
if not token:
    print(json.dumps({"ok": False, "stub": True, "tool": "github-release-create", "message": "Set GITHUB_TOKEN to enable"})); exit(0)
try:
    payload = json.dumps({"tag_name": a.tag, "name": a.name or a.tag, "body": a.body, "draft": a.draft}).encode()
    req = urllib.request.Request(f"https://api.github.com/repos/{a.repo}/releases", data=payload,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
    print(json.dumps({"ok": True, "tool": "github-release-create", "id": d["id"], "url": d["html_url"], "tag": d["tag_name"]}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "github-release-create", "error": str(e)}))
