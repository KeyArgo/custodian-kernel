#!/usr/bin/env python3
"""Execute script for huggingface-infer.

Calls the Hugging Face Inference API for a given model and returns the
raw model output. Always prints a single JSON line on stdout and exits 0.
Falls back to a stub response when HF_API_TOKEN is missing or `requests`
is unavailable.
"""
import argparse
import json
import os
import sys

try:
    import requests
except ImportError:
    requests = None

BASE_URL = "https://api-inference.huggingface.co/models"
TOOL = "huggingface-infer"


def _stub(message):
    print(json.dumps({
        "ok": False,
        "stub": True,
        "tool": TOOL,
        "message": message,
    }))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="", help="Hugging Face model id, e.g. gpt2")
    p.add_argument("--inputs", default="", help="Input text for the model")
    p.add_argument("--task", default="", help="Optional task hint, e.g. text-generation")
    p.add_argument("--timeout", type=int, default=60)
    args = p.parse_args()

    token = os.environ.get("HF_API_TOKEN")
    if not token or requests is None:
        _stub("Set HF_API_TOKEN to enable" if requests is not None
              else "requests library not installed")
        sys.exit(0)

    if not args.model or not args.inputs:
        print(json.dumps({
            "ok": False,
            "tool": TOOL,
            "error": "--model and --inputs are required",
        }))
        sys.exit(0)

    url = f"{BASE_URL}/{args.model}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    params = {}
    if args.task:
        params["task"] = args.task
    payload = {"inputs": args.inputs}

    try:
        resp = requests.post(
            url,
            headers=headers,
            params=params,
            json=payload,
            timeout=args.timeout,
        )
        ok = resp.ok
        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text}
        print(json.dumps({
            "ok": ok,
            "tool": TOOL,
            "model": args.model,
            "output": data,
        }))
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "tool": TOOL,
            "model": args.model,
            "error": str(e),
        }))


if __name__ == "__main__":
    main()
