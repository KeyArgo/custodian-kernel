#!/usr/bin/env python3
"""Execute script for nim-job-status.

Checks the status of an NVIDIA NIM inference job by GETting
https://integrate.api.nvidia.com/v1/jobs/{job_id} with a bearer token.
Always prints a single JSON line on stdout and exits 0. Falls back to a
stub response when NVIDIA_API_KEY is missing or `requests` is unavailable.
"""
import argparse
import json
import os
import sys

try:
    import requests
except ImportError:
    requests = None

BASE_URL = "https://integrate.api.nvidia.com/v1"
TOOL = "nim-job-status"


def _stub(message):
    print(json.dumps({
        "ok": False,
        "stub": True,
        "tool": TOOL,
        "message": message,
    }))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--job-id", default="", help="NIM job identifier")
    args = p.parse_args()

    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key or requests is None:
        _stub("Set NVIDIA_API_KEY to enable" if requests is not None
              else "requests library not installed")
        sys.exit(0)

    if not args.job_id:
        print(json.dumps({
            "ok": False,
            "tool": TOOL,
            "error": "--job-id is required",
        }))
        sys.exit(0)

    url = f"{BASE_URL}/jobs/{args.job_id}"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        ok = resp.ok
        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text}
        status = data.get("status") or ("ok" if ok else "error")
        result = data.get("result", data)
        print(json.dumps({
            "ok": ok,
            "tool": TOOL,
            "job_id": args.job_id,
            "status": status,
            "result": result,
        }))
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "tool": TOOL,
            "job_id": args.job_id,
            "error": str(e),
        }))


if __name__ == "__main__":
    main()
