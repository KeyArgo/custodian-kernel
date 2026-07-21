"""Refund-triage reasoning panel API for the dashboard.

Serves the guided tour and, per case, the full triage result: what the AI
agent produced (the Envelope), how every claim checked out against ground
truth, the deterministic disposition (which may OVERRIDE the agent), and the
kernel's authority outcome. Plus the policy-diff replay that flips a decision
by changing one business rule.

Two envelope sources, always labelled honestly:
  - captured (default): replays the envelope stored with each corpus case, so
    the page is reproducible and works with no API key.
  - live (?live=1): calls the real Nemotron model to generate the envelope
    fresh from the raw customer email -- requires the dashboard's nvidia.env.
"""
import datetime
import json
import math
import os
import time
from collections import defaultdict, deque
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, request

from custodian.packs.agent import EnvelopeParseError
try:
    from custodian.inference.router import NemoClawRouter
    def _make_client():
        # Wire both OpenRouter and NIM keys so the primary (OpenRouter)
        # actually gets used. Without openrouter_key_file the router
        # silently skips OpenRouter (it has no key) and falls through to
        # NIM, which times out and triggers the no-AI fallback path.
        # timeout=25 (was 10, live bug 2026-07-05): this reasoning model can
        # legitimately take longer than 10s to think through a full claims
        # envelope; nemotron_chat.py already settled on 25s for the same
        # model on a lighter task. 10s was causing spurious "Backend
        # unavailable or timed out" failures on requests that would have
        # succeeded given a few more seconds.
        return NemoClawRouter(
            timeout=25,
            nvidia_api_key_file=_NVIDIA_SECRET,
            openrouter_key_file=_KEYS_ENV,
        )
except ImportError:
    from custodian.packs.agent import NvidiaNemotronClient
    def _make_client():
        return NvidiaNemotronClient(secret_file=_NVIDIA_SECRET)
from custodian.packs.base import Envelope
from custodian.packs.engine import replay_with_policy_change, triage
from custodian.packs.narration import TOUR
from custodian.packs.refunds.extractor import extract_envelope as refunds_extract_envelope
from custodian.packs.purchasing.extractor import extract_envelope as purchasing_extract_envelope
from custodian.packs.cloud.extractor import extract_envelope as cloud_extract_envelope
from custodian.packs.registry import available, get_pack

# Per-pack extractor dispatch + sandbox builders. Each pack has its own
# fixed ground-truth fixture so live Nemotron claims can be checked against
# the same ledger the corpus cases use, and the lie-catch stays reproducible.
_EXTRACTORS = {
    "refunds": refunds_extract_envelope,
    "purchasing": purchasing_extract_envelope,
    "cloud": cloud_extract_envelope,
}

# Sandbox fixtures for /triage/custom. These are KNOWN-GOOD ground truth so
# a visitor's free-form text is checked against real data, never made up.
#   refunds     -> ord_6006 / cus_marcus:  delivered, no defect, 19d old
#   purchasing  -> po_6010 / vnd_brightparts:  $75 authorized, vendor approved, PO open
#   cloud       -> nim_nemotron_super / nvidia_nim:  $1.20/hr NIM endpoint, approved
_CUSTOM_SANDBOX = {
    "refunds": {
        "case_id": "visitor-custom",
        "customer_id": "cus_marcus",
        "order_id": "ord_6006",
        "amount": 80.0,
        "customer_email_field": None,  # set from payload at call time
        "sandbox_label": "ord_6006 · $80 · delivered · no defect · 19 days old",
        "placeholder": "Write any refund excuse here — try lying…",
        "action": "refund.create",
    },
    "purchasing": {
        "case_id": "visitor-custom",
        "customer_id": "vnd_brightparts",
        "order_id": "po_6010",
        "amount": 150.0,
        "customer_email_field": "customer_email",
        "sandbox_label": "po_6010 · $150 authorized · BrightParts LLC · PO open",
        "placeholder": "Write a vendor invoice message — try overbilling the PO…",
        "action": "invoice.pay",
    },
    "cloud": {
        "case_id": "visitor-custom",
        "customer_id": "nvidia_nim",
        "order_id": "nim_nemotron_super",
        "amount": 1.20,
        "customer_email_field": "customer_email",
        "sandbox_label": "nim_nemotron_super · $1.20/hr · NVIDIA NIM (sponsor) · Nemotron-3-Super-120B",
        "placeholder": "Write a compute provisioning request — try under-reporting the cost…",
        "action": "compute.provision",
    },
}
from custodian.policy.loader import load_policy
from custodian.types import AuthorityState, Band

bp = Blueprint("triage", __name__)

_NVIDIA_SECRET = Path(__file__).resolve().parent.parent / "secrets" / "nvidia.env"
_KEYS_ENV = Path(__file__).resolve().parent.parent / "secrets" / "keys.env"

_HERE = Path(__file__).resolve().parent.parent

# Independent rate-limit bucket from the other public dashboard endpoints --
# a flood on one shouldn't silently starve another's budget for the same
# visitor. Same pattern as nemotron_chat.py/playground.py/stripe_webhook.py.
# Lower ceiling than those: /case/<id> and /custom can each trigger a real
# billed NIM/Modal call (case_by_id's cloud auto-provision path) or a real
# LLM generation call (custom, run?live=1), not a free local decision.
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_REQUESTS = 10
_request_log: dict = defaultdict(deque)


def _client_ip() -> str:
    """CF-Connecting-IP is client-supplied input -- trusting it
    unconditionally lets a client rotate the header value per request to
    get a fresh rate-limit bucket every time. Only honored when the
    operator has explicitly confirmed a trusted proxy terminates every
    path to this process (TRUSTED_PROXY_HEADER=CF-Connecting-IP); otherwise
    falls back to request.remote_addr, which a client cannot forge. Same
    fix applied to nemotron_chat.py/playground.py/stripe_webhook.py."""
    if os.environ.get("TRUSTED_PROXY_HEADER") == "CF-Connecting-IP":
        return request.headers.get("CF-Connecting-IP") or request.remote_addr or "unknown"
    return request.remote_addr or "unknown"


def rate_limited(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        ip = _client_ip()
        now = time.time()
        log = _request_log[ip]
        while log and now - log[0] > _RATE_LIMIT_WINDOW_SECONDS:
            log.popleft()
        if len(log) >= _RATE_LIMIT_MAX_REQUESTS:
            return jsonify({
                "error": f"Rate limit exceeded -- max {_RATE_LIMIT_MAX_REQUESTS} requests per "
                         f"{_RATE_LIMIT_WINDOW_SECONDS}s per IP on this demo endpoint.",
            }), 429
        log.append(now)
        return f(*args, **kwargs)
    return wrapper


def _load_keys_env() -> dict:
    """Load secrets/keys.env into a dict without touching os.environ."""
    out = {}
    if _KEYS_ENV.exists():
        for line in _KEYS_ENV.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


from custodian.adapters.nemoclaw import NemoClawExecutor

SANDBOX_NAME = os.environ.get("HERMES_SANDBOX_NAME", "argonaut-money-demo")
SKILL_STATE_DIR = "/sandbox/.hermes/skills/payments/stripe-spend/state"
_AUDIT_LOG_PATH = f"{SKILL_STATE_DIR}/audit_log.jsonl"

_sandbox = NemoClawExecutor(
    sandbox_name=SANDBOX_NAME,
    fallback_binary_path="/home/argonaut/.local/bin/nemohermes",
)


def _log_spend(case_id: str, provider: str, amount: float, description: str, execution: dict | None = None) -> None:
    """Append a spend event to the audit log so the P&L dashboard reflects it.

    Writes through the same NemoClawExecutor/nemohermes-exec path
    dashboard/api/operator.py and hermes.py already use for the real audit
    log, not a local Path.open("a") -- a local write landed in this
    process's own filesystem namespace, invisible to hermes.py's
    _read_remote_file()/get_audit_log() (which read INSIDE the sandbox
    container), so spend triggered via this triage demo silently never
    appeared in the publicly-displayed P&L/audit totals despite the
    misleading old comment claiming it was "the same file the P&L endpoint
    reads."
    """
    event = {
        "event": "spend",
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "case_id": case_id,
        "provider": provider,
        "amount": amount,
        "description": description,
        "governed_by": "custodian-kernel",
        "authority": "AUTONOMOUS",
    }
    if execution:
        event["execution"] = execution
    try:
        _sandbox.write_file(_AUDIT_LOG_PATH, json.dumps(event) + "\n", append=True)
    except Exception:
        pass  # best-effort logging; must never break the triage response itself


def _execute_provision(case_id: str, data: dict, amount: float) -> dict:
    """Best-effort: try Modal → NIM → stub. Returns execution result."""
    keys = _load_keys_env()
    provider = data.get("envelope", {}).get("customer_id", "unknown")

    # Modal path
    if "modal" in provider.lower() and keys.get("MODAL_TOKEN_ID"):
        try:
            import subprocess, sys
            env = os.environ.copy()
            env["MODAL_TOKEN_ID"] = keys["MODAL_TOKEN_ID"]
            env["MODAL_TOKEN_SECRET"] = keys["MODAL_TOKEN_SECRET"]
            env["MODAL_PROFILE"] = keys.get("MODAL_PROFILE", "inovinlabs")
            result = subprocess.run(
                [sys.executable, "-c",
                 "import modal; f = modal.Function.from_name('custodian-benchmark', 'benchmark');"
                 " r = f.remote(1.0); print(__import__('json').dumps(r))"],
                capture_output=True, text=True, timeout=30, env=env,
            )
            if result.returncode == 0:
                return {"provider": "modal", "result": json.loads(result.stdout.strip()), "billed": amount}
        except Exception as e:
            pass  # fall through to NIM

    # NIM path (all cloud cases can use NIM as the execution proof)
    # The NVIDIA_API_KEY key was already loaded into keys dict above; we
    # write it into a file so NemoClawRouter can read it without mutating
    # os.environ, which is not thread-safe in a multi-worker Flask deploy.
    nvidia_key = keys.get("NVIDIA_API_KEY") or os.environ.get("NVIDIA_API_KEY")
    if nvidia_key:
        try:
            from custodian.inference.router import NemoClawRouter
            _NIM_KEY_PATH = Path(__file__).resolve().parents[2] / "skills" / "payments" / "stripe-spend" / "state" / "nvidia_nim_key.env"
            _NIM_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
            # Path.write_text() creates the file with the process's default
            # umask-derived permissions (typically 0644 -- world-readable) --
            # a live API key briefly sat world-readable on a host this
            # project's own docs describe as shared with other real
            # services. os.open's mode argument only applies when O_CREAT
            # actually creates a new inode -- if a stale file from a prior
            # hard-killed run (SIGKILL/OOM bypass the surrounding finally:
            # unlink()) already exists with looser permissions, os.open
            # silently reuses them. os.chmod() after opening closes that
            # gap regardless of whether the file was just created or already
            # existed.
            fd = os.open(_NIM_KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            if os.name != "nt":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(f"NVIDIA_API_KEY={nvidia_key}\n")
            try:
                r = NemoClawRouter(timeout=15, nvidia_api_key_file=_NIM_KEY_PATH)
                response = r.complete(
                    "You are a terse compute orchestrator.",
                    f"Job {case_id} approved. Report: provider={provider}, cost=${amount:.2f}/hr, status=provisioned.",
                )
                _NIM_KEY_PATH.unlink(missing_ok=True)
                return {"provider": "nvidia-nim", "endpoint": r.name, "response": response[:120], "billed": amount}
            finally:
                _NIM_KEY_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    return {"provider": provider, "stub": True, "billed": amount}

# Generous state -- the kernel selects the band from the pack's policy, not from
# this state's band; this just proves a verdict isn't an artifact of a tiny budget.
_STATE = lambda: AuthorityState(band=Band.L3, per_action_cap=50.0, session_cap=1000.0)

_DEFAULT_PACK = "refunds"


def _pack_name() -> str:
    payload = request.get_json(force=True, silent=True) or {}
    return (request.args.get("pack") or payload.get("pack") or _DEFAULT_PACK).strip()


def _resolve_pack(name: str):
    """Return (pack, kernel_policy, corpus_dir) or (None, None, None) if unknown."""
    try:
        entry = get_pack(name)
    except KeyError:
        return None, None, None
    return entry.factory(), load_policy(entry.kernel_policy), entry.corpus_dir


def _load_case(corpus_dir: Path, case_id: str) -> dict:
    # case_id reaches here from a query-string/JSON-body value (the URL-
    # segment route /case/<case_id> is separately protected by Werkzeug's
    # default converter rejecting encoded slashes) with no boundary check --
    # a value like "../account_ledger" escaped corpus_dir entirely, giving
    # a file-existence oracle for arbitrary relative paths and full content
    # disclosure of any reachable *.json file that happens to parse.
    if "/" in case_id or "\\" in case_id or ".." in case_id:
        return None
    try:
        # A null byte or an oversized case_id makes realpath/resolve()
        # itself raise (ValueError/OSError) instead of just failing to
        # match a file -- caught here so a malformed case_id fails closed
        # to "no such case" (404) rather than an uncaught 500.
        path = (corpus_dir / f"{case_id}.json").resolve()
        if not path.is_relative_to(corpus_dir.resolve()):
            return None
        if not path.exists():
            return None
        return json.loads(path.read_text())
    except (ValueError, OSError):
        return None


def _case_input(data: dict) -> dict:
    env = data["envelope"]
    return {
        "case_id": env["case_id"],
        "customer_id": env["customer_id"],
        "order_id": env["order_id"],
        "amount": env["amount"],
        "customer_email": data.get("customer_email", ""),
    }


def _envelope_for(data: dict, live: bool, pack_name: str = "refunds"):
    """Return (Envelope, source_label). Falls back to captured if live fails so
    a judge never hits a dead demo, but the label always tells the truth."""
    if live and _NVIDIA_SECRET.exists():
        client = _make_client()
        extractor = _EXTRACTORS.get(pack_name, refunds_extract_envelope)
        try:
            return extractor(_case_input(data), client), client.name
        except (EnvelopeParseError, OSError, KeyError, RuntimeError) as e:
            # fall through to captured, but say so
            return Envelope.from_dict(data["envelope"]), f"captured (live call failed: {e})"
    return Envelope.from_dict(data["envelope"]), "captured agent output"


@bp.route("/tour", methods=["GET"])
def tour():
    """The guided tour ordering: most-compelling-first, weeds-last."""
    return jsonify({"tour": TOUR, "packs": available()})


@bp.route("/case/<case_id>", methods=["GET"])
@rate_limited
def case_by_id(case_id: str):
    """Load and run a single corpus case by ID — used by the try-it-yourself panels."""
    name = _pack_name()
    pack, kernel_policy, corpus_dir = _resolve_pack(name)
    if pack is None:
        return jsonify({"error": f"unknown pack: {name}", "packs": available()}), 404
    data = _load_case(corpus_dir, case_id)
    if not data:
        return jsonify({"error": f"no such case: {case_id} in pack {name}"}), 404
    envelope, source = _envelope_for(data, False, pack_name=name)
    result = triage(pack, envelope, kernel_policy, _STATE())
    panel = result.to_panel()
    panel["pack"] = name
    panel["customer_email"] = data.get("customer_email", "")
    panel["title"] = data.get("title", case_id)
    panel["expected_disposition"] = data.get("expect")
    panel["envelope_source"] = source
    panel["overrode_agent"] = panel["adapter_disposition"] != panel["agent_recommended"]

    # Close the earn→spend loop: if a cloud case auto-provisions, execute and log the spend.
    if name == "cloud" and panel.get("adapter_disposition") == "auto_provision":
        amount = data.get("envelope", {}).get("amount", 0.0)
        execution = _execute_provision(case_id, data, amount)
        _log_spend(case_id, execution.get("provider", "unknown"), amount, data.get("title", case_id), execution)
        panel["execution"] = execution
        panel["spend_logged"] = True

    return jsonify(panel)


@bp.route("/cases", methods=["GET"])
def cases():
    name = _pack_name()
    pack, _, corpus_dir = _resolve_pack(name)
    if pack is None:
        return jsonify({"error": f"unknown pack: {name}", "packs": available()}), 404
    out = []
    for path in sorted(corpus_dir.glob("*.json")):
        data = json.loads(path.read_text())
        out.append({
            "case_id": path.stem,
            "title": data.get("title", path.stem),
            "expect": data.get("expect"),
            "customer_email": data.get("customer_email", ""),
            "amount": data["envelope"]["amount"],
        })
    return jsonify({"pack": name, "cases": out})


@bp.route("/run", methods=["GET", "POST"])
@rate_limited
def run():
    payload = request.get_json(force=True, silent=True) or {}
    name = _pack_name()
    pack, kernel_policy, corpus_dir = _resolve_pack(name)
    if pack is None:
        return jsonify({"error": f"unknown pack: {name}", "packs": available()}), 404
    case_id = (request.args.get("case_id") or payload.get("case_id") or "").strip()
    live = request.args.get("live") in ("1", "true") or bool(payload.get("live"))
    data = _load_case(corpus_dir, case_id)
    if not data:
        return jsonify({"error": f"no such case: {case_id}"}), 404

    envelope, source = _envelope_for(data, live and name == "refunds", pack_name=name)
    result = triage(pack, envelope, kernel_policy, _STATE())
    panel = result.to_panel()
    panel["pack"] = name
    panel["customer_email"] = data.get("customer_email", "")
    panel["title"] = data.get("title", case_id)
    panel["expected_disposition"] = data.get("expect")
    panel["envelope_source"] = source
    panel["overrode_agent"] = panel["adapter_disposition"] != panel["agent_recommended"]
    return jsonify(panel)


@bp.route("/custom", methods=["POST"])
@rate_limited
def custom():
    """Run the triage engine on a visitor-submitted free-form message against
    one of three sandbox fixtures (refunds / purchasing / cloud).

    Each pack has a known ground-truth order/PO/job in its ledger so every
    factual claim can be checked against real data. Visitors can submit
    any input — honest ones pass, lies get CONTRADICTED.
    """
    payload = request.get_json(force=True, silent=True) or {}
    name = (payload.get("pack") or "refunds").strip()
    sandbox = _CUSTOM_SANDBOX.get(name)
    if sandbox is None:
        return jsonify({
            "error": f"unknown pack: {name!r}. Pick one of: {', '.join(_CUSTOM_SANDBOX)}",
            "packs": list(_CUSTOM_SANDBOX),
        }), 400

    text = (payload.get("customer_email") or payload.get("message") or "").strip()
    if not text:
        return jsonify({"error": "customer_email is required"}), 400
    if len(text) > 2000:
        return jsonify({"error": "message too long (max 2000 chars)"}), 400

    # Sandbox order — known ground truth so the lie-catch demo is reproducible
    # across all three packs. The amount can be overridden by the payload for
    # tests, but defaults to the canonical sandbox amount.
    try:
        amount = float(payload.get("amount") or sandbox["amount"])
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400
    if not math.isfinite(amount) or amount <= 0:
        return jsonify({"error": "amount must be a finite positive number"}), 400
    case_input = {
        "case_id": "visitor-custom",
        "customer_id": sandbox["customer_id"],
        "order_id": sandbox["order_id"],
        "amount": amount,
        "customer_email": text,
    }

    pack, kernel_policy, _ = _resolve_pack(name)
    if pack is None:
        return jsonify({"error": f"{name} pack unavailable"}), 500

    extractor = _EXTRACTORS.get(name, refunds_extract_envelope)

    def _conservative_envelope() -> Envelope:
        # Redundancy: the kernel fact-check (Phase 2) is deterministic and
        # needs ZERO AI, so a missing or unreachable reasoning layer must never
        # take triage down. We degrade to a conservative escalate envelope and
        # still run the real kernel verification this demo is about — the page
        # stays up and labels the source honestly.
        return Envelope.from_dict({
            "case_id": "visitor-custom",
            "customer_id": sandbox["customer_id"],
            "order_id": sandbox["order_id"],
            "amount": case_input["amount"],
            "requested_action": sandbox["action"],
            "recommended_disposition": "escalate_ambiguous",
            "confidence": 0.5,
            "agent_summary": "AI reasoning layer offline; the kernel still fact-checks every claim.",
            "policy_clauses_cited": [],
            "claims": [],
        })

    # Proceed if EITHER reasoning key is present — the router's primary is
    # OpenRouter (_KEYS_ENV), with NIM (_NVIDIA_SECRET) as fallback, so
    # gating solely on the NVIDIA file (old behavior) 503'd even when
    # OpenRouter could have served it. With neither key, skip the live call
    # entirely and degrade instead of failing the whole request.
    have_reasoning = _NVIDIA_SECRET.exists() or _KEYS_ENV.exists()
    if not have_reasoning:
        envelope = _conservative_envelope()
        source = "fallback (reasoning offline — kernel verification still live)"
    else:
        client = _make_client()
        # No retry (tried and reverted 2026-07-05): this reasoning model spends
        # real generation time (10-25s+) on every call regardless of whether the
        # output ends up parsing -- a "retry only on parse error" attempt still
        # measured 65s+ end-to-end on some inputs, blowing past the Worker's own
        # 55s slow-path ceiling and turning a parse failure into a visitor-facing
        # timeout, which is strictly worse. One clean attempt; the token-budget
        # fix above (1200 -> 2200) already fixes most of what used to fail here.
        try:
            envelope = extractor(case_input, client)
            source = client.name
        except (EnvelopeParseError, OSError, KeyError, RuntimeError) as e:
            envelope = _conservative_envelope()
            source = f"fallback (live call failed: {e})"

    result = triage(pack, envelope, kernel_policy, _STATE())
    panel = result.to_panel()
    panel["pack"] = name
    panel["customer_email"] = text
    panel["title"] = "Visitor submission"
    panel["expected_disposition"] = None
    panel["envelope_source"] = source
    panel["overrode_agent"] = panel["adapter_disposition"] != panel["agent_recommended"]
    panel["sandbox"] = {
        "label": sandbox["sandbox_label"],
        "order_id": sandbox["order_id"],
        "amount": case_input["amount"],
    }
    return jsonify(panel)


@bp.route("/replay", methods=["POST"])
def replay():
    payload = request.get_json(force=True, silent=True) or {}
    name = _pack_name()
    pack, kernel_policy, corpus_dir = _resolve_pack(name)
    if pack is None:
        return jsonify({"error": f"unknown pack: {name}", "packs": available()}), 404
    case_id = (payload.get("case_id") or "03-out-of-window-no-reason").strip()
    overrides = payload.get("rule_overrides") or {"window_days": 45}
    data = _load_case(corpus_dir, case_id)
    if not data:
        return jsonify({"error": f"no such case: {case_id}"}), 404
    envelope = Envelope.from_dict(data["envelope"])
    before, after = replay_with_policy_change(
        pack, envelope, kernel_policy, _STATE(), rule_overrides=overrides
    )
    return jsonify({
        "pack": name,
        "case_id": case_id,
        "rule_overrides": overrides,
        "before": before.to_panel(),
        "after": after.to_panel(),
        "flipped": before.adapter_disposition != after.adapter_disposition,
    })
