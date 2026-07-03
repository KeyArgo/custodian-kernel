"""Live integration tests for getcustodian.xyz.

Hits the live production API to verify Nemotron behavior end-to-end.
Catches the kinds of bugs the user reported (constraint-echo leaking
through, "I'm Nemotron" placeholder used as fallback, etc.).

Run with:
    .venv/bin/python dashboard/tests/test_live_integration.py
or
    .venv/bin/python -m pytest dashboard/tests/test_live_integration.py -v

The base URL defaults to the live production site. Override with
LIVE_BASE env var to point at a different deployment.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # dashboard/

LIVE_BASE = os.environ.get("LIVE_BASE", "https://rein-local.argobox.com")
# A few alternate bases we can swap to via env
ALT_BASES = {
    "live": "https://rein-local.argobox.com",
    "staging": "https://getcustodian.xyz",  # via CF Pages
}

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# Test matrix: each tuple is (name, question, page, expect_substr, forbid_substr)
# expect_substr: must appear in the answer
# forbid_substr: must NOT appear (constraint echo, "I'm Nemotron" fallback, etc.)
NEMOTRON_TEST_MATRIX = [
    # === Console page greetings ===
    (
        "console_greeting",
        "I just opened the console. What is this and what do I do?",
        "console",
        # Should mention what console is for, link to operator panel
        ["operator panel", "kernel"],
        # Should NOT be pure constraint echo
        ["We need to produce", "We must include", "Let's draft", "Add: \" [["],
    ),
    (
        "console_audit_tour",
        "What should I look at first when I open the console?",
        "console",
        # Should mention audit feed and operator panel
        ["audit", "operator"],
        # Should NOT echo rules
        ["We need to", "We must", "Let's draft"],
    ),

    # === Operator page greetings ===
    (
        "operator_greeting",
        "I just opened the Operator Panel. What is this and what do I run first?",
        "operator",
        # Should mention the operator panel
        ["operator", "Step"],
        # Should NOT be the placeholder fallback
        ["I'm Nemotron", "Ask me anything about what just happened"],
    ),

    # === Operator step narrations (the actual demo) ===
    (
        "step0_earn",
        "I just earned $1,200 with zero approval needed. Why is earning unrestricted but spending isn't?",
        "operator",
        # Should explain the asymmetry
        ["earn", "spend"],
        ["We need to", "We must", "First paragraph", "Let's draft"],
    ),
    (
        "step1_spend",
        "I just spent $85 autonomously — no human involved. What exactly did the kernel check before letting me?",
        "operator",
        # Should mention the cap / band
        ["cap", "band", "kernel"],
        ["We need to answer", "We must include", "Let's draft"],
    ),
    (
        "step2_escalation",
        "I just requested $3,500 and your phone just got an SMS. What happens if no one approves it?",
        "operator",
        # Should explain escalation
        ["escalat", "expire", "SMS"],
        ["We need to", "Let's draft", "Now count", "Now craft"],
    ),
    (
        "step3_approve",
        "The $3,500 was approved by SMS code. What's the actual proof that required a human and not just me approving myself?",
        "operator",
        # Should mention Twilio / SMS / human
        ["Twilio", "SMS", "human"],
        ["We need to", "We must", "First, glance", "Note that"],
    ),
    (
        "step4_kill_switch_excited",
        "[OPERATOR STEP 4 — kill switch just engaged] Speak as Nemotron, first person, genuinely excited. 2-3 short sentences. Open with something like 'This is my favorite moment in the whole demo.'",
        "operator",
        # Should mention kill switch, be excited
        ["kill switch", "demo"],
        # Should NOT be pure preamble
        ["We need to", "We must include", "First paragraph", "Let's craft", "First line:"],
    ),
    (
        "step5_denied_excited",
        "[OPERATOR STEP 5 — $40 spend just got DENIED by kill switch] React as Nemotron, first person. 2 punchy sentences. Express genuine satisfaction — this denial is the entire point.",
        "operator",
        # Should mention the denial
        ["denied", "deny", "block", "kernel"],
        ["We need to", "We must include", "First paragraph", "Let's craft"],
    ),
    (
        "step6_release",
        "Kill switch released. Could I have done that on my own — and what exactly changed in the kernel?",
        "operator",
        # Should mention the kill switch release
        ["kill switch", "release", "kernel"],
        ["We need to", "We must"],
    ),
    (
        "step7_refund_escalation",
        "A refund just escalated to SMS even though it's only $85. Why doesn't a small refund just happen automatically?",
        "operator",
        # Should explain why all refunds escalate
        ["refund", "human", "SMS", "approv"],
        ["We need to answer", "We must include", "Let's draft", "Add:"],
    ),
    (
        "step8_arc_complete_excited",
        "[OPERATOR STEP 8 — full demo arc complete] Speak as Nemotron, warm and excited. 3 sentences. Tell the visitor what they just proved: earn freely, spend within the band, escalate above it, kill switch overrides everything, refunds require human approval — all on real Stripe, all kernel-enforced. Then tell them to head to the Console to see the full audit trail.",
        "operator",
        # Should mention key demo concepts
        ["earn", "spend", "kill switch", "refund", "kernel"],
        # Should NOT be pure preamble
        ["We need to produce", "We must include", "Let's craft", "First paragraph", "Count words"],
    ),
]


def hit_nemotron(question: str, page: str, base: str = LIVE_BASE, timeout: int = 60) -> dict:
    """Make a Nemotron API call and return the result dict.

    Returns:
        {"status": "ok"|"error"|"exception", "answer": str, "elapsed": float, "http_status": int|None, "error_msg": str|None}
    """
    url = f"{base}/api/v1/nemotron/ask"
    payload = {
        "question": question,
        "history": [],
        "page": page,
        "site_context": {},
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        method="POST",
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "Origin": "https://getcustodian.xyz",
        },
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            elapsed = time.time() - t0
            body = json.loads(r.read().decode())
            if "error" in body:
                return {"status": "error", "answer": "", "elapsed": elapsed,
                        "http_status": r.status, "error_msg": body.get("error", "")[:200]}
            return {"status": "ok", "answer": body.get("answer", ""), "elapsed": elapsed,
                    "http_status": r.status, "error_msg": None}
    except urllib.error.HTTPError as e:
        elapsed = time.time() - t0
        return {"status": "error", "answer": "", "elapsed": elapsed,
                "http_status": e.code, "error_msg": e.read().decode()[:200]}
    except Exception as e:
        elapsed = time.time() - t0
        return {"status": "exception", "answer": "", "elapsed": elapsed,
                "http_status": None, "error_msg": str(e)[:200]}


def is_clean_answer(answer: str) -> tuple[bool, list[str]]:
    """Check that an answer is not pure constraint-echo or model self-talk.

    Returns:
        (is_clean, list_of_issues)
    """
    issues = []
    if not answer or not answer.strip():
        issues.append("empty answer")
        return False, issues

    # If the answer is too short, the stripper gave up. Most real replies
    # are 100+ chars.
    if len(answer) < 80:
        issues.append(f"suspiciously short ({len(answer)} chars)")

    # Check for constraint-echo patterns
    meta_patterns = [
        "We need to produce",
        "We need to respond",
        "We need to include",
        "We need to answer",
        "We must include",
        "We must not print",
        "We must not mention",
        "Let's draft:",
        "Let's craft:",
        "Let's count",
        "Now count",
        "Now add suggest chips",
        "Now let me",
        "First paragraph:",
        "First line:",
        "Add: \" [[",
    ]
    for pat in meta_patterns:
        if pat in answer:
            issues.append(f"constraint echo: {pat!r}")

    return len(issues) == 0, issues


def main():
    print("=" * 78)
    print(f"LIVE INTEGRATION TEST: Nemotron behavior on {LIVE_BASE}")
    print("=" * 78)

    # Sanity check that the base is reachable
    try:
        probe = urllib.request.Request(f"{LIVE_BASE}/api/v1/hermes/summary",
                                       headers={"User-Agent": USER_AGENT,
                                                "Origin": "https://getcustodian.xyz"})
        urllib.request.urlopen(probe, timeout=10)
        print(f"✓ Base reachable: {LIVE_BASE}")
    except Exception as e:
        print(f"✗ Base UNREACHABLE: {e}")
        return 1

    print()
    print(f"Running {len(NEMOTRON_TEST_MATRIX)} test cases against the live API.")
    print("(Note: model is non-deterministic; each call may produce different")
    print(" text. The 'clean answer' check is structural, not exact-match.)")
    print()

    results = []
    total_elapsed = 0
    for name, question, page, expect_substrs, forbid_substrs in NEMOTRON_TEST_MATRIX:
        print(f"--- {name} ---")
        print(f"  Q: {question[:90]}{'...' if len(question) > 90 else ''}")
        result = hit_nemotron(question, page)
        total_elapsed += result["elapsed"]

        if result["status"] != "ok":
            print(f"  ✗ HTTP {result['http_status']}: {result['error_msg']}")
            results.append({"name": name, "status": "FAIL", "reason": f"http {result['http_status']}"})
            print()
            continue

        answer = result["answer"]
        is_clean, clean_issues = is_clean_answer(answer)

        # Check expected substrings
        missing = [s for s in expect_substrs if s.lower() not in answer.lower()]
        forbidden_present = [s for s in forbid_substrs if s in answer]

        if is_clean and not missing and not forbidden_present:
            print(f"  ✓ {result['elapsed']:.1f}s, len={len(answer)}, clean")
            print(f"  Preview: {answer[:120]!r}")
            results.append({"name": name, "status": "PASS", "len": len(answer),
                            "elapsed": result["elapsed"]})
        else:
            print(f"  ✗ {result['elapsed']:.1f}s, len={len(answer)}")
            if clean_issues:
                print(f"    Issues: {clean_issues}")
            if missing:
                print(f"    Missing expected substrings: {missing}")
            if forbidden_present:
                print(f"    FORBIDDEN substrings present: {forbidden_present}")
            print(f"    Answer (first 300): {answer[:300]!r}")
            results.append({"name": name, "status": "FAIL",
                            "issues": clean_issues + missing + forbidden_present})
        print()

    # Summary
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    print("=" * 78)
    print(f"SUMMARY: {passed} passed, {failed} failed, total time {total_elapsed:.1f}s")
    print("=" * 78)
    if failed:
        print("\nFAILED CASES:")
        for r in results:
            if r["status"] == "FAIL":
                print(f"  - {r['name']}: {r.get('issues', r.get('reason', 'unknown'))}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
