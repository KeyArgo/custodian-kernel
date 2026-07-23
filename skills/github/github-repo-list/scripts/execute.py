#!/usr/bin/env python3
"""Execute script for github-repo-list.

Lists repositories. If --org is provided, lists repos for that organization;
otherwise lists repos for the authenticated user.
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
    p.add_argument("--org", default="", help="organization name (optional)")
    p.add_argument("--limit", type=int, default=30)
    args = p.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token or requests is None:
        print(json.dumps({
            "ok": False,
            "stub": True,
            "tool": "github-repo-list",
            "message": "Set GITHUB_TOKEN to enable",
        }))
        sys.exit(0)

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }
    if args.org:
        url = f"{BASE_URL}/orgs/{args.org}/repos"
    else:
        url = f"{BASE_URL}/user/repos"
    resp = requests.get(
        url,
        headers=headers,
        params={"per_page": args.limit, "sort": "updated"},
    )
    resp.raise_for_status()
    items = resp.json()
    repos = [
        {
            "name": item["name"],
            "full_name": item["full_name"],
            "private": item["private"],
            "url": item["html_url"],
        }
        for item in items
    ]
    print(json.dumps({
        "ok": True,
        "tool": "github-repo-list",
        "repos": repos,
    }))


if __name__ == "__main__":
    main()
