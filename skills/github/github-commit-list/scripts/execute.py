#!/usr/bin/env python3
import argparse, json, os, urllib.request
p = argparse.ArgumentParser()
p.add_argument("--repo", required=True, help="owner/repo")
p.add_argument("--branch", default="main")
p.add_argument("--limit", type=int, default=10)
a = p.parse_args()
token = os.environ.get("GITHUB_TOKEN", "")
if not token:
    print(json.dumps({"ok": False, "stub": True, "tool": "github-commit-list", "message": "Set GITHUB_TOKEN to enable"})); exit(0)
try:
    url = f"https://api.github.com/repos/{a.repo}/commits?sha={a.branch}&per_page={a.limit}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    commits = [{"sha": c["sha"][:7], "message": c["commit"]["message"].split("\n")[0], "author": c["commit"]["author"]["name"]} for c in data]
    print(json.dumps({"ok": True, "tool": "github-commit-list", "repo": a.repo, "commits": commits}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "github-commit-list", "error": str(e)}))
