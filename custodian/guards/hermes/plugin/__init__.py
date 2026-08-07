"""custodian-hermes-guard — the repository-owned Hermes Agent plugin.

Wires Hermes' tool-call loop to the Custodian guard pipeline through the
OSS :mod:`custodian.guards.hermes` runtime. Two hooks (the same contract
Nous' own security-guidance plugin uses):

* ``pre_tool_call`` — runs the guard's pre-action on every proposed tool
  call. A denial becomes ``{"action": "block", "message": <reason>}``,
  which Hermes turns into the tool result the model sees. An
  ``escalation_required`` decision is *not* permission: the plugin waits
  (bounded) for the operator's digest-bound approval before allowing the
  call, and fails closed on timeout or denial.
* ``transform_tool_result`` — runs post-action guards on the result
  string; redactions (secret-leak, PII, prompt-injection) rewrite what the
  model sees next turn. A post-action deny (or guard failure) suppresses
  the output entirely rather than returning it.

This is the OSS plugin: it contains no operator paths, profiles, policy,
credentials, or launch configuration. The operator's Hermes profile only
installs/enables a released version of this plugin and supplies
operator-owned configuration (policy files, protected paths, approval
window) through the shared Custodian state directory. This plugin must
never grow a parallel personal policy engine.

If the kernel, policy loading, or the guard pipeline cannot be initialized,
the pre-tool hook blocks the call. A security plugin must never turn an
installation problem into unrestricted agent execution.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

from custodian.guards.hermes.contract import HERMES_GUARD_CONTRACT_VERSION, approval_wait_seconds

try:
    from custodian.guards.hermes.runtime import HermesGuardRuntime, _DisabledGuardError, _FailClosedError
    _IMPORT_ERROR: Optional[Exception] = None
except Exception as e:  # pragma: no cover - exercised only without the dep
    _IMPORT_ERROR = e
    HermesGuardRuntime = None  # type: ignore
    _DisabledGuardError = RuntimeError  # type: ignore
    _FailClosedError = RuntimeError  # type: ignore

_RUNTIME = None
_DISABLED = False
_FAIL_CLOSED = False


def _runtime():
    global _RUNTIME, _DISABLED
    if _DISABLED:
        return None
    if _RUNTIME is None:
        try:
            _RUNTIME = HermesGuardRuntime(
                # vault=None: this OSS plugin must not import Paladin (the
                # kernel stays brand-neutral; Paladin is reached only from the
                # deployment layer via the `paladin` CLI). The runtime never
                # reads vault material; egress/credential metadata is a
                # deployment-shim concern.
                vault=None,
                notifier=lambda message: print(f"[hermes-guard] {message}", file=sys.stderr),
            )
        except _DisabledGuardError:
            _DISABLED = True
            return None
        except _FailClosedError as exc:
            print(f"[hermes-guard] BLOCKED — {exc}", file=sys.stderr)
            _FAIL_CLOSED = True
            return None
    return _RUNTIME


def _pipeline():
    """Compatibility shim for callers that inspect the compiled pipeline."""
    return _runtime().pipeline


def _wait_seconds() -> float:
    """Resolve the approval-wait window.

    Operator policy (from the loaded ``policy.yaml``) wins over the
    environment. The environment fallback is delegated to
    :func:`custodian.guards.hermes.contract.approval_wait_seconds`, which
    honors the brand-neutral ``CUSTODIAN_APPROVAL_WAIT_SECONDS`` and
    keeps the legacy ``TALARIA_APPROVAL_WAIT_SECONDS`` as a compat shim.
    """
    policy = _runtime().policy.get("operator") or {}
    if isinstance(policy, dict) and "approval_wait_seconds" in policy:
        try:
            return max(0.0, min(3600.0, float(policy["approval_wait_seconds"])))
        except (TypeError, ValueError):
            pass
    return float(approval_wait_seconds())


def _on_pre_tool_call(tool_name: str = "", args: Any = None, **_: Any) -> Optional[Dict[str, str]]:
    if _FAIL_CLOSED:
        return {
            "action": "block",
            "message": "[hermes-guard] unavailable; tool call blocked (gate state unreadable — failing closed)",
        }
    if _IMPORT_ERROR is not None:
        print(f"[hermes-guard] BLOCKED — custodian import failed: {_IMPORT_ERROR}",
              file=sys.stderr)
        return {
            "action": "block",
            "message": "[hermes-guard] unavailable; tool call blocked (kernel import failed)",
        }
    if _runtime() is None:
        # Guard is dormant (operator did not `custodian guards enable hermes`).
        # Pass through unchanged so a disabled guard costs nothing.
        return None
    try:
        _pipeline()  # compatibility probe; initialization remains fail-closed
        decision = _runtime().evaluate_pre(
            tool_name,
            args if isinstance(args, dict) else {},
            approval_id=str(_.get("approval_id", "") or ""),
            requester=str(_.get("requester", "hermes:agent") or "hermes:agent"),
            workspace=_.get("workspace"),
            correlation_id=str(_.get("correlation_id", "") or ""),
            session_id=str(_.get("session_id", "") or ""),
            task_id=str(_.get("task_id", "") or ""),
        )
        if decision.verdict == "escalation_required" and decision.approval_id:
            decision = _runtime().wait_for_approval(
                tool_name,
                args if isinstance(args, dict) else {},
                approval_id=decision.approval_id,
                requester=str(_.get("requester", "hermes:agent") or "hermes:agent"),
                workspace=_.get("workspace"),
                correlation_id=str(_.get("correlation_id", "") or ""),
                session_id=str(_.get("session_id", "") or ""),
                timeout_seconds=approval_wait_seconds(),
            )
    except Exception as exc:
        print(f"[hermes-guard] BLOCKED — guard evaluation failed: {exc}", file=sys.stderr)
        return {
            "action": "block",
            "message": "[hermes-guard] unavailable; tool call blocked (guard evaluation failed)",
        }
    if decision.allowed:
        return None
    message = decision.notification or f"Custodian blocked this {decision.action_kind}: {decision.reason}"
    if decision.approval_id:
        message += f" Approval: {decision.approval_id}"
    return {"action": "block", "message": f"[hermes-guard] {message}"}


def _on_transform_tool_result(tool_name: str = "", args: Any = None,
                              result: Any = None, **_: Any) -> Optional[str]:
    if not isinstance(result, str):
        return None
    if _IMPORT_ERROR is not None:
        return "[hermes-guard] output suppressed: guard unavailable"
    if _runtime() is None:
        # Guard dormant — no post-action scanning either.
        return None
    try:
        _pipeline()  # compatibility probe; initialization remains fail-closed
        return _runtime().inspect_result(
            tool_name, args if isinstance(args, dict) else {}, result,
        )
    except Exception as exc:
        print(f"[hermes-guard] output suppressed — post-action guard failed: {exc}",
              file=sys.stderr)
        return "[hermes-guard] output suppressed: guard evaluation failed"


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("transform_tool_result", _on_transform_tool_result)
