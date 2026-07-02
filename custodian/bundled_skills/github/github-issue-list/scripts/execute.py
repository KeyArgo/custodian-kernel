#!/usr/bin/env python3
"""Execute script for github-issue-list.

Lists issues for a GitHub repository. Pull requests are filtered out
because GitHub returns them via the issues endpoint.
"""
import argparse
import json
import os
import sys

try:
    import requests
except ImportError:
    requests = None

BASE_URL = "https://api.github.com"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True, help="owner/repo")
    p.add_argument("--state", default="open", choices=["open", "closed", "all"])
    p.add_argument("--limit", type=int, default=20)
    args = p.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token or requests is None:
        print(json.dumps({
            "ok": False,
            "stub": True,
            "tool": "github-issue-list",
            "message": "Set GITHUB_TOKEN to enable",
        }))
        sys.exit(0)

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }
    url = f"{BASE_URL}/repos/{args.repo}/issues"
    resp = requests.get(
        url,
        headers=headers,
        params={"state": args.state, "per_page": args.limit},
    )
    resp.raise_for_status()
    items = resp.json()
    issues = [
        {
            "number": item["number"],
            "title": item["title"],
            "state": item["state"],
            "url": item["html_url"],
        }
        for item in items
        if "pull_request" not in item
    ]
    print(json.dumps({
        "ok": True,
        "tool": "github-issue-list",
        "issues": issues,
    }))


if __name__ == "__main__":
    main()
