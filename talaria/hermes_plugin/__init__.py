"""talaria-guard — the Hermes Agent plugin that enforces your policy.

Wires Hermes' tool-call loop to a Custodian guard-adapter pipeline
compiled from ``~/.talaria/policy.yaml``. Two hooks (the same contract
Nous' own security-guidance plugin uses):

* ``pre_tool_call``  — runs the pipeline's pre_action on every proposed
  tool call. A DENY becomes ``{"action": "block", "message": <reason>}``,
  which Hermes turns into the tool result the model sees. Denials are
  recorded to the tamper-evident denial log as they happen.
* ``transform_tool_result`` — runs post_action on the result string;
  redactions (secret-leak-guard, pii-redactor) rewrite what the model
  sees next turn. A post-action DENY (an adapter judging the raw result
  unsafe to hand back at all) suppresses the output entirely rather than
  returning it — found in review that the original version returned
  ``ctx.output`` unconditionally on both TRANSFORM and DENY, which for a
  DENY meant returning the very output that was supposed to be blocked.

The pipeline is built once per process and reused — so editing
``~/.talaria/policy.yaml`` requires restarting Hermes to take effect,
same as any other Hermes plugin config. If custodian-kernel isn't
importable (dev checkout not on the path), the plugin logs the failure
to stderr and no-ops — it fails OPEN with a loud message rather than
silently pretending to protect.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Dev fallback: if custodian isn't installed into Hermes' venv yet, allow a
# checkout to be pointed at via TALARIA_GUARD_DEV_PATH (defaults to the
# usual dev location). Once `pip install custodian-kernel` has run into the
# Hermes venv this branch is a no-op.
_DEV_PATH = Path(os.environ.get("TALARIA_GUARD_DEV_PATH", "~/Development/custodian-dev")).expanduser()
if _DEV_PATH.is_dir() and str(_DEV_PATH) not in sys.path:
    sys.path.insert(0, str(_DEV_PATH))

try:
    from custodian.adapters.base import ActionContext
    from talaria.policy import build_pipeline, load_policy
    from talaria.denial_log import DenialLog
    _IMPORT_ERROR: Optional[Exception] = None
except Exception as e:  # pragma: no cover - exercised only without the dep
    _IMPORT_ERROR = e
    ActionContext = build_pipeline = load_policy = DenialLog = None  # type: ignore

_PIPELINE = None


def _open_vault_best_effort():
    """Open the credential vault for EgressDomainGuard's host-restriction
    metadata. Best-effort and silent on failure — a missing/misconfigured
    vault (no WARDEN_KEYFILE, wrong passphrase, no vault created yet) must
    never crash the plugin or block tool calls; it just means host
    restrictions on secrets won't be enforced until the vault is reachable."""
    try:
        from warden.vault import Vault
        return Vault.open_from_env(interactive=False)
    except Exception:
        return None


def _pipeline():
    global _PIPELINE
    if _PIPELINE is None:
        policy = load_policy()
        observer = None
        if policy.get("log_denials", True):
            try:
                observer = DenialLog(log_warns=False).observer()
            except Exception as e:
                print(f"[talaria-guard] denial log unavailable: {e}", file=sys.stderr)
        vault = _open_vault_best_effort()
        _PIPELINE = build_pipeline(policy, denial_observer=observer, vault=vault)
    return _PIPELINE


def _on_pre_tool_call(tool_name: str = "", args: Any = None, **_: Any) -> Optional[Dict[str, str]]:
    if _IMPORT_ERROR is not None:
        print(f"[talaria-guard] DISABLED — custodian import failed: {_IMPORT_ERROR}",
              file=sys.stderr)
        return None
    ctx = ActionContext(skill=tool_name, args=args if isinstance(args, dict) else {})
    result = _pipeline().run_pre(ctx)
    if result.allowed:
        return None
    return {"action": "block", "message": f"[talaria-guard] {result.summary()}"}


def _on_transform_tool_result(tool_name: str = "", args: Any = None,
                              result: Any = None, **_: Any) -> Optional[str]:
    if _IMPORT_ERROR is not None or not isinstance(result, str):
        return None
    ctx = ActionContext(skill=tool_name, args=args if isinstance(args, dict) else {},
                        output=result)
    outcome = _pipeline().run_post(ctx)
    if outcome.denials:
        # A post_action DENY means an adapter judged the raw result unsafe
        # to hand back at all. ctx.output may carry a partial TRANSFORM
        # applied by an earlier adapter before the DENY fired — returning
        # it would still leak whatever wasn't yet redacted. Suppress
        # outright instead.
        reasons = "; ".join(v.reason for v in outcome.denials)
        return f"[talaria-guard] output suppressed: {reasons}"
    if not outcome.transforms:
        return None
    return ctx.output


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("transform_tool_result", _on_transform_tool_result)
