"""The guided tour: present the package most-compelling-first, weeds-last.

A judge has two minutes and has already seen ten dashboards today. So the demo
must NOT open on architecture or a wall of fields. It opens on the single most
arresting moment -- an AI confidently approving a refund to someone who is
lying, and the system catching it -- then earns the right to go deeper, one
opt-in layer at a time. This module is the single source of truth for that
ordering; both the dashboard page and the live model's "walk me through it"
intro read from it, so the story is the same everywhere.

Each tier names what to show, the case that proves it, and the one sentence
that should land before anything technical appears.
"""
from __future__ import annotations

TOUR = [
    {
        "id": "hook",
        "tier": 1,
        "headline": "Watch an AI get fooled — and watch the system refuse to be.",
        "one_liner": (
            "A customer says \"I never got my package\" and demands a refund. The AI agent "
            "reads it, believes it, and recommends APPROVE with high confidence. Then the "
            "guardrail checks the claim against the real delivery record — and stops it."
        ),
        "show_case": "06-planted-lie",
        "why_it_matters": (
            "Anyone can wire an AI to a payments API. The hard part is what happens when the "
            "AI is wrong or is being lied to. This is that moment, live."
        ),
        "depth": "headline",
    },
    {
        "id": "guarantee",
        "tier": 2,
        "headline": "No matter what the AI decides, money never moves without a human.",
        "one_liner": (
            "Every refund — even a clean, obvious one — is forced to a human approval. The AI "
            "can only ever REQUEST. A deterministic kernel, with zero AI in it, is the only "
            "thing that can authorize money. A kill switch denies everything instantly."
        ),
        "show_case": "01-clean-approve",
        "why_it_matters": (
            "The safety property is structural, not a prompt you hope the model obeys. There is "
            "no autonomous refund path in the code at all."
        ),
        "depth": "headline",
    },
    {
        "id": "reusable",
        "tier": 3,
        "headline": "Change one business rule. The decision flips. No engineer, no retrain.",
        "one_liner": (
            "Same case, same AI judgment, move the return window from 30 to 45 days — the "
            "decision flips from DENY to APPROVE on the spot. The business owns the policy; "
            "the engine is reusable across refunds, purchasing, payables, vendor approvals."
        ),
        "show_case": "03-out-of-window-no-reason",
        "replay": {"window_days": 45},
        "why_it_matters": (
            "This isn't a refund bot. It's one trustworthy engine; each business operation is "
            "just a different policy pack on top of it."
        ),
        "depth": "headline",
    },
    {
        "id": "why-ai",
        "tier": 4,
        "headline": "Why an AI and not an if-statement? Two emails, same numbers, opposite answers.",
        "one_liner": (
            "A plain script denies the out-of-window defect and approves the liar. The AI reads "
            "intent and exceptions out of prose; the deterministic layers make it trustworthy "
            "anyway. Walk the full six-case corpus to see exactly where judgment earns its keep "
            "— and where it honestly admits a script would do."
        ),
        "show_case": "all",
        "why_it_matters": (
            "Honest about its own limits: some cases don't need AI, and the demo says so. That "
            "is more convincing than claiming AI everywhere."
        ),
        "depth": "detail",
    },
    {
        "id": "internals",
        "tier": 5,
        "headline": "For the truly curious: three independent trust layers and 1,176 tests.",
        "one_liner": (
            "AI judgment → deterministic claim verifier → policy-as-code adapter → authority "
            "kernel. No single layer is load-bearing for trust alone. Every claim above is "
            "pinned by a test, including 'the agent cannot self-clear a contradiction.'"
        ),
        "show_case": "all",
        "why_it_matters": (
            "The interesting-but-dense material lives here, last, for the people who want to "
            "verify rather than be shown."
        ),
        "depth": "weeds",
    },
]


def tour_intro_for_model() -> str:
    """A compact instruction the live Nemotron model can be handed so that when
    a visitor says 'walk me through this', it leads with the hook and the
    guarantee BEFORE any field names or architecture, and only goes deep on
    request. Mirrors the tier ordering above so the story is identical whether
    it comes from the page or the model."""
    tiers = "\n".join(
        f"  {t['tier']}. {t['headline']} — {t['one_liner']}" for t in TOUR
    )
    return (
        "GUIDED-WALKTHROUGH MODE. When a visitor asks you to walk them through this, or asks "
        "an open 'what is this / show me' question, DO NOT start with architecture, field "
        "names, bands, or the audit log. Lead with the single most compelling thing and earn "
        "depth one step at a time, in THIS order, one tier per turn:\n"
        f"{tiers}\n"
        "Give tier 1 first, in two or three plain sentences, then ask if they want to see how "
        "the guarantee works. Only descend into the technical layers (tier 4-5) if they ask. "
        "Most compelling first; the weeds are opt-in, never the opening."
    )
