"""Session policy — one YAML file that declares everything Hermes may do.

The operator writes ``hermes-session.yaml``; ``build_bridge()`` compiles
it into the full governed stack (capsule + guard adapters + Warden +
bridge). Granular control over tools, files, hosts, spend, skill
authoring, and privacy — in one reviewable artifact::

    goal: "keep the homelab healthy"
    band: L2
    budget_usd: 25.00
    constraints:
      - "never touch production databases"

    tools:
      allow: [http-get, stripe-spend, file-read, file-write]   # omit = all
      forbid: [stripe-payout]

    files:
      workspace: /srv/agent-workspace       # writes fenced to here
      skill_quarantine: /srv/agent-workspace/skill-drafts

    network:
      hosts: [api.stripe.com, integrate.api.nvidia.com]

    money:
      max_per_minute: 4
      duplicate_window_s: 900

    privacy:
      redact: []          # empty = redact every kind pii-redactor knows about

    guards:                # togglable; set false to drop one.
      repetition: true     # self_protection/prompt_injection/secret_leak are
      pii: true             # NOT listed here — they're kernel-grade and
      introspection: true  # always on, not settable via policy.

Everything unspecified stays enforced at safe defaults — the file can
only *narrow* sensible baselines, not silently widen them (e.g. there
is no key that disables the kernel or the confabulation check).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from custodian.adapters.pipeline import AdapterPipeline
from custodian.adapters.builtin import (
    ContextAnchor,
    KernelSelfProtection,
    PiiRedactor,
    PromptInjectionGuard,
    RepetitionBreaker,
    ScopeFence,
    SecretLeakGuard,
    SpendSentinel,
)
from talaria.bridge import HermesBridge
from talaria.capsule import SessionCapsule


def load_session_policy(path: str | Path) -> dict:
    doc = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(doc, dict):
        raise ValueError(f"{path} is not a mapping")
    return doc


def build_bridge(policy_path: str | Path, registry=None, broker=None,
                 capsule_path: Optional[str | Path] = None) -> HermesBridge:
    """Compile a session-policy YAML into a ready HermesBridge."""
    doc = load_session_policy(policy_path)
    guards = doc.get("guards", {})

    capsule = SessionCapsule.load_or_create(
        capsule_path or Path(policy_path).with_suffix(".capsule.json"),
        goal=doc.get("goal", ""),
        constraints=list(doc.get("constraints", [])),
        band=doc.get("band", "L1"),
        max_session_cost_usd=float(doc.get("budget_usd", 0) or 0),
    )

    pipeline = AdapterPipeline()

    # Security first — self-protection and injection guards run before
    # anything else can be steered by hostile arguments. Unconditional:
    # these are kernel-grade and cannot be disabled by policy (same fix
    # as talaria/policy.py's build_pipeline() — found in review that
    # this was a separate, parallel copy of the identical bug: a policy
    # file with self_protection: false silently dropped it).
    pipeline.add(KernelSelfProtection({
        "quarantine": doc.get("files", {}).get("skill_quarantine", ""),
        "protected_paths": doc.get("files", {}).get("protected", []),
    }))
    pipeline.add(PromptInjectionGuard(
        {"strict": bool(guards.get("strict_injection", False))}))
    pipeline.add(SecretLeakGuard(
        leak_sentinel=broker.leak_sentinel if broker else None))

    # Invariants: tool fences + budget, enforced and re-anchorable.
    tools = doc.get("tools", {})
    pipeline.add(ContextAnchor({
        "goal": doc.get("goal", ""),
        "constraints": list(doc.get("constraints", [])),
        "allowed_skills": list(tools.get("allow", [])),
        "forbidden_skills": list(tools.get("forbid", [])),
        "max_session_cost_usd": float(doc.get("budget_usd", 0) or 0),
    }))

    # Task scope: files + network.
    files, network = doc.get("files", {}), doc.get("network", {})
    if files.get("workspace") or network.get("hosts"):
        pipeline.add(ScopeFence({
            "path_prefixes": [files["workspace"]] if files.get("workspace") else [],
            "url_hosts": list(network.get("hosts", [])),
            "arg_pins": doc.get("pins", {}),
        }))

    # Money + loops.
    money = doc.get("money", {})
    pipeline.add(SpendSentinel(money))
    if guards.get("repetition", True):
        pipeline.add(RepetitionBreaker(doc.get("repetition", {})))

    privacy = doc.get("privacy", {})
    if guards.get("pii", True):
        # Same fix as talaria/policy.py: an empty/absent redact list must
        # mean "redact every kind" (PiiRedactor's own default when no
        # kinds= key is given at all), not "add nothing" — the previous
        # `if privacy.get("redact"):` gate silently skipped this guard
        # whenever redact was unset, even though pii-style guards should
        # be on by default.
        redact = privacy.get("redact") or []
        config = {
            "deny_on_args": bool(privacy.get("deny_on_args", False)),
            "allowlist": list(privacy.get("allowlist", [])),
        }
        if redact:
            config["kinds"] = list(redact)
        pipeline.add(PiiRedactor(config))

    # Capability adapters (answer actions rather than veto them) — all opt-out.
    if guards.get("introspection", True):
        from talaria.introspection import IntrospectionAdapter
        pipeline.add(IntrospectionAdapter(capsule=capsule, broker=broker))

    return HermesBridge(registry=registry, pipeline=pipeline, broker=broker,
                        capsule=capsule,
                        anchor_every=int(doc.get("anchor_every", 5) or 5))
