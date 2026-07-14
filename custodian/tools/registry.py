"""Tool registry — discovers Hermes skills that declare a custodian-band.

Scans a skills root directory for SKILL.md files, parses YAML frontmatter,
and returns CustodianTool records for any skill that opts in via:

    metadata:
      custodian:
        band: L1          # authority band required to invoke this tool
        cost_usd: 0.00    # estimated cost per call (optional, default 0)
        configured: true  # whether credentials are wired (optional)

The `configured` flag in SKILL.md is a static hint for display purposes.
At runtime, the registry overrides it by checking the actual env vars
required by each tool category. L2/L3/L4 tools run through the kernel's
`decide()` before their execute script is called.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)

# Maps tool name → list of env var names that must ALL be present for the
# tool to be considered configured. If any are missing → configured=False.
_ENV_REQUIREMENTS: dict[str, list[str]] = {
    # Stripe
    "stripe-balance":            ["STRIPE_SECRET_KEY"],
    "stripe-customer-lookup":    ["STRIPE_SECRET_KEY"],
    "stripe-invoice-send":       ["STRIPE_SECRET_KEY"],
    "stripe-subscription-create":["STRIPE_SECRET_KEY"],
    "stripe-subscription-cancel":["STRIPE_SECRET_KEY"],
    "stripe-payout":             ["STRIPE_SECRET_KEY"],
    "stripe-spend":              ["STRIPE_SECRET_KEY"],
    # NVIDIA NIM
    "nim-model-list":            ["NVIDIA_API_KEY"],
    "nim-job-submit":            ["NVIDIA_API_KEY"],
    "nim-job-status":            ["NVIDIA_API_KEY"],
    # Communication
    "email-send":                ["SENDGRID_API_KEY"],
    "sms-send":                  ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"],
    "slack-message":             ["SLACK_BOT_TOKEN"],
    "discord-webhook":           ["DISCORD_WEBHOOK_URL"],
    "push-notification":         ["PUSH_SERVER_KEY"],
    # GitHub (private repos)
    "github-issue-create":       ["GITHUB_TOKEN"],
    "github-pr-list":            ["GITHUB_TOKEN"],
    # HuggingFace / OpenAI
    "huggingface-infer":         ["HF_API_TOKEN"],
    "openai-complete":           ["OPENAI_API_KEY"],
    # Calendar
    "calendar-list":             ["GOOGLE_CALENDAR_TOKEN"],
    "calendar-create":           ["GOOGLE_CALENDAR_TOKEN"],
    "calendar-update":           ["GOOGLE_CALENDAR_TOKEN"],
    "calendar-event-list":       ["GOOGLE_CALENDAR_TOKEN"],
    "calendar-event-create":     ["GOOGLE_CALENDAR_TOKEN"],
    "cron-list":                 ["CUSTODIAN_DB_PATH"],
    "cron-create":               ["CUSTODIAN_DB_PATH"],
    "cron-delete":               ["CUSTODIAN_DB_PATH"],
    # Modal
    "modal-run":                 ["MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"],
    "modal-invoke":              ["MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"],
    "modal-deploy":              ["MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"],
    # Cloud Storage (S3-compatible)
    "s3-list":                   ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
    "s3-get":                    ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
    "s3-put":                    ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
    "s3-delete":                 ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
    # Database
    "redis-get":                 ["REDIS_URL"],
    "redis-set":                 ["REDIS_URL"],
    "redis-delete":              ["REDIS_URL"],
    "postgres-query":            ["POSTGRES_URL"],
    "mysql-query":               ["MYSQL_URL"],
    "mongodb-find":              ["MONGODB_URL"],
    # Additional GitHub
    "github-commit-list":        ["GITHUB_TOKEN"],
    "github-file-read":          ["GITHUB_TOKEN"],
    "github-release-list":       ["GITHUB_TOKEN"],
    "github-release-create":     ["GITHUB_TOKEN"],
    "github-issue-list":         ["GITHUB_TOKEN"],
    "github-repo-list":          ["GITHUB_TOKEN"],
    "github-comment":            ["GITHUB_TOKEN"],
    "slack-channel-list":        ["SLACK_BOT_TOKEN"],
    "modal-function-list":       ["MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"],
    # AI Inference
    "openai-chat":               ["OPENAI_API_KEY"],
    "anthropic-chat":            ["ANTHROPIC_API_KEY"],
    "cohere-embed":              ["COHERE_API_KEY"],
    "replicate-run":             ["REPLICATE_API_TOKEN"],
    "together-infer":            ["TOGETHER_API_KEY"],
    # Calendar
    "calendar-list":             ["GOOGLE_CALENDAR_TOKEN"],
    "calendar-create":           ["GOOGLE_CALENDAR_TOKEN"],
    "calendar-update":           ["GOOGLE_CALENDAR_TOKEN"],
    "calendar-delete":           ["GOOGLE_CALENDAR_TOKEN"],
    # Additional Stripe
    "stripe-charge-list":        ["STRIPE_SECRET_KEY"],
    "stripe-customer-create":    ["STRIPE_SECRET_KEY"],
    "stripe-price-list":         ["STRIPE_SECRET_KEY"],
    "stripe-refund-list":        ["STRIPE_SECRET_KEY"],
    # Alerts
    "pagerduty-alert":           ["PAGERDUTY_API_KEY"],
    "twilio-voice-call":         ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"],
    "telegram-send":             ["TELEGRAM_BOT_TOKEN"],
}


def _is_configured(name: str, skill_meta_flag: bool,
                   env: Optional[dict] = None) -> bool:
    """Return True if the tool's required env vars are all present.

    `env` overrides os.environ when given — a Warden-injected environment
    counts as configured even though the agent's own env has no keys.
    """
    reqs = _ENV_REQUIREMENTS.get(name)
    if reqs is None:
        return skill_meta_flag  # no known requirement → trust SKILL.md
    source = env if env is not None else os.environ
    return all(source.get(v) for v in reqs)


@dataclass
class CustodianTool:
    name: str
    description: str
    band: str               # L0–L4
    cost_usd: float = 0.0
    configured: bool = True  # False = stub, credentials not set
    skill_dir: Optional[Path] = None
    tags: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    execute_script: Optional[Path] = None  # scripts/execute.py if present

    @property
    def band_label(self) -> str:
        labels = {
            "L0": "L0 · read-only",
            "L1": "L1 · free / trivial",
            "L2": "L2 · autonomous up to cap",
            "L3": "L3 · always escalates",
            "L4": "L4 · unlimited / human required",
        }
        return labels.get(self.band, self.band)

    def _kernel_decide(self) -> Optional[dict]:
        """Consult the kernel policy engine for L2+ tools.

        Returns None if the kernel state isn't available (e.g. no workspace
        initialized) — callers treat None as "proceed" so tools aren't broken
        in environments without a full Custodian workspace.

        Returns a dict with keys: verdict, reason, band.
        """
        try:
            from custodian.policy import load_policy
            from custodian.policy.evaluator import decide
            from custodian.types import AuthorityState, Band, KillSwitchState, SpendRequest

            # Load or default authority state
            state_path = Path.home() / ".custodian" / "authority.json"
            if state_path.exists():
                state = AuthorityState.from_dict(json.loads(state_path.read_text()))
            else:
                state = AuthorityState(
                    band=Band.L2, per_action_cap=250.0, session_cap=1000.0
                )

            # Kill switch — fail closed on corruption (same policy as govern.py)
            ks_path = Path.home() / ".custodian" / "kill_switch.json"
            killed = False
            if ks_path.exists():
                try:
                    ks_data = json.loads(ks_path.read_text())
                    killed = bool(ks_data.get("killed", False))
                except Exception:
                    killed = True  # corrupted kill switch file = treat as killed

            # Policy: workspace first, then default preset
            policy_path = Path.home() / ".custodian" / "policy.yaml"
            if not policy_path.exists():
                here = Path(__file__).resolve().parent.parent
                policy_path = here / "policy" / "presets" / "default.yaml"
            policy = load_policy(policy_path)

            request = SpendRequest(
                amount=self.cost_usd,
                description=f"tool:{self.name}",
            )
            decision = decide(request, state, policy, skill=self.name, killed=killed)
            return {
                "verdict": decision.verdict.value,
                "reason": decision.reason,
                "band": decision.band.value,
            }
        except Exception:
            return None  # kernel unavailable → allow through

    def invoke(self, _env: Optional[dict] = None, **kwargs) -> dict:
        """Run the skill's execute.py script with kwargs as --key value args.

        For L2/L3/L4 tools the kernel's decide() is called first. If it
        returns anything other than AUTONOMOUS the tool does not execute.

        `_env`, when given, is the complete environment for the script
        subprocess (Warden egress injection: the credential exists in the
        skill's process, never the agent's). Defaults to inheriting the
        parent environment, matching the old behavior.

        Returns dict with at minimum {"ok": bool}.
        """
        from custodian import bus as _event_bus

        if not _is_configured(self.name, self.configured, env=_env):
            return {
                "ok": False,
                "stub": True,
                "tool": self.name,
                "message": (
                    f"{self.name} is not configured — "
                    f"set: {', '.join(_ENV_REQUIREMENTS.get(self.name, ['required env vars']))}"
                ),
                "kwargs": kwargs,
            }

        # Kernel gate for spending bands
        decision = None
        if self.band in ("L2", "L3", "L4"):
            decision = self._kernel_decide()
            if decision is not None and decision["verdict"] != "autonomous":
                payload = {
                    "tool": self.name,
                    "band": self.band,
                    "verdict": decision["verdict"],
                    "reason": decision["reason"],
                    "cost_usd": self.cost_usd,
                }
                if decision["verdict"] == "denied":
                    _event_bus.emit("kernel_denied", payload)
                else:
                    _event_bus.emit("escalation_required", payload)
                return {
                    "ok": False,
                    "kernel_escalation": True,
                    "verdict": decision["verdict"],
                    "reason": decision["reason"],
                    "tool": self.name,
                    "band": self.band,
                    "cost_usd": self.cost_usd,
                    "message": (
                        f"Kernel requires escalation for {self.name} "
                        f"(band {self.band}): {decision['reason']}"
                    ),
                }

        if not self.execute_script or not self.execute_script.exists():
            return {
                "ok": False,
                "error": f"no execute script found for {self.name}",
                "tool": self.name,
            }

        _event_bus.emit("pre_execute", {"tool": self.name, "band": self.band, "kwargs": kwargs})

        cmd = ["python3", str(self.execute_script)]
        for k, v in kwargs.items():
            cmd += [f"--{k.replace('_', '-')}", str(v)]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
                cwd=str(self.skill_dir) if self.skill_dir else None,
                env=_env,
            )
            try:
                parsed = json.loads(result.stdout.strip())
            except (json.JSONDecodeError, ValueError):
                parsed = {"ok": result.returncode == 0, "output": result.stdout.strip()}
            parsed["tool"] = self.name
            if result.stderr.strip():
                parsed.setdefault("stderr", result.stderr.strip())
            _event_bus.emit("post_execute", {
                "tool": self.name,
                "band": self.band,
                "ok": parsed.get("ok", False),
                "result": parsed,
            })
            return parsed
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "timeout", "tool": self.name}
        except Exception as e:
            return {"ok": False, "error": str(e), "tool": self.name}


class ToolRegistry:
    """Discover and index all Custodian-governed skills under a root dir."""

    def __init__(self, skills_root: Path):
        self.skills_root = Path(skills_root)
        self._tools: dict[str, CustodianTool] = {}
        self._loaded = False

    def _parse_frontmatter(self, text: str) -> dict:
        m = _FRONTMATTER.match(text.strip())
        if not m:
            return {}
        try:
            return yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            return {}

    def load(self) -> "ToolRegistry":
        """Scan skills_root for SKILL.md files with custodian metadata."""
        self._tools = {}
        for skill_md in self.skills_root.rglob("SKILL.md"):
            try:
                text = skill_md.read_text()
                meta = self._parse_frontmatter(text)
                custodian_meta = (meta.get("metadata") or {}).get("custodian") or {}
                band = custodian_meta.get("band")
                if not band:
                    continue  # not a governed skill
                name = meta.get("name") or skill_md.parent.name
                static_configured = bool(custodian_meta.get("configured", True))
                execute = skill_md.parent / "scripts" / "execute.py"
                tool = CustodianTool(
                    name=name,
                    description=meta.get("description", ""),
                    band=str(band),
                    cost_usd=float(custodian_meta.get("cost_usd", 0.0)),
                    configured=_is_configured(name, static_configured),
                    skill_dir=skill_md.parent,
                    tags=list(meta.get("metadata", {}).get("hermes", {}).get("tags", [])),
                    version=str(meta.get("version", "1.0.0")),
                    execute_script=execute if execute.exists() else None,
                )
                self._tools[name] = tool
            except Exception:
                continue
        self._loaded = True
        return self

    def all(self) -> list[CustodianTool]:
        if not self._loaded:
            self.load()
        return sorted(self._tools.values(), key=lambda t: (t.band, t.name))

    def get(self, name: str) -> Optional[CustodianTool]:
        if not self._loaded:
            self.load()
        return self._tools.get(name)

    def by_band(self, band: str) -> list[CustodianTool]:
        return [t for t in self.all() if t.band == band]

    def configured_only(self) -> list[CustodianTool]:
        return [t for t in self.all() if t.configured]

    def summary(self) -> dict:
        tools = self.all()
        by_band: dict[str, int] = {}
        for t in tools:
            by_band[t.band] = by_band.get(t.band, 0) + 1
        return {
            "total": len(tools),
            "configured": sum(1 for t in tools if t.configured),
            "stubs": sum(1 for t in tools if not t.configured),
            "by_band": by_band,
        }

    def run(self, name: str, _env: Optional[dict] = None, **kwargs) -> dict:
        """Convenience: look up a tool by name and invoke it.

        Returns a structured error dict (never raises) when the tool is
        unknown so callers can branch on `ok` without try/except plumbing.
        `_env` is forwarded to CustodianTool.invoke (Warden egress).
        """
        tool = self.get(name)
        if tool is None:
            return {
                "ok": False,
                "error": f"tool not found: {name}",
                "tool": name,
            }
        return tool.invoke(_env=_env, **kwargs)


def default_registry() -> ToolRegistry:
    """Return registry pointed at the canonical skills/ directory.

    Search order:
    1. Walk up from this file looking for skills/ (works in dev/cloned repo)
    2. Fall back to bundled_skills/ inside the installed package
    3. Fall back to cwd skills/ (legacy)
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "skills"
        if candidate.is_dir():
            return ToolRegistry(candidate)
    # Installed via pip — use bundled skills shipped with the package
    # __file__ = .../site-packages/custodian/tools/registry.py
    # parent.parent = .../site-packages/custodian/
    bundled = Path(__file__).resolve().parent.parent / "bundled_skills"
    if bundled.is_dir():
        return ToolRegistry(bundled)
    return ToolRegistry(Path("skills"))
