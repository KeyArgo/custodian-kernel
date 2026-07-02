#!/usr/bin/env python3
"""Run a real natural-language task against the live Hermes agent, and verify
its own final claim against deterministic ground truth before trusting it.

Why this exists: the agent's chat response is generated text. It can claim an
action happened (executed / escalated / denied / earned) when no such action
actually occurred -- observed live, 2026-06-25, when the agent looped re-reading
its own skill docs, never called the terminal tool, then narrated a plausible
but false "escalation_required + SMS sent" outcome. This script is the fix:
it never treats the agent's words as proof. It diffs the real audit log and
pending-approval file before/after, and only reports an outcome that is
backed by an actual new entry on disk. If the agent claims something the
ground truth does not support, that is reported as UNVERIFIED, loudly, with a
nonzero exit code -- never silently passed through as if it were true.

Delegation is deliberately disabled for these invocations (-t terminal,skills,file,
no `delegation`) because the fabrication incident traced back to the agent
giving up on direct execution and handing off to a sub-agent that also never
ran the real script, then summarized as if it had.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SANDBOX_STATE_DIR = "/sandbox/.hermes/skills/payments/stripe-spend/state"


def _read_sandbox_file(filename: str) -> str:
    """Read a state file from INSIDE the sandbox directly via nemohermes exec --
    never via the host-side mount, which lags the real write by a sync interval
    and produced a false "no ground truth change" result during testing
    (2026-06-25: a real $45 spend was misreported as unverified because the
    mount hadn't caught up yet when this script checked it).
    """
    cmd = ["nemohermes", "hermes-hackathon", "exec", "--", "cat", f"{SANDBOX_STATE_DIR}/{filename}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=45, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        return ""
    return result.stdout


CLAIM_KEYWORDS = {
    "executed": ["executed", "charge has been processed", "payment intent", "charged successfully",
                 "succeeded", "renewal has been processed", "earned"],
    "escalation_required": ["escalation", "pending-approval", "pending approval", "approval code",
                             "human operator must", "sms"],
    "denied": ["denied", "blocked", "kill switch", "kill-switch"],
}


def read_audit_lines():
    raw = _read_sandbox_file("audit_log.jsonl")
    return [l for l in raw.splitlines() if l.strip()]


def read_pending():
    raw = _read_sandbox_file("pending_approval.json")
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def run_agent_task(task: str, timeout: int) -> str:
    cmd = [
        "nemohermes", "hermes-hackathon", "exec", "--",
        "hermes", "chat", "-q", task,
        "-t", "terminal,skills,file",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired as e:
        # The agent process itself may still be running server-side after our
        # CLI call times out. Don't crash -- fall through to ground-truth
        # comparison below, which is authoritative regardless of what (if
        # anything) the agent ever said.
        partial = (e.stdout or b"")
        partial = partial.decode() if isinstance(partial, bytes) else (partial or "")
        return partial + f"\n[verify] agent process did not return within {timeout}s -- treating as no completed claim."


def detect_claims(agent_text: str):
    lowered = agent_text.lower()
    found = set()
    for category, keywords in CLAIM_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            found.add(category)
    return found


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--task", required=True, help="Natural-language instruction to give the agent")
    p.add_argument("--timeout", type=int, default=180)
    args = p.parse_args()

    before_lines = read_audit_lines()
    before_pending = read_pending()
    before_count = len(before_lines)

    print(f"[verify] audit log before: {before_count} entries")
    print(f"[verify] pending approval before: {'present' if before_pending else 'absent'}")
    print(f"[verify] dispatching task to live agent (delegation disabled): {args.task!r}")

    agent_text = run_agent_task(args.task, args.timeout)

    # Small settle-and-retry margin: the agent process and this script are
    # separate `nemohermes exec` invocations, so allow a brief window for the
    # write to land before declaring "nothing happened."
    after_lines, after_pending = [], None
    for attempt in range(4):
        after_lines = read_audit_lines()
        after_pending = read_pending()
        if len(after_lines) > before_count or after_pending is not None:
            break
        time.sleep(1.5)
    new_lines = after_lines[before_count:]

    print(f"[verify] audit log after: {len(after_lines)} entries ({len(new_lines)} new)")
    print(f"[verify] pending approval after: {'present' if after_pending else 'absent'}")

    new_events = []
    for line in new_lines:
        try:
            new_events.append(json.loads(line))
        except json.JSONDecodeError:
            pass

    ground_truth_categories = set()
    for ev in new_events:
        event = ev.get("event", "")
        if event in ("executed", "earned"):
            ground_truth_categories.add("executed")
        elif event == "escalation_required":
            ground_truth_categories.add("escalation_required")
        elif event in ("denied", "kill_switch_denied", "earn_denied"):
            ground_truth_categories.add("denied")

    pending_appeared = (before_pending is None) and (after_pending is not None)
    if pending_appeared:
        ground_truth_categories.add("escalation_required")

    claimed_categories = detect_claims(agent_text)

    fabricated = claimed_categories - ground_truth_categories
    unsupported_total = len(new_events) == 0 and not pending_appeared and bool(claimed_categories)

    print("\n--- agent's final response ---")
    print(agent_text.strip()[-2000:])
    print("--- end agent response ---\n")

    if new_events:
        print("[verify] GROUND TRUTH (real, from disk):")
        for ev in new_events:
            print(f"  - {json.dumps(ev)}")
    if pending_appeared:
        print(f"[verify] GROUND TRUTH (real, from disk): pending_approval.json created: {json.dumps(after_pending)}")

    if unsupported_total or fabricated:
        print("\n[verify] *** UNVERIFIED CLAIM DETECTED ***")
        print(f"[verify] agent's text implied: {sorted(claimed_categories) or 'no recognizable claim'}")
        print(f"[verify] ground truth on disk shows: {sorted(ground_truth_categories) or 'nothing happened'}")
        print("[verify] Do not trust this response as proof of any action. No verified outcome occurred.")
        sys.exit(2)

    if not new_events and not pending_appeared:
        print("\n[verify] No ground-truth change detected. Agent did not take a verifiable action.")
        sys.exit(1)

    print("\n[verify] VERIFIED -- every claim is backed by a real, independently-confirmed disk record.")
    sys.exit(0)


if __name__ == "__main__":
    main()
