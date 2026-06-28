#!/usr/bin/env python3
"""Execute script for github-issue-create.

Creates a new GitHub issue.
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
    p.add_argument("--title", required=True, help="issue title")
    p.add_argument("--body", default="", help="issue body")
    p.add_argument("--labels", default="", help="comma-separated labels")
    args = p.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token or requests is None:
        print(json.dumps({
            "ok": False,
            "stub": True,
            "tool": "github-issue-create",
            "message": "Set GITHUB_TOKEN to enable",
        }))
        sys.exit(0)

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }
    payload = {"title": args.title}
    if args.body:
        payload["body"] = args.body
    if args.labels:
        payload["labels"] = [s.strip() for s in args.labels.split(",") if s.strip()]
    url = f"{BASE_URL}/repos/{args.repo}/issues"
    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    data = resp.json()
    print(json.dumps({
        "ok": True,
        "tool": "github-issue-create",
        "number": data["number"],
        "url": data["html_url"],
    }))


if __name__ == "__main__":
    main()
