#!/usr/bin/env python3
"""Generate stub SKILL.md files for all Custodian-governed tools.

Each stub has valid YAML frontmatter including custodian-band metadata,
so `custodian tools list` shows them immediately. Real execute.py scripts
are added by OpenCode in a second pass.
"""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"

TOOLS = [
    # (category, name, description, band, cost_usd, configured, tags)
    # ── Communication ────────────────────────────────────────────────────
    ("communication", "email-send",        "Send email via SMTP or SendGrid with subject and body",       "L1", 0.00, False, ["Communication", "Email"]),
    ("communication", "sms-send",          "Send SMS via Twilio to any phone number",                     "L1", 0.01, False, ["Communication", "SMS", "Twilio"]),
    ("communication", "slack-message",     "Post a message to a Slack channel via incoming webhook",      "L1", 0.00, False, ["Communication", "Slack"]),
    ("communication", "slack-channel-list","List public Slack channels in a workspace",                   "L0", 0.00, False, ["Communication", "Slack"]),
    ("communication", "discord-webhook",   "Post a message to a Discord channel via webhook URL",         "L1", 0.00, False, ["Communication", "Discord"]),
    ("communication", "webhook-post",      "Send an HTTP POST to any configured webhook endpoint",        "L1", 0.00, True,  ["Communication", "Webhook"]),
    ("communication", "push-notification", "Send a push notification via ntfy.sh or Pushover",           "L1", 0.00, False, ["Communication", "Push"]),

    # ── GitHub ────────────────────────────────────────────────────────────
    ("github",        "github-issue-create","Create a GitHub issue in a specified repository",           "L1", 0.00, False, ["GitHub", "Issues"]),
    ("github",        "github-issue-list",  "List open issues in a GitHub repository with filters",      "L0", 0.00, False, ["GitHub", "Issues"]),
    ("github",        "github-pr-list",     "List open pull requests in a GitHub repository",            "L0", 0.00, False, ["GitHub", "PullRequests"]),
    ("github",        "github-comment",     "Add a comment to a GitHub issue or pull request",           "L1", 0.00, False, ["GitHub", "Issues"]),
    ("github",        "github-repo-list",   "List repositories for a GitHub user or organization",       "L0", 0.00, False, ["GitHub", "Repos"]),
    ("github",        "github-file-read",   "Read a file from a public GitHub repository at a given ref","L0", 0.00, True,  ["GitHub", "Files"]),

    # ── HTTP / Web ─────────────────────────────────────────────────────────
    ("web",           "http-get",           "Perform an HTTP GET request and return the response body",   "L0", 0.00, True,  ["HTTP", "Web"]),
    ("web",           "http-post",          "Perform an HTTP POST with JSON body and return the response","L1", 0.00, True,  ["HTTP", "Web"]),
    ("web",           "web-scrape",         "Fetch and extract visible text from a web page URL",         "L0", 0.00, True,  ["HTTP", "Web", "Scraping"]),
    ("web",           "web-search",         "Search the web using DuckDuckGo and return top results",     "L0", 0.00, True,  ["Search", "Web"]),
    ("web",           "news-search",        "Search for recent news articles on a given topic",           "L0", 0.00, True,  ["Search", "News"]),

    # ── Files ──────────────────────────────────────────────────────────────
    ("files",         "file-read",          "Read a file from an allowed path on the local filesystem",   "L0", 0.00, True,  ["Files", "Local"]),
    ("files",         "file-write",         "Write content to a file at an allowed path",                 "L1", 0.00, True,  ["Files", "Local"]),
    ("files",         "file-list",          "List files in an allowed directory path",                    "L0", 0.00, True,  ["Files", "Local"]),
    ("files",         "shell-exec",         "Run a sandboxed shell command with timeout and allowlist",   "L2", 0.00, True,  ["Shell", "Local"]),

    # ── Docker ─────────────────────────────────────────────────────────────
    ("docker",        "docker-list",        "List running Docker containers with status and port info",   "L0", 0.00, True,  ["Docker", "Infrastructure"]),
    ("docker",        "docker-start",       "Start a stopped Docker container by name or ID",             "L2", 0.00, True,  ["Docker", "Infrastructure"]),
    ("docker",        "docker-stop",        "Stop a running Docker container gracefully",                 "L2", 0.00, True,  ["Docker", "Infrastructure"]),
    ("docker",        "docker-logs",        "Tail the last N lines of a Docker container's stdout log",   "L0", 0.00, True,  ["Docker", "Infrastructure"]),
    ("docker",        "docker-exec",        "Run a command inside a running Docker container",            "L2", 0.00, True,  ["Docker", "Infrastructure"]),

    # ── Memory / Storage ───────────────────────────────────────────────────
    ("memory",        "kv-get",             "Retrieve a value by key from the Custodian KV store",        "L0", 0.00, True,  ["Memory", "Storage"]),
    ("memory",        "kv-set",             "Store a key-value pair in the Custodian KV store",           "L0", 0.00, True,  ["Memory", "Storage"]),
    ("memory",        "kv-delete",          "Delete a key from the Custodian KV store",                   "L1", 0.00, True,  ["Memory", "Storage"]),
    ("memory",        "kv-list",            "List all keys in the Custodian KV store with optional prefix","L0",0.00, True,  ["Memory", "Storage"]),
    ("memory",        "sqlite-query",       "Run a read-only SQL query against a SQLite database file",   "L0", 0.00, True,  ["Database", "SQLite"]),

    # ── Scheduling ─────────────────────────────────────────────────────────
    ("scheduling",    "cron-create",        "Schedule a recurring task using cron syntax",                "L2", 0.00, False, ["Scheduling", "Cron"]),
    ("scheduling",    "cron-list",          "List all scheduled cron tasks managed by Custodian",         "L0", 0.00, False, ["Scheduling", "Cron"]),
    ("scheduling",    "cron-delete",        "Delete a scheduled cron task by name or ID",                 "L2", 0.00, False, ["Scheduling", "Cron"]),
    ("scheduling",    "task-queue-add",     "Add a one-shot task to the Custodian task queue",            "L1", 0.00, True,  ["Scheduling", "Queue"]),
    ("scheduling",    "task-queue-list",    "List pending and completed tasks in the Custodian queue",    "L0", 0.00, True,  ["Scheduling", "Queue"]),

    # ── Stripe extended ────────────────────────────────────────────────────
    ("stripe",        "stripe-balance",     "Fetch current Stripe account balance (test mode)",           "L0", 0.00, True,  ["Stripe", "Finance"]),
    ("stripe",        "stripe-customer-lookup","Look up a Stripe customer by email or ID",               "L0", 0.00, True,  ["Stripe", "Finance"]),
    ("stripe",        "stripe-subscription-create","Create a new Stripe subscription for a customer",    "L3", 0.10, False, ["Stripe", "Finance", "Subscriptions"]),
    ("stripe",        "stripe-subscription-cancel","Cancel a Stripe subscription immediately or at period end","L3",0.00, False,["Stripe", "Finance", "Subscriptions"]),
    ("stripe",        "stripe-invoice-send","Send a Stripe invoice to a customer",                        "L2", 0.00, False, ["Stripe", "Finance", "Invoices"]),
    ("stripe",        "stripe-payout",      "Initiate a Stripe payout to the connected bank account",    "L4", 0.00, False, ["Stripe", "Finance", "Payouts"]),

    # ── NVIDIA / AI ────────────────────────────────────────────────────────
    ("nvidia",        "nim-model-list",     "List available NVIDIA NIM models and their status",          "L0", 0.00, True,  ["NVIDIA", "NIM", "AI"]),
    ("nvidia",        "nim-job-submit",     "Submit an inference job to NVIDIA NIM and return a job ID",  "L2", 0.05, True,  ["NVIDIA", "NIM", "AI"]),
    ("nvidia",        "nim-job-status",     "Check the status and result of an NVIDIA NIM inference job", "L0", 0.00, True,  ["NVIDIA", "NIM", "AI"]),
    ("nvidia",        "openai-complete",    "Send a completion request to the OpenAI API",                "L1", 0.01, False, ["OpenAI", "AI"]),
    ("nvidia",        "huggingface-infer",  "Run inference on a HuggingFace model via the Inference API", "L1", 0.00, False, ["HuggingFace", "AI"]),

    # ── Modal ──────────────────────────────────────────────────────────────
    ("modal",         "modal-function-list","List deployed Modal functions in the current workspace",     "L0", 0.00, False, ["Modal", "Serverless"]),
    ("modal",         "modal-invoke",       "Invoke a deployed Modal function with JSON arguments",       "L2", 0.05, False, ["Modal", "Serverless"]),
    ("modal",         "modal-deploy",       "Deploy a Modal function from a local Python file",           "L3", 0.00, False, ["Modal", "Serverless"]),

    # ── Calendar ───────────────────────────────────────────────────────────
    ("calendar",      "calendar-event-create","Create a Google Calendar event with title, time, and attendees","L1",0.00,False,["Calendar", "Google"]),
    ("calendar",      "calendar-event-list","List upcoming Google Calendar events for a given timerange", "L0", 0.00, False, ["Calendar", "Google"]),

    # ── Utilities ──────────────────────────────────────────────────────────
    ("utilities",     "json-transform",     "Apply a jq-style filter to transform a JSON payload",        "L0", 0.00, True,  ["Utilities", "JSON"]),
    ("utilities",     "base64-encode",      "Base64-encode a string or file content",                     "L0", 0.00, True,  ["Utilities"]),
    ("utilities",     "base64-decode",      "Base64-decode a string and return raw or UTF-8 content",     "L0", 0.00, True,  ["Utilities"]),
    ("utilities",     "hash-sha256",        "Compute the SHA-256 hash of a string or file",               "L0", 0.00, True,  ["Utilities", "Security"]),
    ("utilities",     "currency-convert",   "Convert an amount between two currencies using live rates",  "L0", 0.00, True,  ["Utilities", "Finance"]),
    ("utilities",     "timezone-lookup",    "Convert a datetime between two IANA timezone identifiers",   "L0", 0.00, True,  ["Utilities"]),
    ("utilities",     "url-parse",          "Parse a URL and return its scheme, host, path, and query params","L0",0.00,True,["Utilities", "Web"]),
]

TEMPLATE = '''\
---
name: {name}
description: "{description}"
version: 1.0.0
author: custodian
license: MIT
platforms: [linux, darwin, windows]
metadata:
  hermes:
    tags: {tags}
  custodian:
    band: {band}
    cost_usd: {cost_usd}
    configured: {configured}
---

# {title}

{description}

## Authority band

This tool runs under **{band}** authority in the Custodian kernel.{band_note}

## Inputs

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| (see execute.py for full schema) | | | |

## Configuration

{config_section}

## Usage

```bash
custodian tools run {name} --param value
```

## Custodian governance

Every call to this tool passes through the Custodian kernel authority check
before executing. The kernel verifies the current authority band, checks
spending caps where applicable, logs the action to the OCSF audit trail,
and escalates to a human operator if the action exceeds the declared band.

Adding this tool to any Hermes agent session requires no code changes —
declare `custodian-band: {band}` in the SKILL.md frontmatter and the kernel
wraps it automatically.
'''

BAND_NOTES = {
    "L0": " Read-only; no real-world effects — always autonomous.",
    "L1": " Trivial autonomous spend or free side-effect — no human approval required.",
    "L2": " Autonomous up to the per-action and session caps; escalates above threshold.",
    "L3": " Always requires human approval via Twilio SMS before executing.",
    "L4": " Unlimited potential impact — always escalates; never executes autonomously.",
}

def config_section(name: str, configured: bool) -> str:
    if configured:
        return "No additional configuration required — uses credentials already wired to Custodian."
    return (
        f"Set the required environment variables before use. "
        f"Until configured, `custodian tools run {name}` returns a stub response "
        f"indicating which variables are needed."
    )

def make_skill(category, name, description, band, cost_usd, configured, tags):
    skill_dir = SKILLS / category / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)

    title = name.replace("-", " ").title()
    tags_yaml = "[" + ", ".join(tags) + "]"
    configured_yaml = "true" if configured else "false"

    content = TEMPLATE.format(
        name=name,
        description=description,
        band=band,
        cost_usd=cost_usd,
        configured=configured_yaml,
        tags=tags_yaml,
        title=title,
        band_note=BAND_NOTES.get(band, ""),
        config_section=config_section(name, configured),
    )
    (skill_dir / "SKILL.md").write_text(content)

    # placeholder execute.py so the registry can find it
    execute = scripts_dir / "execute.py"
    if not execute.exists():
        execute.write_text(f'''\
#!/usr/bin/env python3
"""Stub execute script for {name}.

Replace this with a real implementation.
OpenCode prompt: custodian/opencode-prompts/{category}-tools.md
"""
import argparse, json, os, sys

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args, rest = p.parse_known_args()

    configured = bool(os.environ.get("{name.upper().replace("-", "_")}_CONFIGURED"))
    if not configured:
        print(json.dumps({{
            "ok": False,
            "stub": True,
            "tool": "{name}",
            "message": "Set {name.upper().replace("-", "_")}_CONFIGURED=1 (and required credentials) to enable.",
        }}))
        sys.exit(0)

    # TODO: real implementation
    print(json.dumps({{"ok": True, "tool": "{name}", "result": "stub"}}))

if __name__ == "__main__":
    main()
''')

def add_custodian_band_to_existing(skill_md: Path, band: str, cost_usd: float = 0.0, configured: bool = True):
    """Patch an existing SKILL.md to add custodian metadata."""
    text = skill_md.read_text()
    if "custodian:" in text:
        return  # already has it
    inject = f"  custodian:\n    band: {band}\n    cost_usd: {cost_usd}\n    configured: {'true' if configured else 'false'}\n"
    # find metadata: block
    if "  hermes:" in text:
        text = text.replace("  hermes:", inject + "  hermes:", 1)
    elif "metadata:" in text:
        text = text.replace("metadata:", f"metadata:\n{inject}", 1)
    else:
        # insert before the closing ---
        parts = text.split("---", 2)
        if len(parts) >= 3:
            parts[1] += f"\nmetadata:\n{inject}"
            text = "---".join(parts)
    skill_md.write_text(text)
    print(f"  patched {skill_md.relative_to(REPO)}")

if __name__ == "__main__":
    print(f"Generating {len(TOOLS)} tool stubs under {SKILLS}/")
    for tool in TOOLS:
        make_skill(*tool)
        print(f"  created  skills/{tool[0]}/{tool[1]}/")

    # patch existing stripe-spend to add custodian metadata
    stripe_md = SKILLS / "payments" / "stripe-spend" / "SKILL.md"
    if stripe_md.exists():
        add_custodian_band_to_existing(stripe_md, band="L2", cost_usd=0.0, configured=True)
        print(f"  patched  skills/payments/stripe-spend/SKILL.md")

    print(f"\nDone. Run: custodian tools list")
