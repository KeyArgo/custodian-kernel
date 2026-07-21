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
import sys
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

_SAFE_RUNTIME_ENV = frozenset({
    "PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR",
    "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "PYTHONUTF8",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
    "CUSTODIAN_KV_PATH", "CUSTODIAN_QUEUE_PATH", "CUSTODIAN_CRONS_PATH",
    "CUSTODIAN_DB_PATH", "CUSTODIAN_ALLOWED_WRITE_DIR",
    "CUSTODIAN_STRIPE_MOCK", "HERMES_OPERATOR_PHONE",
    "DOCKER_EXEC_CONFIGURED",
})


def _tool_environment(name: str, supplied: Optional[dict] = None) -> dict:
    """Build a least-privilege environment for one tool subprocess.

    A supplied environment is already the complete, trusted environment
    assembled by the Paladin bridge, including custom secret references whose
    names cannot be known by this registry.  Never merge it with ``os.environ``.
    """
    if supplied is not None:
        return {str(key): str(value) for key, value in supplied.items()
                if value is not None}
    source = os.environ
    allowed = _SAFE_RUNTIME_ENV | frozenset(_ENV_REQUIREMENTS.get(name, []))
    return {key: str(source[key]) for key in allowed if source.get(key) is not None}


def _redact_credential_values(text: str, environment: dict, name: str) -> str:
    """Remove known credential values before child output reaches the caller."""
    redacted = text
    for key in _ENV_REQUIREMENTS.get(name, []):
        value = environment.get(key)
        if value and len(str(value)) >= 4:
            redacted = redacted.replace(str(value), "[REDACTED:credential]")
    return redacted


def _is_configured(name: str, skill_meta_flag: bool,
                   env: Optional[dict] = None) -> bool:
    """Return True if the tool's required env vars are all present.

    `env` overrides os.environ when given — a Paladin-injected environment
    counts as configured even though the agent's own env has no keys.
    """
    reqs = _ENV_REQUIREMENTS.get(name)
    if reqs is None:
        return skill_meta_flag  # no known requirement → trust SKILL.md
    source = env if env is not None else os.environ
    return all(source.get(v) for v in reqs)


def _state_dir() -> Path:
    """Resolve the Custodian state directory.

    Honors CUSTODIAN_STATE_DIR like the rest of the kernel (policy/enforcer.py,
    codex_guard/mcp_server.py) instead of hardcoding ~/.custodian -- this file
    used to hardcode it in three places, silently diverging from a workspace
    that set the env var.
    """
    configured = os.environ.get("CUSTODIAN_STATE_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".custodian"


def _ledger_write(ledger, **kw) -> None:
    """Never let a ledger write failure block a tool call -- same resilience
    posture as cmd_request.py's identical helper."""
    try:
        from custodian.universal_ledger import LedgerEvent
        ledger.append(LedgerEvent(**kw))
    except Exception as e:
        print(f"warning: failed to write ledger event: {e}", file=sys.stderr)


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
    # Opt-in per-tool network destination allowlist (see custodian/egress_proxy.py).
    # Empty = unrestricted, today's behavior -- a tool only gets enforcement
    # once its SKILL.md declares real destinations.
    allowed_hosts: frozenset = field(default_factory=frozenset)

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

    def _kernel_decide(self, amount: Optional[float] = None) -> Optional[dict]:
        """Consult the kernel policy engine for L2+ tools.

        `amount` is the real requested spend for this call — the caller's
        `kwargs.get("amount", self.cost_usd)`, same precedence already used
        by spend_sentinel.py/context_anchor.py. This used to always build
        the SpendRequest from `self.cost_usd` (the SKILL.md-declared static
        default, 0.0 for any tool whose real cost is per-call — the normal
        shape for a spend tool) and never looked at the caller's actual
        amount at all, so the L2/L3/L4 band-cap gate always decided against
        $0 regardless of what was really requested. Verified live: a
        $999,999.99 call to a fresh L2 tool sailed through as autonomous
        with a $2.00 default per-action cap. Found in review.

        Thin wrapper over custodian.policy.gate.kernel_gate, which every
        other governed call path (the delegated executor, the inference
        router) also uses -- kept as one implementation so a fix here can't
        silently fail to reach the others.
        """
        from custodian.policy.gate import kernel_gate
        return kernel_gate(
            self.cost_usd if amount is None else amount,
            action=f"tool:{self.name}", state_dir=_state_dir(),
            fallback_band=self.band,
        )

    def invoke(self, _env: Optional[dict] = None, requester: str = "tool-registry",
               **kwargs) -> dict:
        """Run the skill's execute.py script with kwargs as --key value args.

        For L2/L3/L4 tools the kernel's decide() is called first. If it
        returns anything other than AUTONOMOUS the tool does not execute.

        `_env`, when given, is the complete trusted environment for the script
        subprocess (Paladin egress injection: the credential exists in the
        skill's process, never the agent's). Without it, only runtime plumbing
        and the exact declared requirements for this tool are inherited.

        `requester` identifies who's calling for the universal ledger (e.g.
        talaria's HermesBridge passes ``session:<capsule.session_id>``);
        callers that don't pass one are recorded under a generic label.

        Returns dict with at minimum {"ok": bool}.

        If CUSTODIAN_EXECUTOR_SOCKET is set, this delegates entirely to a
        separate executor process over that socket instead of deciding and
        executing in-process (see custodian/executor/) -- the strongest
        guarantee: this process never runs the skill script itself, so a
        fully compromised agent process cannot bypass the kernel's decision
        by simply not calling it. Opt-in today, not the default, because it
        requires an operator to have started `custodian executor start`
        separately; the in-process path below is unchanged for callers that
        don't configure it.
        """
        executor_socket = os.environ.get("CUSTODIAN_EXECUTOR_SOCKET")
        if executor_socket:
            from custodian.executor.client import ExecutorClient, ExecutorUnavailableError
            client = ExecutorClient(Path(executor_socket))
            try:
                return client.propose(
                    self.name, kwargs, requester=requester,
                    workspace=str(self.skill_dir) if self.skill_dir else "",
                    env=_env,
                )
            except ExecutorUnavailableError as e:
                return {"ok": False, "error": str(e), "tool": self.name}

        from custodian import bus as _event_bus
        from custodian.universal_ledger import UniversalLedger
        import uuid as _uuid

        ledger = UniversalLedger(_state_dir() / "ledger.db")
        correlation_id = _uuid.uuid4().hex
        try:
            real_amount = float(kwargs.get("amount", self.cost_usd) or 0)
        except (TypeError, ValueError):
            real_amount = self.cost_usd

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

        _ledger_write(
            ledger, correlation_id=correlation_id, requester=requester,
            provider="custodian", action=self.name, lifecycle_event="proposed",
            band=self.band, amount=real_amount, currency="USD",
        )

        # Kernel gate for spending bands
        decision = None
        if self.band in ("L2", "L3", "L4"):
            decision = self._kernel_decide(real_amount)
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
                _ledger_write(
                    ledger, correlation_id=correlation_id, requester=requester,
                    provider="custodian", action=self.name, lifecycle_event="decided",
                    verdict=decision["verdict"], band=self.band, amount=real_amount,
                    currency="USD", metadata={"reason": decision["reason"][:200]},
                )
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
            if decision is not None:
                _ledger_write(
                    ledger, correlation_id=correlation_id, requester=requester,
                    provider="custodian", action=self.name, lifecycle_event="decided",
                    verdict=decision["verdict"], band=self.band, amount=real_amount,
                    currency="USD",
                )

        result = self._run_script(kwargs, _env)
        error_reason = result.get("error") if not result.get("ok") else None
        _ledger_write(
            ledger, correlation_id=correlation_id, requester=requester,
            provider="custodian", action=self.name,
            lifecycle_event="executed" if result.get("ok") else "failed",
            band=self.band, amount=real_amount, currency="USD",
            metadata={"reason": error_reason[:200]} if error_reason else {},
        )
        return result

    def _run_script(self, kwargs: dict, _env: Optional[dict] = None) -> dict:
        """Actually run the skill's execute.py script, sandboxed.

        No kernel gating here at all -- this is the low-level execution
        mechanics shared by invoke() (which has already gated on
        _kernel_decide) and custodian.executor.service's delegated executor
        (which gates independently, in a separate process, before ever
        calling this). Kept as one method rather than duplicated in both
        places: a sandboxing or redaction fix applied to only one copy is
        exactly the kind of subtle two-tier bug this codebase has already
        been adversarially reviewed for elsewhere this session.
        """
        from custodian import bus as _event_bus

        if not self.execute_script or not self.execute_script.exists():
            return {
                "ok": False,
                "error": f"no execute script found for {self.name}",
                "tool": self.name,
            }

        from custodian.types import sanitize_dict
        _event_bus.emit("pre_execute", {
            "tool": self.name, "band": self.band,
            "kwargs": sanitize_dict(kwargs),
        })

        # sys.executable, not "python3": the literal is not on PATH on Windows
        # (where it hits the App Execution Alias and prints "Python was not
        # found; install from the Microsoft Store" to stderr, so every tool
        # invocation returned ok=False), and even on POSIX it can resolve to a
        # different interpreter than the one running Custodian — one without
        # the skill's dependencies installed. sys.executable is the venv's own
        # Python by construction.
        cmd = [sys.executable, str(self.execute_script)]
        for k, v in kwargs.items():
            cmd += [f"--{k.replace('_', '-')}", str(v)]

        from custodian.exceptions import ToolSandboxUnavailableError
        from custodian.sandbox import require_sandboxed_argv
        rw_dirs = [str(_state_dir())]
        if self.skill_dir:
            rw_dirs.append(str(self.skill_dir))
        try:
            argv = require_sandboxed_argv(
                cmd, rw_dirs=rw_dirs,
                allow_unsandboxed=os.environ.get("CUSTODIAN_ALLOW_UNSANDBOXED_TOOLS") == "1",
            )
        except ToolSandboxUnavailableError as e:
            return {"ok": False, "error": str(e), "tool": self.name}

        egress_proxy = None
        try:
            tool_env = _tool_environment(self.name, _env)
            # Opt-in per-tool destination allowlist (see
            # custodian/egress_proxy.py for exactly what this does and does
            # not guarantee -- it redirects cooperative HTTP clients, it
            # does not isolate the network namespace). No-op for the ~all
            # existing tools that haven't declared allowed_hosts yet.
            if self.allowed_hosts:
                from custodian.egress_proxy import EgressProxy
                egress_proxy = EgressProxy(allowed_hosts=self.allowed_hosts)
                egress_proxy.start()
                tool_env = {**tool_env, **egress_proxy.proxy_env()}

            result = subprocess.run(
                argv, capture_output=True, text=True, timeout=30,
                cwd=str(self.skill_dir) if self.skill_dir else None,
                env=tool_env,
            )
            stdout = _redact_credential_values(result.stdout, tool_env, self.name)
            stderr = _redact_credential_values(result.stderr, tool_env, self.name)
            try:
                parsed = json.loads(stdout.strip())
            except (json.JSONDecodeError, ValueError):
                parsed = {"ok": result.returncode == 0, "output": stdout.strip()}
            parsed["tool"] = self.name
            if stderr.strip():
                parsed.setdefault("stderr", stderr.strip())
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
        finally:
            if egress_proxy is not None:
                egress_proxy.stop()


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
                    allowed_hosts=frozenset(custodian_meta.get("allowed_hosts") or ()),
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

    def run(self, name: str, _env: Optional[dict] = None,
            requester: str = "tool-registry", **kwargs) -> dict:
        """Convenience: look up a tool by name and invoke it.

        Returns a structured error dict (never raises) when the tool is
        unknown so callers can branch on `ok` without try/except plumbing.
        `_env` is forwarded to CustodianTool.invoke (Paladin egress).
        `requester` is forwarded to the universal ledger.
        """
        tool = self.get(name)
        if tool is None:
            return {
                "ok": False,
                "error": f"tool not found: {name}",
                "tool": name,
            }
        return tool.invoke(_env=_env, requester=requester, **kwargs)


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
