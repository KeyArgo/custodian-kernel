#!/usr/bin/env python3
"""Execute script for github-comment.

Posts a comment on a GitHub issue or pull request.
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
    p.add_argument("--issue", type=int, required=True, help="issue or PR number")
    p.add_argument("--body", required=True, help="comment body")
    args = p.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token or requests is None:
        print(json.dumps({
            "ok": False,
            "stub": True,
            "tool": "github-comment",
            "message": "Set GITHUB_TOKEN to enable",
        }))
        sys.exit(0)

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }
    url = f"{BASE_URL}/repos/{args.repo}/issues/{args.issue}/comments"
    resp = requests.post(url, headers=headers, json={"body": args.body})
    resp.raise_for_status()
    data = resp.json()
    print(json.dumps({
        "ok": True,
        "tool": "github-comment",
        "id": data["id"],
        "url": data["html_url"],
    }))


if __name__ == "__main__":
    main()
