"""Talaria policy — one YAML file that declares every standing rule, and
the compiler that turns it into a live guard-adapter pipeline.

This is the single place a user states "the rules": which tools the agent
may/may not call, which paths it may never read or write, whether to log
denied attempts. The rules are enforced MECHANICALLY on every tool call
(the model can't talk its way around a guard), and the compiled pipeline
is what the Hermes plugin runs.

Everything unspecified stays at a safe default — the file can only
*narrow*, never disable the kernel-grade protections (self-protection,
secret-leak, prompt-injection are always on).

Example ~/.talaria/policy.yaml::

    tools:
      forbid: [stripe-payout]        # the agent literally cannot call these
      # allow: [read_file, write_file, shell]   # if set, ONLY these

    paths:
      forbid: ["~/.ssh", "~/.aws", "~/.gnupg"]
      forbid_globs: ["*.env", "*.pem", "id_*"]
      # allow: ["/srv/agent-workspace"]   # confine to a workspace

    privacy:
      redact: [email, phone, ssn, card]

    log_denials: true                 # record what it tried but wasn't allowed

    guards:                           # togglable guards; set false to drop one.
      pii: true                       # self_protection/secret_leak/prompt_injection
      repetition: true                # are NOT listed here — they're kernel-grade
      tool_confabulation: false       # and always on, not settable via policy.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

from custodian.adapters.pipeline import AdapterPipeline
from custodian.adapters.builtin import (
    ContextAnchor,
    EgressDomainGuard,
    KernelSelfProtection,
    PathFence,
    PiiRedactor,
    PromptInjectionGuard,
    RepetitionBreaker,
    SecretLeakGuard,
)

POLICY_FILENAME = "policy.yaml"


def talaria_home() -> Path:
    """Resolved at call time so ``TALARIA_HOME`` set after import (tests, or
    a process that changes it) is honored, not frozen at first import."""
    return Path(os.environ.get("TALARIA_HOME", "~/.talaria")).expanduser()

# Sensible default denylist for the "just works" install — the paths a
# personal machine most wants an agent kept out of.
DEFAULT_FORBIDDEN_PATHS = [
    "~/.ssh", "~/.aws", "~/.gnupg", "~/.config/gcloud",
    "~/.paladin", "~/.talaria", "~/.custodian",
]
DEFAULT_FORBIDDEN_GLOBS = ["*.env", "*.pem", "id_rsa", "id_ed25519", "*.key"]

STARTER_POLICY = """\
# Talaria policy — the standing rules for your local agent.
# Enforced mechanically on every tool call. See docs/TALARIA.md.

tools:
  forbid: []          # tool names the agent may NEVER call
  # allow: []         # if set, the agent may ONLY call these tools

paths:
  # Folders/files the agent may never read OR write. ~ is expanded.
  forbid:
    - "~/.ssh"
    - "~/.aws"
    - "~/.gnupg"
  forbid_globs:
    - "*.env"
    - "*.pem"
    - "id_rsa"
  # allow: ["~/projects/agent-workspace"]   # confine the agent to here

privacy:
  redact: []          # empty = redact every kind pii-redactor knows about.
                       # narrow it, e.g. [email, phone, ssn, card], to only
                       # redact those specific kinds instead.

log_denials: true     # record every attempt the agent made that was blocked

guards:                    # togglable; set false to drop one.
  pii: true                # self_protection/secret_leak/prompt_injection are
  repetition: true         # NOT listed here — they're kernel-grade and always
  tool_confabulation: false  # on, not settable via policy.
"""


def default_policy_path() -> Path:
    return talaria_home() / POLICY_FILENAME


def load_policy(path: Optional[Path] = None) -> dict:
    path = Path(path) if path else default_policy_path()
    if not path.exists():
        return {}
    doc = yaml.safe_load(path.read_text())
    return doc if isinstance(doc, dict) else {}


def save_policy(policy: dict, path: Optional[Path] = None) -> None:
    """Write a policy dict back to policy.yaml (e.g. from the dashboard).

    This replaces the whole file, so hand-written comments in an edited
    policy.yaml are lost on the first save through this path — a normal
    tradeoff for a GUI-editable config file, but worth being explicit
    about rather than surprising someone the next time they open it in
    an editor."""
    path = Path(path) if path else default_policy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(policy, sort_keys=False, default_flow_style=False))


def build_pipeline(policy: dict, denial_observer=None, vault=None) -> AdapterPipeline:
    """Compile a policy dict into a ready AdapterPipeline.

    ``denial_observer`` (from talaria.denial_log.DenialLog.observer) is
    wired in when policy['log_denials'] is true.

    ``vault`` (a paladin.vault.Vault), when given, populates
    EgressDomainGuard's ref_hosts map from every entry's allowed_hosts
    metadata — this is the ONLY place that wiring happens. Without a
    vault passed in, host-restricted secrets have no domain enforcement
    (there's nothing to restrict against). The Hermes plugin passes its
    open vault in; any other caller of build_pipeline() without one still
    gets every other guard, just not this one — found missing entirely in
    review (the adapter existed and passed its own unit tests, but was
    never actually added to the compiled pipeline).
    """
    guards = policy.get("guards") or {}
    if not isinstance(guards, dict):
        guards = {}
    pipeline = AdapterPipeline()

    # Always-on kernel-grade protections — genuinely cannot be disabled by
    # policy (unconditional adds, no guards.get() check). Found in review:
    # this previously read guards.get("self_protection", True) etc., which
    # meant a policy.yaml with self_protection: false silently dropped it
    # — contradicting this exact promise. A malicious or careless policy
    # edit must not be able to turn these off.
    pipeline.add(KernelSelfProtection())
    pipeline.add(PromptInjectionGuard())
    pipeline.add(SecretLeakGuard())

    if vault is not None:
        try:
            ref_hosts = {
                m["name"]: m["allowed_hosts"]
                for m in vault.iter_meta()
                if m.get("allowed_hosts")
            }
        except Exception:
            ref_hosts = {}
        if ref_hosts:
            pipeline.add(EgressDomainGuard({"ref_hosts": ref_hosts}))

    # Tool allow/deny — the model literally cannot call a forbidden tool.
    tools = policy.get("tools") or {}
    if not isinstance(tools, dict):
        tools = {}
    forbid_tools = list(tools.get("forbid", []))
    allow_tools = list(tools.get("allow", []))
    if forbid_tools or allow_tools:
        pipeline.add(ContextAnchor({
            "forbidden_skills": forbid_tools,
            "allowed_skills": allow_tools,
        }))

    # Path denylist / workspace confinement — reads AND writes.
    paths = policy.get("paths") or {}
    if not isinstance(paths, dict):
        paths = {}
    fp = list(paths.get("forbid", []))
    fg = list(paths.get("forbid_globs", []))
    ap = list(paths.get("allow", []))
    if fp or fg or ap:
        pipeline.add(PathFence({
            "forbidden_paths": fp, "forbidden_globs": fg, "allow_paths": ap,
        }))

    if guards.get("repetition", True):
        pipeline.add(RepetitionBreaker())

    if guards.get("pii", True):
        # An empty/absent redact list means "no specific kinds configured"
        # — that should mean "redact everything" (PiiRedactor's own
        # default when no kinds= is given), not "redact nothing." The
        # previous `and redact` check silently skipped adding this guard
        # at all when redact was [] — which is what the shipped starter
        # policy.yaml sets — so PII redaction was dead on every fresh
        # install despite pii: true being on by default. Found in review.
        redact = policy.get("privacy", {}).get("redact") or []
        kinds_config = {"kinds": list(redact)} if redact else {}
        pipeline.add(PiiRedactor(kinds_config))

    if policy.get("log_denials", True) and denial_observer is not None:
        pipeline.set_observer(denial_observer)

    return pipeline
