#!/usr/bin/env python3
"""Execute script for openai-complete.

Calls the OpenAI Chat Completions API. Always prints a single JSON line on
stdout and exits 0. Falls back to a stub response when OPENAI_API_KEY is
missing or `requests` is unavailable.
"""
import argparse
import json
import os
import sys

try:
    import requests
except ImportError:
    requests = None

BASE_URL = "https://api.openai.com/v1/chat/completions"
TOOL = "openai-complete"
DEFAULT_MODEL = "gpt-4o-mini"


def _stub(message):
    print(json.dumps({
        "ok": False,
        "stub": True,
        "tool": TOOL,
        "message": message,
    }))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=DEFAULT_MODEL, help="OpenAI chat model")
    p.add_argument("--prompt", default="", help="User prompt text")
    p.add_argument("--max-tokens", type=int, default=256)
    p.add_argument("--system", default="", help="Optional system prompt")
    p.add_argument("--timeout", type=int, default=60)
    args = p.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or requests is None:
        _stub("Set OPENAI_API_KEY to enable" if requests is not None
              else "requests library not installed")
        sys.exit(0)

    if not args.prompt:
        print(json.dumps({
            "ok": False,
            "tool": TOOL,
            "error": "--prompt is required",
        }))
        sys.exit(0)

    messages = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": args.prompt})

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": args.model,
        "messages": messages,
        "max_tokens": args.max_tokens,
    }

    try:
        resp = requests.post(
            BASE_URL,
            headers=headers,
            json=payload,
            timeout=args.timeout,
        )
        ok = resp.ok
        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text}
        content = ""
        if isinstance(data, dict):
            choices = data.get("choices") or []
            if choices:
                content = choices[0].get("message", {}).get("content", "")
        usage = data.get("usage") if isinstance(data, dict) else None
        print(json.dumps({
            "ok": ok,
            "tool": TOOL,
            "model": args.model,
            "content": content,
            "usage": usage,
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
